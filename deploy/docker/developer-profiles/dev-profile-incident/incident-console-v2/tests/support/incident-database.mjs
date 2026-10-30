// SPDX-License-Identifier: Apache-2.0

// The mvp3 incident database over the fake PostgREST store: the
// save_human_revision_with_crops, set_official_revision, create_ai_revision,
// set_revision_crops, replace_video_crops and merge_incidents RPCs of
// supabase/migrations. Only the behaviour the console relies on is modelled:
// numbering, parentage and coverage of a revision, its refusals, the official
// pointer and the crops. Payload validation and facet derivation are not; the
// SQL test harness under supabase/tests covers them. An RPC refuses like a
// RAISE EXCEPTION by throwing an Error.

const storedNow = () => new Date().toISOString().replace('Z', '');

const revisionsOf = (store, incidentId) => store.report_revisions.filter((row) => row.incident_id === incidentId);
const videosOf = (store, incidentId) => store.videos.filter((row) => row.incident_id === incidentId);

function incidentOrRefuse(store, incidentId) {
  const incident = store.incidents.find((row) => row.id === incidentId);
  if (!incident) throw new Error(`Incident not found: ${incidentId}`);
  return incident;
}

/** The official revision, else the newest (searchable_revision_id). */
function searchable(store, incidentId) {
  const incident = incidentOrRefuse(store, incidentId);
  if (incident.official_revision_id != null) return incident.official_revision_id;
  const all = revisionsOf(store, incidentId);
  return all.length ? all.reduce((a, b) => (b.revision_no > a.revision_no ? b : a)).id : null;
}

function insertCrops(store, revisionId, crops) {
  const unique = new Map();
  for (const crop of crops) {
    if (String(crop.image ?? '').trim() && String(crop.item_id ?? '').trim()) {
      unique.set(`${crop.video_id}|${crop.item_type}|${crop.item_id}`, crop);
    }
  }
  for (const crop of unique.values()) store.evidence_crops.push({ ...crop, revision_id: revisionId });
  return unique.size;
}

function newRevision(store, fields) {
  const all = revisionsOf(store, fields.incident_id);
  const row = {
    id: Math.max(0, ...store.report_revisions.map((existing) => existing.id)) + 1,
    revision_no: Math.max(0, ...all.map((existing) => existing.revision_no)) + 1,
    created_at: storedNow(),
    ...fields,
  };
  store.report_revisions.push(row);
  return row;
}

export const incidentRpcs = {
  save_human_revision_with_crops: (args, store) => {
    incidentOrRefuse(store, args.p_incident_id);
    const parent = revisionsOf(store, args.p_incident_id).find((row) => row.id === args.p_parent_id);
    if (!parent) throw new Error(`Revision not found for this incident: ${args.p_parent_id}`);
    const by = String(args.p_created_by ?? '').trim();
    if (!by || by.length > 256) throw new Error('A reviewer name of 1 to 256 characters is required');
    if (!Array.isArray(args.p_crops ?? [])) throw new Error('The crops must be a list');
    const here = new Set(videosOf(store, args.p_incident_id).map((video) => video.id));
    for (const crop of args.p_crops ?? []) {
      if (!here.has(crop.video_id) || !parent.video_names.includes(crop.video_id)) {
        throw new Error(`Crop video is not a covered video of this incident: ${crop.video_id}`);
      }
    }
    const row = newRevision(store, {
      incident_id: args.p_incident_id,
      kind: 'human',
      model_run_id: parent.model_run_id,
      parent_id: parent.id,
      payload: args.p_payload,
      evidence: args.p_evidence,
      video_names: parent.video_names,
      incident_type: args.p_incident_type ?? null,
      severity_level: args.p_severity_level ?? null,
      start_seconds: args.p_start_seconds ?? null,
      end_seconds: args.p_end_seconds ?? null,
      created_by: by,
      note: String(args.p_note ?? '').trim() || null,
    });
    return {
      revisionId: row.id,
      revisionNo: row.revision_no,
      incidentId: row.incident_id,
      kind: row.kind,
      parentId: row.parent_id,
      modelRunId: row.model_run_id,
      videoNames: row.video_names,
      createdBy: row.created_by,
      createdAt: row.created_at,
      note: row.note,
      crops: insertCrops(store, row.id, args.p_crops ?? []),
    };
  },

  set_official_revision: (args, store) => {
    const incident = incidentOrRefuse(store, args.p_incident_id);
    if (args.p_revision_id !== null && !revisionsOf(store, args.p_incident_id).some((row) => row.id === args.p_revision_id)) {
      throw new Error(`Revision not found for this incident: ${args.p_revision_id}`);
    }
    if (args.p_revision_id === null) incident.official_since = null;
    else if (incident.official_revision_id !== args.p_revision_id || !incident.official_since) incident.official_since = storedNow();
    incident.official_revision_id = args.p_revision_id;
    return { incidentId: incident.id, officialRevisionId: incident.official_revision_id, officialSince: incident.official_since };
  },

  create_ai_revision: (args, store) => {
    incidentOrRefuse(store, args.p_incident_id);
    const names = args.p_video_names ?? [];
    if (!names.length) throw new Error('A revision must cover at least one video');
    const here = new Set(videosOf(store, args.p_incident_id).map((video) => video.id));
    for (const name of names) {
      if (!String(name).trim() || !here.has(name)) throw new Error(`Video ${name} is not in incident ${args.p_incident_id}`);
    }
    if (!store.model_runs.some((run) => run.id === args.p_model_run_id)) throw new Error(`Model run not found: ${args.p_model_run_id}`);
    const row = newRevision(store, {
      incident_id: args.p_incident_id,
      kind: 'ai',
      model_run_id: args.p_model_run_id,
      parent_id: null,
      payload: args.p_payload,
      evidence: args.p_evidence,
      video_names: [...new Set(names)],
      embedding: args.p_embedding ?? null,
      created_by: null,
      note: String(args.p_note ?? '').trim() || null,
    });
    let crops = 0;
    for (const video of row.video_names) {
      const mine = store.evidence_crops.filter((crop) => crop.video_id === video && crop.revision_id !== row.id);
      const latest = Math.max(-1, ...mine.map((crop) => crop.revision_id));
      crops += insertCrops(
        store,
        row.id,
        mine.filter((crop) => crop.revision_id === latest),
      );
    }
    return { revisionId: row.id, revisionNo: row.revision_no, crops };
  },

  replace_video_crops: (args, store) => {
    if (!videosOf(store, args.p_incident_id).some((video) => video.id === args.p_video_id)) {
      throw new Error(`Video ${args.p_video_id} is not in incident ${args.p_incident_id}`);
    }
    if (args.p_revision_id !== null && !revisionsOf(store, args.p_incident_id).some((row) => row.id === args.p_revision_id)) {
      throw new Error(`Revision ${args.p_revision_id} is not in incident ${args.p_incident_id}`);
    }
    store.evidence_crops = store.evidence_crops.filter((crop) => crop.video_id !== args.p_video_id);
    return args.p_revision_id === null
      ? 0
      : insertCrops(
          store,
          args.p_revision_id,
          (args.p_crops ?? []).map((crop) => ({ ...crop, video_id: args.p_video_id })),
        );
  },

  set_revision_crops: (args, store) => {
    incidentOrRefuse(store, args.p_incident_id);
    if (args.p_revision_id !== searchable(store, args.p_incident_id)) {
      throw new Error(`Revision ${args.p_revision_id} is not the searchable revision of incident ${args.p_incident_id}`);
    }
    const here = new Set(videosOf(store, args.p_incident_id).map((video) => video.id));
    for (const crop of args.p_crops ?? []) {
      if (!here.has(crop.video_id)) throw new Error(`Every crop must name a video_id that belongs to incident ${args.p_incident_id}`);
    }
    store.evidence_crops = store.evidence_crops.filter((crop) => !here.has(crop.video_id));
    return {
      incidentId: args.p_incident_id,
      revisionId: args.p_revision_id,
      crops: insertCrops(store, args.p_revision_id, args.p_crops ?? []),
    };
  },

  merge_incidents: (args, store) => {
    if (args.p_target_incident_id === args.p_source_incident_id) throw new Error('An incident cannot be merged into itself');
    incidentOrRefuse(store, args.p_target_incident_id);
    incidentOrRefuse(store, args.p_source_incident_id);
    const moved = videosOf(store, args.p_source_incident_id);
    for (const video of moved) video.incident_id = args.p_target_incident_id;
    const sourceRevisions = new Set(revisionsOf(store, args.p_source_incident_id).map((row) => row.id));
    const orphaned = store.evidence_crops.filter((crop) => sourceRevisions.has(crop.revision_id)).map((crop) => crop.image);
    store.evidence_crops = store.evidence_crops.filter((crop) => !sourceRevisions.has(crop.revision_id));
    store.report_revisions = store.report_revisions.filter((row) => !sourceRevisions.has(row.id));
    store.incidents = store.incidents.filter((row) => row.id !== args.p_source_incident_id);
    return {
      incident_id: args.p_target_incident_id,
      source_incident_id: args.p_source_incident_id,
      moved_video_ids: moved.map((video) => video.id),
      orphaned_crop_images: [...new Set(orphaned)],
    };
  },
};
