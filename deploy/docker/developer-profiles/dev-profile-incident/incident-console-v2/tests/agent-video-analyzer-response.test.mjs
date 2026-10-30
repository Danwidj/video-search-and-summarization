// SPDX-License-Identifier: Apache-2.0

// Regression: the console reads the contract report from the field the agent really returns
// (`report`, from incident_report_gen's IncidentReportGenOutput), not from `payload`.

import assert from 'node:assert/strict';
import { register } from 'node:module';
import { describe, test } from 'node:test';

register('./support/alias-loader.mjs', import.meta.url);

const { parseAnalysisResponse } = await import('../src/modules/analysis/infrastructure/agent/video-analyzer.ts');

const REPORT = { incident: { type: 'assault', title: 'Altercation at the front door', duration: '00:00:05' }, entities: [] };

// Shaped exactly like IncidentReportGenOutput.model_dump() from POST /api/v1/incidents/{video_name}/analyze.
const AGENT_BODY = {
  report: REPORT,
  report_text: null,
  report_text_error: null,
  model: 'nvidia/cosmos-3-super-reasoner',
  contract_version: 'incident-contract-v4',
  raw_output: '{"incident":{}}',
  finish_reason: 'stop',
  analysis_id: 35,
  model_run_id: 'clip.mp4@2026-10-30T06:26:50.050Z',
  outcome: 'stored',
  evidence: [],
  video_duration_seconds: 5,
  video_duration_source: 'request',
};

describe('parseAnalysisResponse against the agent response shape', () => {
  test('stores the report as the per-video payload', () => {
    const result = parseAnalysisResponse(200, true, 'OK', JSON.stringify(AGENT_BODY));
    assert.deepEqual(result, {
      kind: 'analysed',
      analysisId: 35,
      modelRunId: 'clip.mp4@2026-10-30T06:26:50.050Z',
      outcome: 'stored',
      payload: REPORT,
    });
  });

  test('a body with no report object is a 502', () => {
    const { report: _report, ...withoutReport } = AGENT_BODY;
    const result = parseAnalysisResponse(200, true, 'OK', JSON.stringify({ ...withoutReport, payload: REPORT }));
    assert.deepEqual(result, { kind: 'failed', status: 502, message: 'The agent analysis has no report object' });
  });
});
