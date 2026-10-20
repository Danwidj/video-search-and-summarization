// SPDX-License-Identifier: Apache-2.0

// The finals database's reviewer version, modelled over the fake PostgREST
// store: the effective_* views and the set_review_status and
// save_human_report_edit RPCs of the finals baseline migration
// (supabase/migrations/*_finals_baseline.sql). Only the behaviour the console
// relies on is modelled: which version is read, the review transition and the
// result keys. Validation, ID renumbering and legacy normalisation are not;
// the SQL test harness under supabase/tests covers them.

const sameRun = (a, b) => a.incident_id === b.incident_id && a.model_run_id === b.model_run_id;
const runOf = (args) => ({ incident_id: args.p_incident_id, model_run_id: args.p_model_run_id });
const storedNow = () => new Date().toISOString().replace('Z', '');
const humanOf = (store, run) => (store.human_reports ?? []).find((row) => sameRun(row, run));

/** The AI items of runs without a reviewer version, then the reviewer's items. */
function effectiveItems(aiTable, humanTable, idColumn) {
  return (store) => [
    ...(store[aiTable] ?? []).filter((row) => !humanOf(store, row)).map((row) => ({ ...row, [`source_${idColumn}`]: row[idColumn], source: 'ai' })),
    ...(store[humanTable] ?? []).map((row) => ({ ...row, image: null, source: 'human' })),
  ];
}

export const effectiveViews = {
  effective_incidents: (store) => (store.incidents ?? []).map((incident) => {
    const human = humanOf(store, incident);
    if (!human) return { ...incident, source: 'ai' };
    return {
      ...incident, type: human.type, start_timestamp: String(human.start_seconds), end_timestamp: String(human.end_seconds),
      duration: human.end_seconds - human.start_seconds, description: human.description, severity_level: human.severity_level, source: 'human',
    };
  }),
  effective_entities: effectiveItems('entities', 'human_report_entities', 'entity_id'),
  effective_instruments: effectiveItems('instruments', 'human_report_instruments', 'instrument_id'),
  effective_assets: effectiveItems('assets', 'human_report_assets', 'asset_id'),
};

function requireIncident(store, run) {
  if (!(store.incidents ?? []).some((row) => sameRun(row, run))) throw new Error('Report not found for this video and model run');
}

function upsert(store, table, run, values) {
  const rows = (store[table] ??= []);
  const index = rows.findIndex((row) => sameRun(row, run));
  if (index >= 0) rows[index] = { ...rows[index], ...values };
  else rows.push({ ...run, ...values });
  return rows[index >= 0 ? index : rows.length - 1];
}

/** Replaces the run's reviewer items; source_* is the item's source_id, else the AI item with the same ID. */
function replaceItems(store, run, aiTable, humanTable, idColumn, items) {
  store[humanTable] = (store[humanTable] ?? []).filter((row) => !sameRun(row, run));
  for (const { source_id: sourceId, ...item } of items) {
    const sameId = (store[aiTable] ?? []).some((row) => sameRun(row, run) && row[idColumn] === item[idColumn]);
    store[humanTable].push({ ...run, ...item, [`source_${idColumn}`]: sourceId !== undefined ? sourceId : sameId ? item[idColumn] : null });
  }
}

function setReviewStatus(args, store) {
  const run = runOf(args);
  requireIncident(store, run);
  const reviewer = args.p_reviewer.trim();
  const status = args.p_status;
  const result = { incidentId: run.incident_id, modelRunId: run.model_run_id, status };
  const current = (store.review_status ?? []).find((row) => sameRun(row, run));
  if ((current?.status ?? 'unreviewed') === status) return { ...result, changed: false };
  const now = storedNow();
  const verified = status === 'verified';
  const humanVersionCreated = verified && !humanOf(store, run);
  if (humanVersionCreated) {
    const ai = store.incidents.find((row) => sameRun(row, run));
    upsert(store, 'human_reports', run, {
      type: ai.type, start_seconds: Number(ai.start_timestamp), end_seconds: Number(ai.end_timestamp), description: ai.description,
      severity_level: ai.severity_level, revision: 1, created_by: reviewer, created_at: now, edited_by: null, edited_at: null,
    });
    const aiItems = (table, columns) => (store[table] ?? []).filter((row) => sameRun(row, run)).map((row) => Object.fromEntries(columns.map((column) => [column, row[column]])));
    replaceItems(store, run, 'entities', 'human_report_entities', 'entity_id', aiItems('entities', ['entity_id', 'type', 'description']));
    replaceItems(store, run, 'instruments', 'human_report_instruments', 'instrument_id', aiItems('instruments', ['instrument_id', 'entity_id', 'name', 'description', 'threat_level']));
    replaceItems(store, run, 'assets', 'human_report_assets', 'asset_id', aiItems('assets', ['asset_id', 'name', 'description']));
  }
  // Never writes edited_by / edited_at.
  upsert(store, 'review_status', run, { status, verified_by: verified ? reviewer : null, verified_at: verified ? now : null });
  return { ...result, verifiedBy: verified ? reviewer : null, verifiedAt: verified ? now : null, changed: true, humanVersionCreated };
}

function saveHumanReportEdit(args, store) {
  const run = runOf(args);
  requireIncident(store, run);
  const editor = args.p_edited_by.trim();
  const now = storedNow();
  const { incident, entities, instruments, assets } = args.p_edit;
  const revision = (humanOf(store, run)?.revision ?? 0) + 1;
  upsert(store, 'human_reports', run, {
    type: incident.type, start_seconds: incident.start_timestamp, end_seconds: incident.end_timestamp, description: incident.description,
    severity_level: incident.severity_level, revision, created_by: humanOf(store, run)?.created_by ?? editor, edited_by: editor, edited_at: now,
  });
  replaceItems(store, run, 'entities', 'human_report_entities', 'entity_id', entities);
  replaceItems(store, run, 'instruments', 'human_report_instruments', 'instrument_id', instruments);
  replaceItems(store, run, 'assets', 'human_report_assets', 'asset_id', assets);
  const current = (store.review_status ?? []).find((row) => sameRun(row, run));
  const reopened = current?.status === 'verified';
  const review = upsert(store, 'review_status', run, {
    status: reopened ? 'under review' : current?.status ?? 'unreviewed', edited_by: editor, edited_at: now,
    ...(reopened ? { verified_by: null, verified_at: null } : {}),
  });
  return {
    incidentId: run.incident_id, modelRunId: run.model_run_id, editedBy: editor, editedAt: now,
    duration: incident.end_timestamp - incident.start_timestamp, revision, status: review.status,
  };
}

export const reviewerRpcs = { set_review_status: setReviewStatus, save_human_report_edit: saveHumanReportEdit };
