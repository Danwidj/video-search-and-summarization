// SPDX-License-Identifier: Apache-2.0

// Human-readable labels for analysis outcomes and their machine-readable
// failure / violation codes. Browser-safe.

export type RunOutcome = 'valid_first_pass' | 'valid_after_structural_repair' | 'contract_failed' | 'request_failed' | 'legacy';

export const OUTCOME_LABELS: Record<RunOutcome, string> = {
  valid_first_pass: 'Valid',
  valid_after_structural_repair: 'Valid · IDs repaired',
  contract_failed: 'Contract failed',
  request_failed: 'Request failed',
  legacy: 'Earlier analysis',
};

export const OUTCOME_DESCRIPTIONS: Record<RunOutcome, string> = {
  valid_first_pass: 'The model’s response satisfied the incident contract on the first pass.',
  valid_after_structural_repair: 'Contract repair applied (IDs only): identifiers were normalized; no text or value was changed.',
  contract_failed: 'The model answered, but the answer broke the incident contract. No report was created.',
  request_failed: 'The model request did not produce a usable answer. No report was created.',
  legacy: 'Analysed before outcomes were recorded (earlier prompt, eval or seed data). Outcome not recorded.',
};

const CODE_LABELS: Record<string, string> = {
  GATEWAY_UNREACHABLE: 'Could not reach the model gateway',
  GATEWAY_TIMEOUT: 'The model did not answer within its time limit',
  GATEWAY_HTTP_ERROR: 'The model service returned an error',
  UPSTREAM_NON_JSON: 'The model service returned an unreadable response',
  UPSTREAM_NO_COMPLETION: 'The model service returned no answer',
  UPSTREAM_EMPTY_CONTENT: 'The model returned an empty answer',
  FINISH_LENGTH: 'The model ran out of its token budget before finishing',
  FINISH_CONTENT_FILTER: 'The model service filtered the answer',
  EMPTY_CONTENT: 'The answer was empty',
  INVALID_JSON: 'The answer was not a single JSON document',
  SCHEMA_VIOLATION: 'The answer did not match the report schema',
  WINDOW_END_BEFORE_START: 'The incident ends before it starts',
  ID_NOT_SEQUENTIAL_ENTITY: 'Entity IDs are out of sequence',
  ID_NOT_SEQUENTIAL_INSTRUMENT: 'Instrument IDs are out of sequence',
  ID_NOT_SEQUENTIAL_ASSET: 'Asset IDs are out of sequence',
  INSTRUMENT_HOLDER_UNKNOWN: 'An instrument is held by an entity that does not exist',
  TIMELINE_START_OUTSIDE_WINDOW: 'A timeline event starts outside the incident window',
  TIMELINE_END_OUTSIDE_WINDOW: 'A timeline event ends outside the incident window',
  TIMELINE_NOT_CHRONOLOGICAL: 'Timeline events are not in chronological order',
};

export function describeCode(code: string): string {
  if (CODE_LABELS[code]) return CODE_LABELS[code];
  if (code.startsWith('FINISH_')) return `The model stopped early (${code.slice('FINISH_'.length).toLowerCase()})`;
  return code;
}
