// SPDX-License-Identifier: Apache-2.0

// The finals database's reviewer version, modelled over the fake PostgREST
// store: the effective_* views and the set_review_status and
// save_human_report_edit RPCs of the finals baseline migration
// (supabase/migrations/*_finals_baseline.sql). Only the behaviour the console
// relies on is modelled: which version is read, the review transition, the
// result keys, and verifying copying the AI report into a renumbered reviewer
// version or refusing one that must be edited first. Edit validation and
// legacy normalisation are not; the SQL test harness under supabase/tests
// covers them.

const sameRun = (a, b) => a.incident_id === b.incident_id && a.model_run_id === b.model_run_id;
const runOf = (args) => ({ incident_id: args.p_incident_id, model_run_id: args.p_model_run_id });
const storedNow = () => new Date().toISOString().replace('Z', '');
const humanOf = (store, run) => (store.human_reports ?? []).find((row) => sameRun(row, run));

/** An AI item as an effective_* view returns it: its own ID is its source. */
const aiItem = (idColumn) => (row) => ({ ...row, [`source_${idColumn}`]: row[idColumn], source: 'ai' });

/** The AI items of runs without a reviewer version, then the reviewer's items. */
function effectiveItems(aiTable, humanTable, idColumn) {
  return (store) => [
    ...(store[aiTable] ?? []).filter((row) => !humanOf(store, row)).map(aiItem(idColumn)),
    ...(store[humanTable] ?? []).map((row) => ({ ...row, image: null, source: 'human' })),
  ];
}

/** A row fixture of a run without a reviewer version (AI table rows), as getRunReport reads it from the effective_* views. */
export const effectiveRowsOfAiRun = (rows) => ({
  ...rows,
  entities: rows.entities.map(aiItem('entity_id')),
  instruments: rows.instruments.map(aiItem('instrument_id')),
  assets: rows.assets.map(aiItem('asset_id')),
});

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

/** Replaces the run's reviewer items; source_* is each item's source_id. */
function replaceItems(store, run, humanTable, idColumn, items) {
  store[humanTable] = (store[humanTable] ?? []).filter((row) => !sameRun(row, run));
  for (const { source_id: sourceId, ...item } of items) store[humanTable].push({ ...run, ...item, [`source_${idColumn}`]: sourceId });
}

const INCIDENT_TYPES = ['road accident', 'burglary', 'explosion', 'assault', 'animal attack'];
const rated = (level) => Number.isInteger(level) && level >= 1 && level <= 5;
const idNumber = (id) => Number(String(id).replace(/\D/g, '')) || Infinity;

/** create_human_report_from_ai: the AI items in ID order, renumbered E#/I#/A#, each naming its AI item; refused when invalid as they stand. */
function copyAiReport(store, run, reviewer, now) {
  const ai = store.incidents.find((row) => sameRun(row, run));
  const start = Number(ai.start_timestamp);
  const end = Number(ai.end_timestamp);
  const items = (table, idColumn) => (store[table] ?? []).filter((row) => sameRun(row, run)).sort((a, b) => idNumber(a[idColumn]) - idNumber(b[idColumn]));
  const entities = items('entities', 'entity_id');
  const instruments = items('instruments', 'instrument_id');
  const entityIds = new Map(entities.map((row, index) => [row.entity_id, `E${index + 1}`]));
  const entityType = (type) => (type === 'person' ? 'human' : type);
  if (!INCIDENT_TYPES.includes(ai.type) || !Number.isInteger(start) || !Number.isInteger(end) || end < start || !rated(ai.severity_level) || ai.description == null
    || entities.some((row) => !['human', 'animal', 'unknown'].includes(entityType(row.type)))
    || instruments.some((row) => !rated(row.threat_level) || (row.entity_id != null && !entityIds.has(row.entity_id)))) {
    throw new Error(`The AI report of run ${run.model_run_id} cannot be verified as it stands; edit it first`);
  }
  upsert(store, 'human_reports', run, {
    type: ai.type, start_seconds: start, end_seconds: end, description: ai.description,
    severity_level: ai.severity_level, revision: 1, created_by: reviewer, created_at: now, edited_by: null, edited_at: null,
  });
  replaceItems(store, run, 'human_report_entities', 'entity_id', entities.map((row, index) => ({
    entity_id: `E${index + 1}`, source_id: row.entity_id, type: entityType(row.type), description: row.description,
  })));
  replaceItems(store, run, 'human_report_instruments', 'instrument_id', instruments.map((row, index) => ({
    instrument_id: `I${index + 1}`, source_id: row.instrument_id, entity_id: row.entity_id == null ? null : entityIds.get(row.entity_id),
    name: row.name, description: row.description, threat_level: row.threat_level,
  })));
  replaceItems(store, run, 'human_report_assets', 'asset_id', items('assets', 'asset_id').map((row, index) => ({
    asset_id: `A${index + 1}`, source_id: row.asset_id, name: row.name, description: row.description,
  })));
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
  if (humanVersionCreated) copyAiReport(store, run, reviewer, now);
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
  replaceItems(store, run, 'human_report_entities', 'entity_id', entities);
  replaceItems(store, run, 'human_report_instruments', 'instrument_id', instruments);
  replaceItems(store, run, 'human_report_assets', 'asset_id', assets);
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
