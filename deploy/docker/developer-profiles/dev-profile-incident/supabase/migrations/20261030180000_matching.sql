-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Matching data functions (mvp3, P3.7).
--
-- Applied after 20261030110000_analyses_suggestions_crops.sql (video_analyses and
-- incident_match_suggestions) on an empty database. Defines only the functions this step owns:
--   shortlist_similar_incidents(video, limit, min_similarity)
--       candidate incidents for the match judge, most similar first. Never the video's own incident,
--       never a pair already decided (accepted or rejected).
--   record_match_suggestion(a, b, score, reasons)
--       store a pending suggestion for a pair of incidents unless the pair already has a row.
--   reject_match_suggestion(suggestion)
--       mark a suggestion rejected; the row stays so the pair is never suggested again.
--
-- Similarity is cosine similarity between the video's latest analysis embedding and the latest
-- analysis embedding of each video in another incident; an incident scores its best video. A video
-- with no analysis or no embedding has an empty shortlist.

BEGIN;

-- 1. shortlist_similar_incidents -----------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.shortlist_similar_incidents(
    p_video_id TEXT,
    p_limit INTEGER DEFAULT 5,
    p_min_similarity DOUBLE PRECISION DEFAULT 0.0
) RETURNS TABLE (
    incident_id BIGINT,
    similarity DOUBLE PRECISION,
    best_video_id TEXT
)
LANGUAGE sql STABLE SECURITY INVOKER SET search_path = ''
AS $$
    WITH own AS (
        SELECT v.incident_id, a.embedding
        FROM public.videos AS v
        JOIN LATERAL (
            SELECT va.embedding FROM public.video_analyses AS va
            WHERE va.video_id = v.id
            ORDER BY va.created_at DESC, va.id DESC LIMIT 1
        ) AS a ON TRUE
        WHERE v.id = p_video_id AND a.embedding IS NOT NULL
    ),
    scored AS (
        SELECT v.incident_id, v.id AS video_id,
               (1.0 - (a.embedding OPERATOR(extensions.<=>) own.embedding))::DOUBLE PRECISION AS similarity
        FROM own
        JOIN public.videos AS v ON v.incident_id <> own.incident_id
        JOIN LATERAL (
            SELECT va.embedding FROM public.video_analyses AS va
            WHERE va.video_id = v.id
            ORDER BY va.created_at DESC, va.id DESC LIMIT 1
        ) AS a ON a.embedding IS NOT NULL
        WHERE NOT EXISTS (
            SELECT 1 FROM public.incident_match_suggestions AS s
            WHERE s.status IN ('accepted', 'rejected')
              AND LEAST(s.incident_a_id, s.incident_b_id) = LEAST(own.incident_id, v.incident_id)
              AND GREATEST(s.incident_a_id, s.incident_b_id) = GREATEST(own.incident_id, v.incident_id))
    ),
    best AS (
        SELECT DISTINCT ON (sc.incident_id) sc.incident_id, sc.similarity, sc.video_id
        FROM scored AS sc
        ORDER BY sc.incident_id, sc.similarity DESC, sc.video_id
    )
    SELECT b.incident_id, b.similarity, b.video_id
    FROM best AS b
    WHERE b.similarity >= p_min_similarity
    ORDER BY b.similarity DESC, b.incident_id
    LIMIT GREATEST(COALESCE(p_limit, 5), 0);
$$;

-- 2. record_match_suggestion ---------------------------------------------------------------------
-- One row per unordered pair: an existing row of any status is kept as it is (a rejected pair stays
-- rejected). Returns {suggestionId, status, created}; created is false when the pair already had a row.
CREATE OR REPLACE FUNCTION public.record_match_suggestion(
    p_incident_a_id BIGINT,
    p_incident_b_id BIGINT,
    p_score DOUBLE PRECISION,
    p_reasons JSONB DEFAULT '[]'::JSONB
) RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_id BIGINT;
    v_status TEXT;
BEGIN
    IF p_incident_a_id IS NULL OR p_incident_b_id IS NULL THEN
        RAISE EXCEPTION 'both incident ids are required' USING ERRCODE = '22023';
    END IF;
    IF p_incident_a_id = p_incident_b_id THEN
        RAISE EXCEPTION 'an incident cannot be suggested against itself' USING ERRCODE = '22023';
    END IF;
    IF p_score IS NULL OR p_score < 0 OR p_score > 1 THEN
        RAISE EXCEPTION 'score must be between 0 and 1' USING ERRCODE = '22023';
    END IF;

    INSERT INTO public.incident_match_suggestions (incident_a_id, incident_b_id, score, reasons)
    VALUES (p_incident_a_id, p_incident_b_id, p_score, COALESCE(p_reasons, '[]'::JSONB))
    ON CONFLICT (LEAST(incident_a_id, incident_b_id), GREATEST(incident_a_id, incident_b_id)) DO NOTHING
    RETURNING id, status INTO v_id, v_status;

    IF v_id IS NOT NULL THEN
        RETURN jsonb_build_object('suggestionId', v_id, 'status', v_status, 'created', TRUE);
    END IF;

    SELECT s.id, s.status INTO v_id, v_status
    FROM public.incident_match_suggestions AS s
    WHERE LEAST(s.incident_a_id, s.incident_b_id) = LEAST(p_incident_a_id, p_incident_b_id)
      AND GREATEST(s.incident_a_id, s.incident_b_id) = GREATEST(p_incident_a_id, p_incident_b_id);
    RETURN jsonb_build_object('suggestionId', v_id, 'status', v_status, 'created', FALSE);
END;
$$;

-- 3. reject_match_suggestion ---------------------------------------------------------------------
-- Pending becomes rejected with decided_at set; the row is kept so the pair is never suggested again.
-- Rejecting a rejected suggestion changes nothing. An accepted suggestion cannot be rejected.
-- Returns {suggestionId, status}.
CREATE OR REPLACE FUNCTION public.reject_match_suggestion(p_suggestion_id BIGINT)
RETURNS JSONB
LANGUAGE plpgsql SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_status TEXT;
BEGIN
    SELECT s.status INTO v_status
    FROM public.incident_match_suggestions AS s
    WHERE s.id = p_suggestion_id
    FOR UPDATE;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'match suggestion % does not exist', p_suggestion_id USING ERRCODE = 'P0002';
    END IF;
    IF v_status = 'accepted' THEN
        RAISE EXCEPTION 'match suggestion % is already accepted', p_suggestion_id USING ERRCODE = '22023';
    END IF;
    IF v_status = 'pending' THEN
        UPDATE public.incident_match_suggestions
        SET status = 'rejected', decided_at = (now() AT TIME ZONE 'utc')
        WHERE id = p_suggestion_id;
    END IF;
    RETURN jsonb_build_object('suggestionId', p_suggestion_id, 'status', 'rejected');
END;
$$;

-- 4. Security: service role only, like the other functions ---------------------------------------
REVOKE ALL ON FUNCTION
    public.shortlist_similar_incidents(TEXT, INTEGER, DOUBLE PRECISION),
    public.record_match_suggestion(BIGINT, BIGINT, DOUBLE PRECISION, JSONB),
    public.reject_match_suggestion(BIGINT)
FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION
    public.shortlist_similar_incidents(TEXT, INTEGER, DOUBLE PRECISION),
    public.record_match_suggestion(BIGINT, BIGINT, DOUBLE PRECISION, JSONB),
    public.reject_match_suggestion(BIGINT)
TO service_role;

NOTIFY pgrst, 'reload schema';

COMMIT;
