-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Midterm -> finals transform. Run by copy_midterm_to_finals.py inside ONE transaction on the
-- finals database, after the raw midterm rows were streamed into temp tables src_<table>
-- (same columns as public.<table>). Nothing here reads or writes midterm.
--
-- What it does, in FK order:
--   leave behind: the 20 orphaned runs (their video was deleted), the 15 unlinked test runs
--                 (mock-run-*, nmtest0925a: no incident, no video, no reader can reach them) and
--                 8 broken uploads (no incident, ground truth or attempt, and no playable file);
--   relabel:      incidents fighting -> assault, animal -> animal attack; entities person -> human;
--                 entity crops' item_name person -> human;
--   split:        a reviewer version for every edited report (from the stored rows) and every
--                 verified report (copy of the AI rows); edited reports get their AI rows back
--                 from the immutable notes record;
--   stamps:       review_status.edited_by/at cleared where provably not a content edit.
-- Leaves migration_* temp tables behind for the script's checks; they vanish with the session.

-- 1. What stays behind ------------------------------------------------------------------------
CREATE TEMP TABLE migration_excluded_runs AS
SELECT mr.id, CASE WHEN linked.video_id IS NULL THEN 'unlinked test run' ELSE 'orphan: video deleted' END AS reason
FROM src_model_runs mr
CROSS JOIN LATERAL (SELECT COALESCE(
    public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,videoId}',
    public.try_parse_jsonb(mr.notes) #>> '{incidentConsoleV2,report,videoId}') AS video_id) linked
WHERE NOT EXISTS (SELECT 1 FROM src_incidents i WHERE i.model_run_id = mr.id)
  AND (linked.video_id IS NULL OR NOT EXISTS (SELECT 1 FROM src_videos v WHERE v.id = linked.video_id));

-- The orphans must be exactly the 20 runs listed by the never-applied midterm clean-up migration
-- (20261016010000), and the unlinked runs only mock-backend and agent test runs; anything else
-- means midterm changed since this copy was written, and a person looks before copying.
DO $$
DECLARE unexpected TEXT;
BEGIN
    SELECT string_agg(id, ', ') INTO unexpected FROM (
        (SELECT id FROM migration_excluded_runs WHERE reason LIKE 'orphan%'
         EXCEPT SELECT unnest(ARRAY['m8f79a33b8231fec914a', 'md2f6528f38497c186ff', 'ma3d606d678144b079ee', 'm6af95ffc5e9a3e0cb2b',
            'md5fb29b5eac05b6a66c', 'm64c1ac3b9016b0a5c25', 'm2d715078e3280006296', 'm7e25e066d916c23cc46', 'mbc0a845a383fee3ba5a',
            'm5b613baff9759dca358', 'm0929a3a7bd056d6f247', 'm6868a8b2e7d0aea7650', 'm907febd09dfb9185af0', 'm6d4b327cf8970d4132f',
            'mcee3ae89ac39f4180f1', 'm25d64aaddd5cb2a86aa', 'mda8e4766ad10350a2a3', 'm555a079c4f026fdbae8', 'mf437bbbff1823828b51',
            'm4b396db37e3b25e8ed4']))
        UNION ALL
        (SELECT id FROM migration_excluded_runs WHERE reason = 'unlinked test run' AND id NOT LIKE 'mock-run-%' AND id <> 'nmtest0925a')
    ) x;
    IF unexpected IS NOT NULL THEN RAISE EXCEPTION 'Unexpected runs would be left behind: %', unexpected; END IF;
END $$;

-- Broken uploads: no incident, no ground truth, no attempt record, and no playable file (4 R2 keys
-- with no object, 4 absolute VST paths from the v1 console; checked against R2 on 2026-10-20).
-- Three other never-analysed uploads (v8cae6a57d1b1f0b057d, v94a2ecb25c606c61987,
-- vf69c73cc44104f10e37) are playable from R2 and are copied.
CREATE TEMP TABLE migration_excluded_videos AS
SELECT v.id, CASE WHEN v.filepath LIKE '/%' THEN 'broken upload: VST disk path' ELSE 'broken upload: R2 object missing' END AS reason
FROM src_videos v
WHERE v.id IN ('v833746b6eaad1531436', 'v5c051db39d3839cc7e2', 'v64093d8cee6ebb0de74', 'v7a1533881beb1bafbad',
               'va5bd87fd75000a68cdd', 'vdd23812aeb2716fa9f0', 've92a4a7926a873dd5cf', 'vf07463971b065b8e4a9');

DO $$
DECLARE in_use TEXT;
BEGIN
    SELECT string_agg(v.id, ', ') INTO in_use FROM migration_excluded_videos v
    WHERE EXISTS (SELECT 1 FROM src_incidents i WHERE i.incident_id = v.id)
       OR EXISTS (SELECT 1 FROM src_gt_incidents g WHERE g.incident_id = v.id)
       OR EXISTS (SELECT 1 FROM src_model_runs mr WHERE mr.notes LIKE '%"videoId":"' || v.id || '"%');
    IF in_use IS NOT NULL THEN RAISE EXCEPTION 'Videos to leave behind are in use: %', in_use; END IF;
END $$;

-- 2. Base rows, as stored (labels folded) ------------------------------------------------------
INSERT INTO public.videos (id, filepath, uploaded_datetime, duration, source, selected_model_run_id, selected_by, selected_at)
SELECT id, filepath, uploaded_datetime, duration, source, NULL, selected_by, selected_at -- selection set in step 6
FROM src_videos WHERE id NOT IN (SELECT id FROM migration_excluded_videos);

INSERT INTO public.queries SELECT * FROM src_queries;

INSERT INTO public.model_runs SELECT * FROM src_model_runs WHERE id NOT IN (SELECT id FROM migration_excluded_runs);

INSERT INTO public.incidents (incident_id, model_run_id, type, start_timestamp, end_timestamp, duration, description, severity_level, confidence_score)
SELECT incident_id, model_run_id,
       CASE type WHEN 'fighting' THEN 'assault' WHEN 'animal' THEN 'animal attack' ELSE type END,
       start_timestamp, end_timestamp, duration, description, severity_level, confidence_score
FROM src_incidents;

INSERT INTO public.reports SELECT * FROM src_reports;

INSERT INTO public.entities (incident_id, entity_id, model_run_id, type, description, image)
SELECT incident_id, entity_id, model_run_id, CASE type WHEN 'person' THEN 'human' ELSE type END, description, image
FROM src_entities;

INSERT INTO public.instruments SELECT * FROM src_instruments;
INSERT INTO public.assets SELECT * FROM src_assets;
INSERT INTO public.review_status SELECT * FROM src_review_status;
INSERT INTO public.notifications SELECT * FROM src_notifications;
INSERT INTO public.severity_eval_log SELECT * FROM src_severity_eval_log;
INSERT INTO public.gt_incidents SELECT * FROM src_gt_incidents;
INSERT INTO public.gt_entities SELECT * FROM src_gt_entities;
INSERT INTO public.gt_instruments SELECT * FROM src_gt_instruments;
INSERT INTO public.gt_assets SELECT * FROM src_gt_assets;
INSERT INTO public.entity_matches SELECT * FROM src_entity_matches;
INSERT INTO public.instrument_matches SELECT * FROM src_instrument_matches;
INSERT INTO public.asset_matches SELECT * FROM src_asset_matches;

INSERT INTO public.evidence_crops (incident_id, model_run_id, item_type, item_id, item_name, description, threat_level,
    holder_entity_id, timestamp_seconds, bounding_box, image, embedding, created_at)
SELECT incident_id, model_run_id, item_type, item_id,
       CASE WHEN item_type = 'entity' AND item_name = 'person' THEN 'human' ELSE item_name END,
       description, threat_level, holder_entity_id, timestamp_seconds, bounding_box, image, embedding, created_at
FROM src_evidence_crops;

INSERT INTO public.query_results SELECT * FROM src_query_results;

-- 3. Which stored reports differ from what the AI wrote ----------------------------------------
-- Contract runs keep the AI's report in the immutable notes record; compare the stored rows with
-- it field by field (raw midterm values, before relabelling). confidence_score is not compared:
-- it was never editable, and rows written before 20260925031000 hold float4-rounded values.
CREATE TEMP TABLE migration_run_diffs AS
WITH contract_runs AS (
    SELECT i.incident_id, i.model_run_id, public.try_parse_jsonb(mr.notes) #> '{incidentConsoleV2,report}' AS report
    FROM src_incidents i JOIN src_model_runs mr ON mr.id = i.model_run_id
    WHERE public.run_outcome(mr.notes) IN ('valid_first_pass', 'valid_after_structural_repair')
      AND jsonb_typeof(public.try_parse_jsonb(mr.notes) #> '{incidentConsoleV2,report,incident}') = 'object'
),
incident_fields AS (
    SELECT c.incident_id, c.model_run_id, f.field
    FROM contract_runs c JOIN src_incidents i USING (incident_id, model_run_id)
    CROSS JOIN LATERAL (VALUES
        ('type', i.type IS DISTINCT FROM c.report #>> '{incident,type}'),
        ('start_timestamp', i.start_timestamp IS DISTINCT FROM c.report #>> '{incident,start_timestamp}'),
        ('end_timestamp', i.end_timestamp IS DISTINCT FROM c.report #>> '{incident,end_timestamp}'),
        ('duration', i.duration IS DISTINCT FROM (c.report #>> '{incident,duration}')::INTEGER),
        ('description', i.description IS DISTINCT FROM c.report #>> '{incident,description}'),
        ('severity_level', i.severity_level IS DISTINCT FROM (c.report #>> '{incident,severity_level}')::INTEGER)
    ) AS f(field, differs)
    WHERE f.differs
),
item_fields AS (
    SELECT c.incident_id, c.model_run_id, 'entities' AS field FROM contract_runs c
    WHERE (SELECT COALESCE(jsonb_agg(jsonb_build_array(e.entity_id, e.type, e.description) ORDER BY e.entity_id), '[]')
           FROM src_entities e WHERE e.incident_id = c.incident_id AND e.model_run_id = c.model_run_id)
       IS DISTINCT FROM
          (SELECT COALESCE(jsonb_agg(jsonb_build_array(x->>'entity_id', x->>'type', x->>'description') ORDER BY x->>'entity_id'), '[]')
           FROM jsonb_array_elements(COALESCE(c.report->'entities', '[]')) x)
    UNION ALL
    SELECT c.incident_id, c.model_run_id, 'instruments' FROM contract_runs c
    WHERE (SELECT COALESCE(jsonb_agg(jsonb_build_array(n.instrument_id, n.entity_id, n.name, n.description, n.threat_level::TEXT) ORDER BY n.instrument_id), '[]')
           FROM src_instruments n WHERE n.incident_id = c.incident_id AND n.model_run_id = c.model_run_id)
       IS DISTINCT FROM
          (SELECT COALESCE(jsonb_agg(jsonb_build_array(x->>'instrument_id', x->>'entity_id', x->>'name', x->>'description', x->>'threat_level') ORDER BY x->>'instrument_id'), '[]')
           FROM jsonb_array_elements(COALESCE(c.report->'instruments', '[]')) x)
    UNION ALL
    SELECT c.incident_id, c.model_run_id, 'assets' FROM contract_runs c
    WHERE (SELECT COALESCE(jsonb_agg(jsonb_build_array(a.asset_id, a.name, a.description) ORDER BY a.asset_id), '[]')
           FROM src_assets a WHERE a.incident_id = c.incident_id AND a.model_run_id = c.model_run_id)
       IS DISTINCT FROM
          (SELECT COALESCE(jsonb_agg(jsonb_build_array(x->>'asset_id', x->>'name', x->>'description') ORDER BY x->>'asset_id'), '[]')
           FROM jsonb_array_elements(COALESCE(c.report->'assets', '[]')) x)
)
SELECT incident_id, model_run_id, field, 'incident' AS level FROM incident_fields
UNION ALL
SELECT incident_id, model_run_id, field, 'item' FROM item_fields;

DO $$
DECLARE item_diffs TEXT;
BEGIN
    SELECT string_agg(DISTINCT model_run_id || ':' || field, ', ') INTO item_diffs FROM migration_run_diffs WHERE level = 'item';
    IF item_diffs IS NOT NULL THEN
        -- Editors renumber items by position, so the AI source of an edited item is a guess: a person decides.
        RAISE EXCEPTION 'Item-level reviewer edits found (%); map their source items by hand before copying', item_diffs;
    END IF;
END $$;

CREATE TEMP TABLE migration_edited_runs AS
SELECT DISTINCT d.incident_id, d.model_run_id, rs.edited_by, rs.edited_at
FROM migration_run_diffs d
LEFT JOIN src_review_status rs USING (incident_id, model_run_id);

-- 4. Review stamps: clear edited_by/at where provably not a content edit -----------------------
-- (a) contract runs whose rows equal the AI report: nothing was edited; the stamp came from a
--     status change (the console writes it on every review change) or a no-op save;
-- (b) other runs whose stamp is exactly the verification stamp (same name, same instant).
-- Edited runs keep their stamp: it is the only record of who changed the report.
CREATE TEMP TABLE migration_cleared_stamps AS
SELECT rs.incident_id, rs.model_run_id, rs.edited_by, rs.edited_at,
       CASE WHEN cr.model_run_id IS NOT NULL THEN 'rows equal the AI report' ELSE 'stamp equals verification' END AS reason
FROM public.review_status rs
JOIN public.model_runs mr ON mr.id = rs.model_run_id
LEFT JOIN LATERAL (SELECT rs.model_run_id WHERE public.run_outcome(mr.notes) IN ('valid_first_pass', 'valid_after_structural_repair')) cr ON TRUE
WHERE rs.edited_by IS NOT NULL
  AND NOT EXISTS (SELECT 1 FROM migration_edited_runs e WHERE e.incident_id = rs.incident_id AND e.model_run_id = rs.model_run_id)
  AND (cr.model_run_id IS NOT NULL OR (rs.edited_by = rs.verified_by AND rs.edited_at = rs.verified_at));

UPDATE public.review_status rs SET edited_by = NULL, edited_at = NULL
FROM migration_cleared_stamps c
WHERE c.incident_id = rs.incident_id AND c.model_run_id = rs.model_run_id;

-- 5. Reviewer versions -------------------------------------------------------------------------
-- 5a. Edited reports: the reviewer version is what is stored now (the edit); then the AI rows get
--     the AI's own values back from notes.
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN SELECT * FROM migration_edited_runs ORDER BY incident_id, model_run_id LOOP
        IF r.edited_by IS NULL THEN
            RAISE EXCEPTION 'Run % of % differs from its AI report but has no edit stamp', r.model_run_id, r.incident_id;
        END IF;
        PERFORM public.create_human_report_from_ai(r.incident_id, r.model_run_id, r.edited_by, r.edited_at);
        UPDATE public.human_reports SET edited_by = r.edited_by, edited_at = r.edited_at
        WHERE incident_id = r.incident_id AND model_run_id = r.model_run_id;
    END LOOP;
END $$;

UPDATE public.incidents i SET
    type = COALESCE(CASE WHEN EXISTS (SELECT 1 FROM migration_run_diffs d WHERE d.incident_id = i.incident_id AND d.model_run_id = i.model_run_id AND d.field = 'type')
        THEN n.report #>> '{incident,type}' END, i.type),
    start_timestamp = COALESCE(CASE WHEN EXISTS (SELECT 1 FROM migration_run_diffs d WHERE d.incident_id = i.incident_id AND d.model_run_id = i.model_run_id AND d.field = 'start_timestamp')
        THEN n.report #>> '{incident,start_timestamp}' END, i.start_timestamp),
    end_timestamp = COALESCE(CASE WHEN EXISTS (SELECT 1 FROM migration_run_diffs d WHERE d.incident_id = i.incident_id AND d.model_run_id = i.model_run_id AND d.field = 'end_timestamp')
        THEN n.report #>> '{incident,end_timestamp}' END, i.end_timestamp),
    duration = COALESCE(CASE WHEN EXISTS (SELECT 1 FROM migration_run_diffs d WHERE d.incident_id = i.incident_id AND d.model_run_id = i.model_run_id AND d.field = 'duration')
        THEN (n.report #>> '{incident,duration}')::INTEGER END, i.duration),
    description = COALESCE(CASE WHEN EXISTS (SELECT 1 FROM migration_run_diffs d WHERE d.incident_id = i.incident_id AND d.model_run_id = i.model_run_id AND d.field = 'description')
        THEN n.report #>> '{incident,description}' END, i.description),
    severity_level = COALESCE(CASE WHEN EXISTS (SELECT 1 FROM migration_run_diffs d WHERE d.incident_id = i.incident_id AND d.model_run_id = i.model_run_id AND d.field = 'severity_level')
        THEN (n.report #>> '{incident,severity_level}')::INTEGER END, i.severity_level)
FROM migration_edited_runs e
JOIN LATERAL (SELECT public.try_parse_jsonb(mr.notes) #> '{incidentConsoleV2,report}' AS report FROM public.model_runs mr WHERE mr.id = e.model_run_id) n ON TRUE
WHERE i.incident_id = e.incident_id AND i.model_run_id = e.model_run_id;

-- 5b. Verified reports without a reviewer version: a copy of the AI report, verified as it stands.
DO $$
DECLARE r RECORD;
BEGIN
    FOR r IN
        SELECT rs.incident_id, rs.model_run_id, rs.verified_by, rs.verified_at FROM public.review_status rs
        WHERE rs.status = 'verified'
          AND NOT EXISTS (SELECT 1 FROM public.human_reports h WHERE h.incident_id = rs.incident_id AND h.model_run_id = rs.model_run_id)
        ORDER BY rs.incident_id, rs.model_run_id
    LOOP
        PERFORM public.create_human_report_from_ai(r.incident_id, r.model_run_id, COALESCE(r.verified_by, 'unknown reviewer'),
            COALESCE(r.verified_at, now() AT TIME ZONE 'utc'));
    END LOOP;
END $$;

-- 6. Official selections, now that every incident exists ---------------------------------------
UPDATE public.videos v SET selected_model_run_id = s.selected_model_run_id
FROM src_videos s
WHERE s.id = v.id AND s.selected_model_run_id IS NOT NULL;

-- 7. Sequences continue after the copied ids ---------------------------------------------------
SELECT setval('public.notifications_id_seq', COALESCE((SELECT max(id) FROM public.notifications), 1),
              (SELECT max(id) FROM public.notifications) IS NOT NULL);
SELECT setval('public.severity_eval_log_id_seq', COALESCE((SELECT max(id) FROM public.severity_eval_log), 1),
              (SELECT max(id) FROM public.severity_eval_log) IS NOT NULL);
