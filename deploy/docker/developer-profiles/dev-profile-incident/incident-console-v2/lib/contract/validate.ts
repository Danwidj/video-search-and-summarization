// SPDX-License-Identifier: Apache-2.0

// Strict validator for incident-contract-v2, equivalent to eval/contract.py:
// JSON.parse of the raw content (no fence stripping, brace extraction, alias
// mapping or default filling), JSON Schema validation against the shared
// schema file, then the cross-field rules the schema cannot express. Derived
// fields (incident.duration) are computed here, never requested from the model.
// tests/contract-validate.test.mjs runs the shared contracts/fixtures/ through
// this module; eval/tests/test_contract_fixtures.py runs them through Python.

import Ajv2020 from 'ajv/dist/2020.js';
import type { ErrorObject, ValidateFunction } from 'ajv';

import { schema } from '@/lib/contract/load';
import type { DerivedContractReport, IncidentContractReport } from '@/lib/contract/types';

/**
 * Machine-readable violation codes. The messages match eval/contract.py's text;
 * the codes exist so the application can decide repair eligibility
 * (lib/contract/repair.ts) and analyse failures without parsing messages.
 */
export type ContractViolationCode =
  | 'EMPTY_CONTENT'
  | 'INVALID_JSON'
  | 'SCHEMA_VIOLATION'
  | 'WINDOW_END_BEFORE_START'
  | 'ID_NOT_SEQUENTIAL_ENTITY'
  | 'ID_NOT_SEQUENTIAL_INSTRUMENT'
  | 'ID_NOT_SEQUENTIAL_ASSET'
  | 'INSTRUMENT_HOLDER_UNKNOWN'
  | 'TIMELINE_START_OUTSIDE_WINDOW'
  | 'TIMELINE_END_OUTSIDE_WINDOW'
  | 'TIMELINE_NOT_CHRONOLOGICAL';

export interface ContractViolation {
  code: ContractViolationCode;
  path: string;
  message: string;
}

export class ContractError extends Error {
  violations: ContractViolation[];

  constructor(message: string, violations: ContractViolation[]) {
    super(message);
    this.name = 'ContractError';
    this.violations = violations;
  }
}

let compiled: ValidateFunction | null = null;

function validator(): ValidateFunction {
  if (!compiled) {
    // strict:false only relaxes Ajv's authoring lint (e.g. minimum on a
    // ["number","null"] union); validation semantics are standard draft 2020-12.
    const ajv = new Ajv2020({ allErrors: true, strict: false });
    compiled = ajv.compile(schema());
  }
  return compiled;
}

function schemaViolation(error: ErrorObject): ContractViolation {
  const location = error.instancePath ? error.instancePath.slice(1) : '<root>';
  const extra = error.keyword === 'additionalProperties'
    ? ` (${String((error.params as { additionalProperty?: string }).additionalProperty)})`
    : error.keyword === 'enum'
      ? ` (${JSON.stringify((error.params as { allowedValues?: unknown }).allowedValues)})`
      : '';
  return { code: 'SCHEMA_VIOLATION', path: location, message: `${location}: ${error.message ?? error.keyword}${extra}` };
}

/** Rules JSON Schema cannot express. Assumes the report already passed the schema (port of eval cross_field_errors). */
export function crossFieldViolations(report: IncidentContractReport): ContractViolation[] {
  const violations: ContractViolation[] = [];
  const add = (code: ContractViolationCode, path: string, message: string) => violations.push({ code, path, message });
  const { start_timestamp: start, end_timestamp: end } = report.incident;
  if (end < start) add('WINDOW_END_BEFORE_START', 'incident/end_timestamp', `end_timestamp ${end} is before start_timestamp ${start}`);

  const sequences: Array<[ContractViolationCode, string, string, string[]]> = [
    ['ID_NOT_SEQUENTIAL_ENTITY', 'entities', 'E', report.entities.map((item) => item.entity_id)],
    ['ID_NOT_SEQUENTIAL_INSTRUMENT', 'instruments', 'I', report.instruments.map((item) => item.instrument_id)],
    ['ID_NOT_SEQUENTIAL_ASSET', 'assets', 'A', report.assets.map((item) => item.asset_id)],
  ];
  const keys: Record<string, string> = { entities: 'entity_id', instruments: 'instrument_id', assets: 'asset_id' };
  for (const [code, collection, prefix, actual] of sequences) {
    const expected = actual.map((_, index) => `${prefix}${index + 1}`);
    if (actual.some((value, index) => value !== expected[index])) {
      add(code, collection, `${keys[collection]} values ${JSON.stringify(actual)} are not sequential ${JSON.stringify(expected)}`);
    }
  }

  const entityIds = new Set(report.entities.map((item) => item.entity_id));
  report.instruments.forEach((instrument, index) => {
    if (instrument.entity_id !== null && !entityIds.has(instrument.entity_id)) {
      add('INSTRUMENT_HOLDER_UNKNOWN', `instruments/${index}/entity_id`, `${instrument.instrument_id} references unknown entity_id ${instrument.entity_id}`);
    }
  });

  let previousStart: number | null = null;
  report.timeline.forEach((event, index) => {
    const { start_seconds: eventStart, end_seconds: eventEnd } = event;
    if (eventStart < start || eventStart > end) {
      add('TIMELINE_START_OUTSIDE_WINDOW', `timeline/${index}/start_seconds`, `timeline[${index}].start_seconds ${eventStart} is outside [${start}, ${end}]`);
    }
    if (eventEnd !== null && (eventEnd < eventStart || eventEnd > end)) {
      add('TIMELINE_END_OUTSIDE_WINDOW', `timeline/${index}/end_seconds`, `timeline[${index}].end_seconds ${eventEnd} is outside [${eventStart}, ${end}]`);
    }
    if (previousStart !== null && eventStart < previousStart) {
      add('TIMELINE_NOT_CHRONOLOGICAL', `timeline/${index}`, `timeline[${index}] is not in chronological order`);
    }
    previousStart = eventStart;
  });
  return violations;
}

/** Message-only view of crossFieldViolations (the eval cross_field_errors shape). */
export function crossFieldErrors(report: IncidentContractReport): string[] {
  return crossFieldViolations(report).map((violation) => violation.message);
}

/** Validate an already-decoded report; throws ContractError listing every violation. */
export function validateReport(report: unknown): IncidentContractReport {
  const validate = validator();
  if (!validate(report)) {
    const violations = [...(validate.errors ?? [])]
      .sort((a, b) => a.instancePath.localeCompare(b.instancePath))
      .map(schemaViolation);
    throw new ContractError(`schema violation: ${violations.map((v) => v.message).join('; ')}`, violations);
  }
  const typed = report as IncidentContractReport;
  const violations = crossFieldViolations(typed);
  if (violations.length) throw new ContractError(`cross-field violation: ${violations.map((v) => v.message).join('; ')}`, violations);
  return typed;
}

/** Add fields computed by code, never requested from the model (incident.duration). */
export function withDerivedFields(report: IncidentContractReport): DerivedContractReport {
  const { incident } = report;
  return { ...report, incident: { ...incident, duration: incident.end_timestamp - incident.start_timestamp } };
}

/** Strict JSON decoding of a model's message content (no fence stripping or brace extraction). */
export function decodeContent(content: string | null | undefined): unknown {
  if (!content) throw new ContractError('empty response content', [{ code: 'EMPTY_CONTENT', path: '<root>', message: 'empty response content' }]);
  try {
    return JSON.parse(content);
  } catch (error) {
    const detail = error instanceof Error ? error.message : String(error);
    const message = `content is not a single JSON document: ${detail}`;
    throw new ContractError(message, [{ code: 'INVALID_JSON', path: '<root>', message }]);
  }
}

/** Strictly decode and validate a model's message content, then add derived fields. */
export function parseReport(content: string | null | undefined): DerivedContractReport {
  return withDerivedFields(validateReport(decodeContent(content)));
}
