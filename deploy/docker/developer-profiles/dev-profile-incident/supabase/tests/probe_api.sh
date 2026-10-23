#!/usr/bin/env bash
# SPDX-FileCopyrightText: Copyright (c) 2025-2026, NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
#
# Security probe of a Supabase project's REST API. Prints status codes only, never keys or rows.
#   FINALS_URL=https://<ref>.supabase.co FINALS_PUBLIC_KEY=<anon or sb_publishable_ key> \
#   FINALS_SERVICE_KEY=<service key> ./probe_api.sh
# Expect: every "public key" line 401 (or 403/404), every "service key" line 200.
set -u
: "${FINALS_URL:?}" "${FINALS_PUBLIC_KEY:?}" "${FINALS_SERVICE_KEY:?}"

headers() { # new sb_ keys go in apikey only; legacy JWT keys also as Bearer
  case "$1" in
    eyJ*) printf '%s\n' -H "apikey: $1" -H "Authorization: Bearer $1" ;;
    *) printf '%s\n' -H "apikey: $1" ;;
  esac
}
probe() { # label key method path [body]
  local label="$1" key="$2" method="$3" path="$4" body="${5:-}"
  mapfile -t h < <(headers "$key")
  local code
  code=$(curl -s -o /dev/null -w '%{http_code}' -X "$method" "${FINALS_URL%/}$path" "${h[@]}" \
    -H 'Content-Type: application/json' ${body:+--data "$body"})
  printf '%-14s %-6s %-62s %s\n' "$label" "$method" "$path" "$code"
}

for table in videos queries model_runs report_revisions evidence_crops query_results; do
  probe "public key" "$FINALS_PUBLIC_KEY" GET "/rest/v1/$table?select=*&limit=1"
done
probe "public key" "$FINALS_PUBLIC_KEY" POST "/rest/v1/videos" '{"id":"probe-anon"}'
probe "public key" "$FINALS_PUBLIC_KEY" POST "/rest/v1/rpc/save_human_revision" \
  '{"p_video_id":"x","p_parent_id":null,"p_created_by":"probe","p_note":null,"p_payload":{"incident":{"type":"assault"}},"p_evidence":[],"p_incident_type":"assault","p_severity_level":1,"p_start_seconds":0,"p_end_seconds":1}'
probe "public key" "$FINALS_PUBLIC_KEY" POST "/rest/v1/rpc/list_incident_report_summaries" '{}'
probe "public key" "$FINALS_PUBLIC_KEY" POST "/rest/v1/rpc/get_incident_dashboard" '{}'
probe "service key" "$FINALS_SERVICE_KEY" GET "/rest/v1/videos?select=id&limit=1"
probe "service key" "$FINALS_SERVICE_KEY" GET "/rest/v1/report_revisions?select=id&limit=1"
probe "service key" "$FINALS_SERVICE_KEY" POST "/rest/v1/rpc/get_incident_dashboard" '{}'
