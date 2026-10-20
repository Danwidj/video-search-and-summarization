-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Explicit official-report selection per video (decision D6).
--
-- A video can have many analyses; at most one of its successful analyses is
-- the official report, chosen by a reviewer. Nothing selects it implicitly:
-- analysis and re-analysis never write these columns ("latest run wins" is
-- never used), and selection is independent of review status (a run can be
-- verified without being official, and vice versa).
--
-- Additive only: three nullable columns (NULL = no official report yet) and
-- two service-role RPCs. No existing row is changed.
--
-- The composite foreign key (id, selected_model_run_id) -> incidents means the
-- official run must be an analysis of this same video. With MATCH SIMPLE it is
-- not checked while selected_model_run_id is NULL. If that incident is deleted
-- (report deleted, video re-analysed and cleaned, ...) only
-- selected_model_run_id is cleared, leaving the video "awaiting selection".

ALTER TABLE public.videos
    ADD COLUMN selected_model_run_id VARCHAR(20),
    ADD COLUMN selected_by VARCHAR(256),
    ADD COLUMN selected_at TIMESTAMP WITHOUT TIME ZONE;

ALTER TABLE public.videos
    ADD CONSTRAINT videos_selected_run_fkey
    FOREIGN KEY (id, selected_model_run_id)
    REFERENCES public.incidents (incident_id, model_run_id)
    ON DELETE SET NULL (selected_model_run_id);

CREATE INDEX videos_selected_run_idx ON public.videos (id, selected_model_run_id)
    WHERE selected_model_run_id IS NOT NULL;

-- Make one successful analysis (it must have an incident and a report) the
-- video's official report.
CREATE FUNCTION public.select_official_report(
    p_video_id TEXT,
    p_model_run_id TEXT,
    p_selected_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    v_selected_at TIMESTAMP WITHOUT TIME ZONE := now() AT TIME ZONE 'utc';
BEGIN
    IF p_selected_by IS NULL OR btrim(p_selected_by) = '' THEN
        RAISE EXCEPTION 'A reviewer name is required';
    END IF;
    PERFORM 1 FROM public.videos WHERE id = p_video_id FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Video not found'; END IF;
    PERFORM 1 FROM public.reports r
    JOIN public.incidents i ON i.incident_id = r.incident_id AND i.model_run_id = r.model_run_id
    WHERE r.incident_id = p_video_id AND r.model_run_id = p_model_run_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Only a successful analysis of this video that has a report can be the official report';
    END IF;

    UPDATE public.videos
    SET selected_model_run_id = p_model_run_id,
        selected_by = btrim(p_selected_by),
        selected_at = v_selected_at
    WHERE id = p_video_id;

    RETURN jsonb_build_object('videoId', p_video_id, 'officialRunId', p_model_run_id, 'selectedBy', btrim(p_selected_by), 'selectedAt', v_selected_at);
END;
$$;

-- Remove the official selection; the video goes back to "awaiting selection".
CREATE FUNCTION public.clear_official_report(
    p_video_id TEXT,
    p_cleared_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = ''
AS $$
BEGIN
    IF p_cleared_by IS NULL OR btrim(p_cleared_by) = '' THEN
        RAISE EXCEPTION 'A reviewer name is required';
    END IF;
    UPDATE public.videos
    SET selected_model_run_id = NULL, selected_by = NULL, selected_at = NULL
    WHERE id = p_video_id;
    IF NOT FOUND THEN RAISE EXCEPTION 'Video not found'; END IF;
    RETURN jsonb_build_object('videoId', p_video_id, 'officialRunId', NULL, 'clearedBy', btrim(p_cleared_by));
END;
$$;

REVOKE ALL ON FUNCTION public.select_official_report(TEXT, TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.select_official_report(TEXT, TEXT, TEXT) TO service_role;
REVOKE ALL ON FUNCTION public.clear_official_report(TEXT, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.clear_official_report(TEXT, TEXT) TO service_role;
