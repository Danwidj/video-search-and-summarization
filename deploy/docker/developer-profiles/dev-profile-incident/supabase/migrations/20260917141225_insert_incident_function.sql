-- SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
-- SPDX-License-Identifier: Apache-2.0
--
-- Licensed under the Apache License, Version 2.0 (the "License");
-- you may not use this file except in compliance with the License.
-- You may obtain a copy of the License at
--
-- http://www.apache.org/licenses/LICENSE-2.0
--
-- Unless required by applicable law or agreed to in writing, software
-- distributed under the License is distributed on an "AS IS" BASIS,
-- WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
-- See the License for the specific language governing permissions and
-- limitations under the License.

-- Migration: Create insert_incident RPC function
-- This function replicates the exact delete-then-insert logic from
-- services/agent/src/vss_agents/utils/incident_db.py:insert_incident
-- as a single atomic server-side transaction, callable via PostgREST's
-- /rpc/insert_incident endpoint.

CREATE OR REPLACE FUNCTION insert_incident(
    p_incident_id TEXT,
    p_model_run_id TEXT,
    p_type TEXT,
    p_start_timestamp TEXT,
    p_end_timestamp TEXT,
    p_duration INTEGER,
    p_description TEXT,
    p_severity_level INTEGER,
    p_confidence_score REAL
) RETURNS VOID
LANGUAGE plpgsql
AS $$
BEGIN
    -- Delete existing incident row for this (incident_id, model_run_id)
    DELETE FROM incidents
    WHERE incident_id = p_incident_id
      AND model_run_id = p_model_run_id;

    -- Insert new incident row
    INSERT INTO incidents (
        incident_id,
        model_run_id,
        type,
        start_timestamp,
        end_timestamp,
        duration,
        description,
        severity_level,
        confidence_score
    ) VALUES (
        p_incident_id,
        p_model_run_id,
        p_type,
        p_start_timestamp,
        p_end_timestamp,
        p_duration,
        p_description,
        p_severity_level,
        p_confidence_score
    );

    -- Delete existing review_status row for this (incident_id, model_run_id)
    DELETE FROM review_status
    WHERE incident_id = p_incident_id
      AND model_run_id = p_model_run_id;

    -- Insert new review_status row, resetting to 'unreviewed'
    INSERT INTO review_status (
        incident_id,
        model_run_id,
        status
    ) VALUES (
        p_incident_id,
        p_model_run_id,
        'unreviewed'
    );
END;
$$;

-- Grant execute permission to the roles that PostgREST uses
GRANT EXECUTE ON FUNCTION insert_incident(TEXT, TEXT, TEXT, TEXT, TEXT, INTEGER, TEXT, INTEGER, REAL) TO anon, authenticated, service_role;