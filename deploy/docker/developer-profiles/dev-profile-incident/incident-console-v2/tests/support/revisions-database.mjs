// SPDX-License-Identifier: Apache-2.0

// The versioned report database over the fake PostgREST store: the
// save_human_revision, save_human_revision_with_crops, set_official_revision and set_revision_crops RPCs of supabase/migrations.
// Only the behaviour the console relies on is modelled: numbering and parentage
// of a human revision, its refusals, the official pointer and the crops it
// rebuilds. Payload validation and facet derivation are not; the SQL test
// harness under supabase/tests covers them.

const storedNow = () => new Date().toISOString().replace('Z', '');

const revisionsOf = (store, videoId) => (store.report_revisions ?? []).filter((row) => row.video_id === videoId);

export const revisionRpcs = {
  save_human_revision: (args, store) => {
    const video = store.videos.find((row) => row.id === args.p_video_id);
    if (!video) throw new Error(`Video not found: ${args.p_video_id}`);
    const all = revisionsOf(store, args.p_video_id);
    const parent = all.find((row) => row.id === args.p_parent_id);
    if (!parent) throw new Error(`Revision not found for this video: ${args.p_parent_id}`);
    const by = String(args.p_created_by ?? '').trim();
    if (!by || by.length > 256) throw new Error('A reviewer name of 1 to 256 characters is required');
    const row = {
      id: Math.max(0, ...store.report_revisions.map((existing) => existing.id)) + 1,
      video_id: args.p_video_id,
      revision_no: Math.max(...all.map((existing) => existing.revision_no)) + 1,
      kind: 'human',
      model_run_id: parent.model_run_id,
      parent_id: parent.id,
      payload: args.p_payload,
      evidence: args.p_evidence,
      incident_type: args.p_incident_type ?? null,
      severity_level: args.p_severity_level ?? null,
      start_seconds: args.p_start_seconds ?? null,
      end_seconds: args.p_end_seconds ?? null,
      created_by: by,
      created_at: storedNow(),
      note: String(args.p_note ?? '').trim() || null,
    };
    store.report_revisions.push(row);
    return {
      revisionId: row.id,
      revisionNo: row.revision_no,
      videoId: row.video_id,
      kind: row.kind,
      parentId: row.parent_id,
      modelRunId: row.model_run_id,
      createdBy: row.created_by,
      createdAt: row.created_at,
      note: row.note,
    };
  },

  // As the SQL function: the crops are checked before anything is written, and on a video with no official
  // revision they replace the video's rows for the new revision in the same call.
  save_human_revision_with_crops: (args, store) => {
    const video = store.videos.find((row) => row.id === args.p_video_id);
    if (!video) throw new Error(`Video not found: ${args.p_video_id}`);
    if (!Array.isArray(args.p_crops ?? [])) throw new Error('The crops must be a list');
    const searchable = video.official_revision_id === null || video.official_revision_id === undefined;
    const saved = revisionRpcs.save_human_revision(args, store);
    if (searchable) store.evidence_crops = (args.p_crops ?? []).map((crop) => ({ revision_id: saved.revisionId, ...crop }));
    return { ...saved, crops: searchable ? store.evidence_crops.length : 0 };
  },

  set_official_revision: (args, store) => {
    const video = store.videos.find((row) => row.id === args.p_video_id);
    if (!video) throw new Error(`Video not found: ${args.p_video_id}`);
    if (args.p_revision_id !== null && !revisionsOf(store, args.p_video_id).some((row) => row.id === args.p_revision_id)) {
      throw new Error(`Revision not found for this video: ${args.p_revision_id}`);
    }
    store.evidence_crops = [];
    video.official_revision_id = args.p_revision_id;
    if (args.p_revision_id !== null) {
      store.evidence_crops = (args.p_crops ?? []).map((crop) => ({ revision_id: args.p_revision_id, ...crop }));
    }
    return { videoId: args.p_video_id, officialRevisionId: args.p_revision_id, crops: store.evidence_crops.length };
  },

  set_revision_crops: (args, store) => {
    const video = store.videos.find((row) => row.id === args.p_video_id);
    if (!video) throw new Error(`Video not found: ${args.p_video_id}`);
    const searchable = video.official_revision_id ?? Math.max(0, ...revisionsOf(store, args.p_video_id).map((row) => row.id));
    if (args.p_revision_id !== searchable) {
      throw new Error(
        `Revision ${args.p_revision_id} is not the searchable revision of video ${args.p_video_id} (the official revision, else the newest)`,
      );
    }
    store.evidence_crops = (args.p_crops ?? []).map((crop) => ({ revision_id: args.p_revision_id, ...crop }));
    return { videoId: args.p_video_id, revisionId: args.p_revision_id, crops: store.evidence_crops.length };
  },
};
