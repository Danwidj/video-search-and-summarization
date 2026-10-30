-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Write paths for mvp3 (P3.4): human revisions and the official revision, per incident.
--
--   save_human_revision(p_incident_id, p_parent_id, ...)
--       Appends a kind='human' revision. The parent must belong to the same incident. The new
--       revision copies the parent's coverage (video_names) and model run; the payload must be an
--       envelope ({overview, cameras}). revision_no is max+1 for the incident, assigned while the
--       incident row is locked.
--   save_human_revision_with_crops(..., p_crops)
--       The same, and stores the given crops on the new revision in the same call. Each crop names
--       its source video (video_id), which must be a current video of the incident that the
--       revision covers. Crop rows are stored for the new revision only; the searchable-revision
--       rules and crop replacement belong to the crop functions (P3.3).
--   set_official_revision(p_incident_id, p_revision_id)
--       Sets the incident's official revision, or clears it with NULL. Only the incident's own
--       revisions are accepted. official_since moves with the pointer; marking the same revision
--       again keeps the original time.
--
-- Every function is SECURITY INVOKER with an empty search_path and executable by service_role only.
-- Applied after 20261030100000_revisions_per_incident.sql, which dropped the video-based versions.

BEGIN;

-- 1. save_human_revision -------------------------------------------------------------------------
-- Returns {revisionId, revisionNo, incidentId, kind, parentId, modelRunId, videoNames, createdBy,
-- createdAt, note}.
CREATE FUNCTION public.save_human_revision(
    p_incident_id BIGINT,
    p_parent_id BIGINT,
    p_created_by TEXT,
    p_note TEXT,
    p_payload JSONB,
    p_evidence JSONB,
    p_incident_type TEXT,
    p_severity_level INTEGER,
    p_start_seconds INTEGER,
    p_end_seconds INTEGER
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_parent public.report_revisions;
    v_by TEXT := btrim(COALESCE(p_created_by, ''));
    v_row public.report_revisions;
BEGIN
    PERFORM 1 FROM public.incidents WHERE id = p_incident_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Incident not found: %', p_incident_id USING ERRCODE = 'P0001';
    END IF;
    IF p_parent_id IS NULL THEN
        RAISE EXCEPTION 'A parent revision is required' USING ERRCODE = 'P0001';
    END IF;
    SELECT * INTO v_parent
    FROM public.report_revisions
    WHERE id = p_parent_id AND incident_id = p_incident_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Revision not found for this incident: %', p_parent_id USING ERRCODE = 'P0001';
    END IF;
    IF v_by = '' OR length(v_by) > 256 THEN
        RAISE EXCEPTION 'A reviewer name of 1 to 256 characters is required' USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(p_payload) IS DISTINCT FROM 'object'
        OR jsonb_typeof(p_payload -> 'overview') IS DISTINCT FROM 'object'
        OR jsonb_typeof(p_payload -> 'cameras') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The report payload must be an object with an overview and a list of cameras'
            USING ERRCODE = 'P0001';
    END IF;
    IF jsonb_typeof(p_evidence) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The evidence must be a list' USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO public.report_revisions (
        incident_id, revision_no, kind, model_run_id, parent_id, payload, evidence, video_names,
        incident_type, severity_level, start_seconds, end_seconds, created_by, note
    )
    SELECT
        p_incident_id,
        COALESCE(MAX(r.revision_no), 0) + 1,
        'human',
        v_parent.model_run_id,
        v_parent.id,
        p_payload,
        p_evidence,
        v_parent.video_names,
        p_incident_type,
        p_severity_level,
        p_start_seconds,
        p_end_seconds,
        v_by,
        NULLIF(btrim(COALESCE(p_note, '')), '')
    FROM public.report_revisions AS r
    WHERE r.incident_id = p_incident_id
    RETURNING * INTO v_row;

    RETURN jsonb_build_object(
        'revisionId', v_row.id,
        'revisionNo', v_row.revision_no,
        'incidentId', v_row.incident_id,
        'kind', v_row.kind,
        'parentId', v_row.parent_id,
        'modelRunId', v_row.model_run_id,
        'videoNames', to_jsonb(v_row.video_names),
        'createdBy', v_row.created_by,
        'createdAt', v_row.created_at,
        'note', v_row.note
    );
END;
$$;

-- 2. save_human_revision_with_crops --------------------------------------------------------------
-- p_crops is the exact row list to store on the new revision:
--   [{video_id, item_type, item_id, image, bounding_box, timestamp_seconds, item_name, description,
--     threat_level, holder_entity_id, embedding}, ...]
-- Entries without an image are skipped; a missing bounding box becomes the whole frame; a missing
-- timestamp becomes 0; an embedding, when present, is a 1024-number JSON array. An entry whose
-- video_id is not a current video of the incident covered by the revision refuses the whole save.
--
-- Returns the save_human_revision result plus {crops}, the number of crop rows stored.
CREATE FUNCTION public.save_human_revision_with_crops(
    p_incident_id BIGINT,
    p_parent_id BIGINT,
    p_created_by TEXT,
    p_note TEXT,
    p_payload JSONB,
    p_evidence JSONB,
    p_incident_type TEXT,
    p_severity_level INTEGER,
    p_start_seconds INTEGER,
    p_end_seconds INTEGER,
    p_crops JSONB DEFAULT '[]'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_saved JSONB;
    v_revision BIGINT;
    v_names TEXT[];
    v_bad TEXT;
    v_crops INTEGER := 0;
BEGIN
    IF jsonb_typeof(COALESCE(p_crops, '[]'::JSONB)) IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The crops must be a list' USING ERRCODE = 'P0001';
    END IF;

    v_saved := public.save_human_revision(
        p_incident_id, p_parent_id, p_created_by, p_note, p_payload, p_evidence,
        p_incident_type, p_severity_level, p_start_seconds, p_end_seconds);
    v_revision := (v_saved ->> 'revisionId')::BIGINT;
    SELECT r.video_names INTO v_names FROM public.report_revisions AS r WHERE r.id = v_revision;

    SELECT e ->> 'video_id' INTO v_bad
    FROM jsonb_array_elements(COALESCE(p_crops, '[]'::JSONB)) AS e
    WHERE jsonb_typeof(e) = 'object'
      AND COALESCE(btrim(e ->> 'image'), '') <> ''
      AND (e ->> 'video_id' IS NULL
           OR NOT (e ->> 'video_id' = ANY (v_names))
           OR NOT EXISTS (SELECT 1 FROM public.videos AS v
                          WHERE v.id = e ->> 'video_id' AND v.incident_id = p_incident_id))
    LIMIT 1;
    IF FOUND THEN
        RAISE EXCEPTION 'Crop video is not a covered video of this incident: %', COALESCE(v_bad, '(none)')
            USING ERRCODE = 'P0001';
    END IF;

    INSERT INTO public.evidence_crops (
        revision_id, video_id, item_type, item_id, item_name, description, threat_level, holder_entity_id,
        timestamp_seconds, bounding_box, image, embedding
    )
    SELECT DISTINCT ON (e ->> 'video_id', e ->> 'item_type', e ->> 'item_id')
        v_revision,
        e ->> 'video_id',
        e ->> 'item_type',
        e ->> 'item_id',
        left(COALESCE(NULLIF(btrim(COALESCE(e ->> 'item_name', '')), ''), e ->> 'item_type', 'item'), 256),
        COALESCE(e ->> 'description', ''),
        CASE WHEN jsonb_typeof(e -> 'threat_level') = 'number'
            THEN (e ->> 'threat_level')::NUMERIC::INTEGER END,
        NULLIF(btrim(COALESCE(e ->> 'holder_entity_id', '')), ''),
        COALESCE(
            CASE WHEN jsonb_typeof(e -> 'timestamp_seconds') = 'number'
                THEN (e ->> 'timestamp_seconds')::NUMERIC::INTEGER END,
            0),
        CASE WHEN jsonb_typeof(e -> 'bounding_box') = 'array'
                AND jsonb_array_length(e -> 'bounding_box') = 4
            THEN ARRAY(SELECT box.value::INTEGER FROM jsonb_array_elements_text(e -> 'bounding_box') AS box(value))
            ELSE ARRAY[0, 0, 1000, 1000] END,
        e ->> 'image',
        CASE WHEN jsonb_typeof(e -> 'embedding') = 'array'
            THEN (e -> 'embedding')::TEXT::extensions.vector(1024) END
    FROM jsonb_array_elements(COALESCE(p_crops, '[]'::JSONB)) AS e
    WHERE jsonb_typeof(e) = 'object'
      AND e ->> 'item_type' IN ('entity', 'instrument', 'asset')
      AND COALESCE(btrim(e ->> 'item_id'), '') <> ''
      AND COALESCE(btrim(e ->> 'image'), '') <> ''
    ORDER BY e ->> 'video_id', e ->> 'item_type', e ->> 'item_id';
    GET DIAGNOSTICS v_crops = ROW_COUNT;

    RETURN v_saved || jsonb_build_object('crops', v_crops);
END;
$$;

-- 3. set_official_revision -----------------------------------------------------------------------
-- Returns {incidentId, officialRevisionId, officialSince}.
CREATE FUNCTION public.set_official_revision(
    p_incident_id BIGINT,
    p_revision_id BIGINT
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_row public.incidents;
BEGIN
    PERFORM 1 FROM public.incidents WHERE id = p_incident_id FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Incident not found: %', p_incident_id USING ERRCODE = 'P0001';
    END IF;
    IF p_revision_id IS NOT NULL AND NOT EXISTS (
        SELECT 1 FROM public.report_revisions
        WHERE id = p_revision_id AND incident_id = p_incident_id
    ) THEN
        RAISE EXCEPTION 'Revision not found for this incident: %', p_revision_id USING ERRCODE = 'P0001';
    END IF;

    UPDATE public.incidents
    SET official_revision_id = p_revision_id,
        official_since = CASE
            WHEN p_revision_id IS NULL THEN NULL
            WHEN official_revision_id IS NOT DISTINCT FROM p_revision_id AND official_since IS NOT NULL THEN official_since
            ELSE now() AT TIME ZONE 'utc' END
    WHERE id = p_incident_id
    RETURNING * INTO v_row;

    RETURN jsonb_build_object(
        'incidentId', v_row.id,
        'officialRevisionId', v_row.official_revision_id,
        'officialSince', v_row.official_since
    );
END;
$$;

-- Security: service role only, exactly like the other write functions.
REVOKE ALL ON FUNCTION
    public.save_human_revision(BIGINT, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER),
    public.save_human_revision_with_crops(BIGINT, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, JSONB),
    public.set_official_revision(BIGINT, BIGINT)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.save_human_revision(BIGINT, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER),
    public.save_human_revision_with_crops(BIGINT, BIGINT, TEXT, TEXT, JSONB, JSONB, TEXT, INTEGER, INTEGER, INTEGER, JSONB),
    public.set_official_revision(BIGINT, BIGINT)
TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
