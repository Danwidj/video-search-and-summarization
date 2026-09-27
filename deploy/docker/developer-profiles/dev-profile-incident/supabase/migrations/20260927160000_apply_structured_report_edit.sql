-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0

-- Structured (Class A) reviewer edits for incident reports.
--
-- A reviewer edit replaces the relational projection of one model run:
-- incidents (type, start/end, derived duration, description, severity level)
-- and that run's entities / instruments / assets rows, and stamps
-- review_status.edited_by / edited_at. It never reads or writes
-- model_runs.notes: the original model output, raw response, repair record
-- and analysis outcome stay immutable. confidence_score is model-sourced and
-- is not editable. Everything happens in one transaction; any violation
-- raises and rolls the whole edit back.
--
-- The console validates the edit against the incident-contract-v2 sub-schemas
-- first (lib/contract/structured-edit.ts); the checks below repeat the rules
-- that keep the projection consistent so the database never stores an
-- invalid edit even if called directly.
--
-- Timestamps are stored as integer seconds in the existing VARCHAR columns,
-- as contract-v2 runs already are. Editing a legacy run therefore writes
-- v2-form values (seconds, contract types, E#/I#/A# IDs) for that run only.
--
-- apply_incident_report_patch (20260927140000) is left in place but is no
-- longer called by the console.

CREATE FUNCTION public.apply_structured_report_edit(
    p_incident_id TEXT,
    p_model_run_id TEXT,
    p_edit JSONB,
    p_edited_by TEXT
) RETURNS JSONB
LANGUAGE plpgsql VOLATILE SECURITY INVOKER SET search_path = ''
AS $$
DECLARE
    incident JSONB := p_edit->'incident';
    item JSONB;
    item_index INTEGER;
    start_seconds INTEGER;
    end_seconds INTEGER;
    entity_ids TEXT[] := ARRAY[]::TEXT[];
    edited_at TIMESTAMP WITHOUT TIME ZONE := now() AT TIME ZONE 'utc';
BEGIN
    IF p_edited_by IS NULL OR btrim(p_edited_by) = '' THEN
        RAISE EXCEPTION 'An editor name is required';
    END IF;
    IF jsonb_typeof(p_edit) IS DISTINCT FROM 'object' OR jsonb_typeof(incident) IS DISTINCT FROM 'object'
        OR jsonb_typeof(p_edit->'entities') IS DISTINCT FROM 'array' OR jsonb_typeof(p_edit->'instruments') IS DISTINCT FROM 'array'
        OR jsonb_typeof(p_edit->'assets') IS DISTINCT FROM 'array' THEN
        RAISE EXCEPTION 'The edit must contain incident, entities, instruments and assets';
    END IF;

    PERFORM 1 FROM public.incidents
    WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id
    FOR UPDATE;
    IF NOT FOUND THEN RAISE EXCEPTION 'Report not found for this video and model run'; END IF;

    -- Incident fields.
    IF incident->>'type' IS NULL OR NOT (incident->>'type' = ANY (ARRAY['road accident', 'burglary', 'explosion', 'assault', 'animal attack'])) THEN
        RAISE EXCEPTION 'Invalid incident type: %', incident->>'type';
    END IF;
    IF jsonb_typeof(incident->'start_timestamp') IS DISTINCT FROM 'number' OR jsonb_typeof(incident->'end_timestamp') IS DISTINCT FROM 'number'
        OR (incident->>'start_timestamp') !~ '^[0-9]{1,9}$' OR (incident->>'end_timestamp') !~ '^[0-9]{1,9}$' THEN
        RAISE EXCEPTION 'start_timestamp and end_timestamp must be non-negative integer seconds';
    END IF;
    start_seconds := (incident->>'start_timestamp')::INTEGER;
    end_seconds := (incident->>'end_timestamp')::INTEGER;
    IF end_seconds < start_seconds THEN
        RAISE EXCEPTION 'end_timestamp % is before start_timestamp %', end_seconds, start_seconds;
    END IF;
    IF jsonb_typeof(incident->'severity_level') IS DISTINCT FROM 'number' OR (incident->>'severity_level') !~ '^[1-5]$' THEN
        RAISE EXCEPTION 'severity_level must be an integer from 1 to 5';
    END IF;
    IF jsonb_typeof(incident->'description') IS DISTINCT FROM 'string' THEN
        RAISE EXCEPTION 'description must be text';
    END IF;

    UPDATE public.incidents
    SET type = incident->>'type',
        start_timestamp = start_seconds::TEXT,
        end_timestamp = end_seconds::TEXT,
        duration = end_seconds - start_seconds,
        description = incident->>'description',
        severity_level = (incident->>'severity_level')::INTEGER
    WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;

    -- Entities: sequential E1..En.
    DELETE FROM public.entities WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
    item_index := 0;
    FOR item IN SELECT value FROM jsonb_array_elements(p_edit->'entities') LOOP
        item_index := item_index + 1;
        IF item->>'entity_id' IS DISTINCT FROM 'E' || item_index THEN
            RAISE EXCEPTION 'entity_id % is not sequential (expected E%)', item->>'entity_id', item_index;
        END IF;
        IF item->>'type' IS NULL OR NOT (item->>'type' = ANY (ARRAY['human', 'animal', 'unknown'])) THEN
            RAISE EXCEPTION 'Invalid entity type: %', item->>'type';
        END IF;
        IF jsonb_typeof(item->'description') IS DISTINCT FROM 'string' THEN RAISE EXCEPTION 'entity description must be text'; END IF;
        INSERT INTO public.entities (incident_id, entity_id, model_run_id, type, description, image)
        VALUES (p_incident_id, item->>'entity_id', p_model_run_id, item->>'type', item->>'description', NULL);
        entity_ids := entity_ids || (item->>'entity_id');
    END LOOP;

    -- Instruments: sequential I1..In; holder is NULL or an edited entity.
    DELETE FROM public.instruments WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
    item_index := 0;
    FOR item IN SELECT value FROM jsonb_array_elements(p_edit->'instruments') LOOP
        item_index := item_index + 1;
        IF item->>'instrument_id' IS DISTINCT FROM 'I' || item_index THEN
            RAISE EXCEPTION 'instrument_id % is not sequential (expected I%)', item->>'instrument_id', item_index;
        END IF;
        IF jsonb_typeof(item->'entity_id') IS NULL OR jsonb_typeof(item->'entity_id') NOT IN ('null', 'string')
            OR (item->>'entity_id' IS NOT NULL AND NOT (item->>'entity_id' = ANY (entity_ids))) THEN
            RAISE EXCEPTION '% references unknown entity_id %', item->>'instrument_id', item->>'entity_id';
        END IF;
        IF jsonb_typeof(item->'threat_level') IS DISTINCT FROM 'number' OR (item->>'threat_level') !~ '^[1-5]$' THEN
            RAISE EXCEPTION 'threat_level of % must be an integer from 1 to 5', item->>'instrument_id';
        END IF;
        IF jsonb_typeof(item->'name') IS DISTINCT FROM 'string' OR jsonb_typeof(item->'description') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'instrument name and description must be text';
        END IF;
        INSERT INTO public.instruments (incident_id, instrument_id, model_run_id, entity_id, name, description, threat_level, image)
        VALUES (p_incident_id, item->>'instrument_id', p_model_run_id, item->>'entity_id', item->>'name', item->>'description',
            (item->>'threat_level')::INTEGER, NULL);
    END LOOP;

    -- Assets: sequential A1..An.
    DELETE FROM public.assets WHERE incident_id = p_incident_id AND model_run_id = p_model_run_id;
    item_index := 0;
    FOR item IN SELECT value FROM jsonb_array_elements(p_edit->'assets') LOOP
        item_index := item_index + 1;
        IF item->>'asset_id' IS DISTINCT FROM 'A' || item_index THEN
            RAISE EXCEPTION 'asset_id % is not sequential (expected A%)', item->>'asset_id', item_index;
        END IF;
        IF jsonb_typeof(item->'name') IS DISTINCT FROM 'string' OR jsonb_typeof(item->'description') IS DISTINCT FROM 'string' THEN
            RAISE EXCEPTION 'asset name and description must be text';
        END IF;
        INSERT INTO public.assets (incident_id, asset_id, model_run_id, name, description, image)
        VALUES (p_incident_id, item->>'asset_id', p_model_run_id, item->>'name', item->>'description', NULL);
    END LOOP;

    INSERT INTO public.review_status (incident_id, model_run_id, edited_by, edited_at)
    VALUES (p_incident_id, p_model_run_id, btrim(p_edited_by), edited_at)
    ON CONFLICT (incident_id, model_run_id)
    DO UPDATE SET edited_by = EXCLUDED.edited_by, edited_at = EXCLUDED.edited_at;

    RETURN jsonb_build_object(
        'incidentId', p_incident_id,
        'modelRunId', p_model_run_id,
        'editedBy', btrim(p_edited_by),
        'editedAt', edited_at,
        'duration', end_seconds - start_seconds
    );
END;
$$;

REVOKE ALL ON FUNCTION public.apply_structured_report_edit(TEXT, TEXT, JSONB, TEXT) FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION public.apply_structured_report_edit(TEXT, TEXT, JSONB, TEXT) TO service_role;
