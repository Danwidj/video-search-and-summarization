-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Create an AI revision for an incident with coverage (mvp3, P3.6).
--
-- create_ai_revision appends one 'ai' revision to an incident in a single transaction:
--   1. locks the incident row, so concurrent calls get distinct, consecutive revision numbers;
--   2. refuses an unknown incident, an empty or duplicated name list, and any video name that is
--      not currently a video of this incident (coverage is the named videos and nothing else);
--   3. numbers the revision max(revision_no) + 1 within the incident;
--   4. stores the envelope (p_payload), evidence, facets, embedding and coverage (video_names);
--   5. attaches the covered videos' latest crops: for each covered video, the rows of the newest
--      revision that holds crops for it are copied onto the new revision. Older rows stay, so the
--      older revisions keep their evidence.
--
-- start_seconds and end_seconds describe a single camera, so they are stored only when exactly one
-- video is covered (NULL otherwise). The function does not touch the official pointer.
--
-- Returns {revisionId, revisionNo, crops} where crops is the number of crop rows attached.

BEGIN;

CREATE OR REPLACE FUNCTION public.create_ai_revision(
    p_incident_id BIGINT,
    p_model_run_id TEXT,
    p_note TEXT,
    p_payload JSONB,
    p_evidence JSONB,
    p_video_names TEXT[],
    p_incident_type TEXT,
    p_severity_level INTEGER,
    p_start_seconds INTEGER DEFAULT NULL,
    p_end_seconds INTEGER DEFAULT NULL,
    p_embedding extensions.vector(1024) DEFAULT NULL
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_names TEXT[];
    v_missing TEXT[];
    v_no INTEGER;
    v_revision BIGINT;
    v_crops INTEGER;
BEGIN
    IF p_incident_id IS NULL OR p_model_run_id IS NULL OR p_payload IS NULL THEN
        RAISE EXCEPTION 'The incident, the model run and the payload are required' USING ERRCODE = 'P0001';
    END IF;

    PERFORM 1 FROM public.incidents AS i WHERE i.id = p_incident_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Incident % does not exist', p_incident_id USING ERRCODE = 'P0001';
    END IF;

    SELECT COALESCE(array_agg(DISTINCT n ORDER BY n), '{}'::TEXT[]) INTO v_names
    FROM unnest(COALESCE(p_video_names, '{}'::TEXT[])) AS n
    WHERE n IS NOT NULL;
    IF cardinality(v_names) = 0 THEN
        RAISE EXCEPTION 'A revision must cover at least one video' USING ERRCODE = 'P0001';
    END IF;

    SELECT array_agg(n ORDER BY n) INTO v_missing
    FROM unnest(v_names) AS n
    WHERE NOT EXISTS (
        SELECT 1 FROM public.videos AS v WHERE v.id = n AND v.incident_id = p_incident_id);
    IF v_missing IS NOT NULL THEN
        RAISE EXCEPTION 'Not videos of incident %: %', p_incident_id, array_to_string(v_missing, ', ')
            USING ERRCODE = 'P0001';
    END IF;

    SELECT COALESCE(max(r.revision_no), 0) + 1 INTO v_no
    FROM public.report_revisions AS r WHERE r.incident_id = p_incident_id;

    INSERT INTO public.report_revisions (
        incident_id, revision_no, kind, model_run_id, payload, evidence, video_names,
        incident_type, severity_level, start_seconds, end_seconds, note, embedding
    ) VALUES (
        p_incident_id, v_no, 'ai', p_model_run_id, p_payload, COALESCE(p_evidence, '[]'::JSONB), v_names,
        p_incident_type, p_severity_level,
        CASE WHEN cardinality(v_names) = 1 THEN p_start_seconds END,
        CASE WHEN cardinality(v_names) = 1 THEN p_end_seconds END,
        p_note, p_embedding
    ) RETURNING id INTO v_revision;

    INSERT INTO public.evidence_crops (
        revision_id, video_id, item_type, item_id, item_name, description, threat_level, holder_entity_id,
        timestamp_seconds, bounding_box, image, embedding
    )
    SELECT v_revision, c.video_id, c.item_type, c.item_id, c.item_name, c.description, c.threat_level,
           c.holder_entity_id, c.timestamp_seconds, c.bounding_box, c.image, c.embedding
    FROM public.evidence_crops AS c
    WHERE c.video_id = ANY (v_names)
      AND c.revision_id = (
          SELECT max(c2.revision_id) FROM public.evidence_crops AS c2 WHERE c2.video_id = c.video_id);
    GET DIAGNOSTICS v_crops = ROW_COUNT;

    RETURN jsonb_build_object('revisionId', v_revision, 'revisionNo', v_no, 'crops', v_crops);
END;
$$;

-- Security: service role only, exactly like the other write functions.
REVOKE ALL ON FUNCTION
    public.create_ai_revision(BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT[], TEXT, INTEGER, INTEGER, INTEGER, extensions.vector)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.create_ai_revision(BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT[], TEXT, INTEGER, INTEGER, INTEGER, extensions.vector)
TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
