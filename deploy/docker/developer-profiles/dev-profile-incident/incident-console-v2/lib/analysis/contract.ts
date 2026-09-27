// SPDX-License-Identifier: Apache-2.0

// Server-only access to the shared incident contract (../../contracts/): the P1/RP1 prompts,
// the request settings, and strict validation. The same files drive eval/ and vss-agent.
//
// Parsing is strict by design (.docs/prompt-contract-plan.md, D3-D5): the model's message content
// must be one JSON document that passes the JSON Schema and the cross-field rules. There is no fence
// stripping, brace extraction, alias mapping, coercion or repair; anything else raises ContractError.

import { readFileSync } from 'node:fs';
import path from 'node:path';

import Ajv2020 from 'ajv/dist/2020.js';
import type { ErrorObject, ValidateFunction } from 'ajv';

import type { IncidentContractReport } from '@/lib/analysis/contract-types';

export class ContractError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ContractError';
  }
}

/** Directory holding the contract files; override with INCIDENT_CONTRACTS_DIR. */
export function contractsDir(): string {
  const configured = process.env.INCIDENT_CONTRACTS_DIR?.trim();
  return configured ? path.resolve(configured) : path.resolve(process.cwd(), '..', 'contracts');
}

const cache = new Map<string, unknown>();

function cached<T>(key: string, load: () => T): T {
  if (!cache.has(`${contractsDir()}:${key}`)) cache.set(`${contractsDir()}:${key}`, load());
  return cache.get(`${contractsDir()}:${key}`) as T;
}

function readContractFile(name: string): string {
  return readFileSync(path.join(contractsDir(), name), 'utf8');
}

export function loadSchema(): Record<string, unknown> {
  return cached('schema', () => JSON.parse(readContractFile('incident_report.schema.json')) as Record<string, unknown>);
}

export function contractVersion(): string {
  return cached('version', () => readContractFile('VERSION').trim());
}

export function extractionPrompt(): string {
  return cached('p1-prompt', () => readContractFile('incident_extraction_prompt.md'));
}

export function reportPromptTemplate(): string {
  return cached('rp1-prompt', () => readContractFile('report_generation_prompt.md'));
}

/** Fixed P1 request settings (temperature, max_tokens, media_io_kwargs), shared with eval and the agent. */
export function p1Request(): Record<string, unknown> {
  return JSON.parse(readContractFile('p1_request.json')) as Record<string, unknown>;
}

/** Fixed RP1 request: `model` plus its inference settings, shared with eval and the agent. */
export function rp1Request(): { model: string } & Record<string, unknown> {
  const value = JSON.parse(readContractFile('rp1_request.json')) as { model?: unknown } & Record<string, unknown>;
  if (typeof value.model !== 'string' || !value.model) throw new ContractError('rp1_request.json has no model');
  return value as { model: string } & Record<string, unknown>;
}

/** OpenAI-compatible response_format enforcing the contract (strict mode). */
export function responseFormat(): Record<string, unknown> {
  const { $schema: _schema, $id: _id, ...schema } = loadSchema();
  return { type: 'json_schema', json_schema: { name: 'incident_report', schema, strict: true } };
}

function validator(): ValidateFunction {
  return cached('validator', () => new Ajv2020({ allErrors: true, strict: false }).compile(loadSchema()));
}

function describeErrors(errors: ErrorObject[] | null | undefined): string {
  return (errors ?? [])
    .map((error) => `${error.instancePath || '<root>'}: ${error.message ?? 'invalid'}`)
    .join('; ');
}

type ModelOutput = Omit<IncidentContractReport, 'incident'> & {
  incident: Omit<IncidentContractReport['incident'], 'duration'>;
};

/** Rules JSON Schema cannot express. Assumes the value already passed the schema. */
export function crossFieldErrors(report: ModelOutput): string[] {
  const errors: string[] = [];
  const { start_timestamp: start, end_timestamp: end } = report.incident;
  if (end < start) errors.push(`end_timestamp ${end} is before start_timestamp ${start}`);

  const sequences: Array<[string, string, Array<Record<string, unknown>>]> = [
    ['E', 'entity_id', report.entities as unknown as Array<Record<string, unknown>>],
    ['I', 'instrument_id', report.instruments as unknown as Array<Record<string, unknown>>],
    ['A', 'asset_id', report.assets as unknown as Array<Record<string, unknown>>],
  ];
  for (const [prefix, key, items] of sequences) {
    const expected = items.map((_, index) => `${prefix}${index + 1}`);
    const actual = items.map((item) => item[key]);
    if (JSON.stringify(actual) !== JSON.stringify(expected)) {
      errors.push(`${key} values ${JSON.stringify(actual)} are not sequential ${JSON.stringify(expected)}`);
    }
  }

  const entityIds = new Set(report.entities.map((entity) => entity.entity_id));
  for (const instrument of report.instruments) {
    if (instrument.entity_id !== null && !entityIds.has(instrument.entity_id)) {
      errors.push(`${instrument.instrument_id} references unknown entity_id ${instrument.entity_id}`);
    }
  }

  let previousStart: number | null = null;
  report.timeline.forEach((event, index) => {
    if (event.start_seconds < start || event.start_seconds > end) {
      errors.push(`timeline[${index}].start_seconds ${event.start_seconds} is outside [${start}, ${end}]`);
    }
    if (event.end_seconds !== null && (event.end_seconds < event.start_seconds || event.end_seconds > end)) {
      errors.push(`timeline[${index}].end_seconds ${event.end_seconds} is outside [${event.start_seconds}, ${end}]`);
    }
    if (previousStart !== null && event.start_seconds < previousStart) {
      errors.push(`timeline[${index}] is not in chronological order`);
    }
    previousStart = event.start_seconds;
  });
  return errors;
}

/** Add fields computed by code, never requested from the model (incident.duration). */
export function withDerivedFields(report: ModelOutput): IncidentContractReport {
  const { incident } = report;
  return { ...report, incident: { ...incident, duration: incident.end_timestamp - incident.start_timestamp } };
}

/** Validate an already-decoded model output (no derived fields); throws ContractError listing every violation. */
export function validateModelOutput(value: unknown): IncidentContractReport {
  const validate = validator();
  if (!validate(value)) throw new ContractError(`schema violation: ${describeErrors(validate.errors)}`);
  const report = value as ModelOutput;
  const errors = crossFieldErrors(report);
  if (errors.length) throw new ContractError(`cross-field violation: ${errors.join('; ')}`);
  return withDerivedFields(report);
}

/** Strictly decode and validate a model's message content, then add derived fields. */
export function parseContractContent(content: string | null | undefined): IncidentContractReport {
  if (!content) throw new ContractError('empty response content');
  let decoded: unknown;
  try {
    decoded = JSON.parse(content);
  } catch (error) {
    throw new ContractError(`content is not a single JSON document: ${error instanceof Error ? error.message : String(error)}`);
  }
  return validateModelOutput(decoded);
}

/**
 * Validate a report that already carries derived fields (stored, returned by the agent, or edited by a
 * reviewer): derived fields are dropped, the rest is validated strictly, then they are recomputed.
 */
export function validateContractReport(value: unknown): IncidentContractReport {
  if (!value || typeof value !== 'object' || Array.isArray(value)) throw new ContractError('schema violation: <root>: must be object');
  const source = value as Record<string, unknown>;
  const incident = source.incident;
  const withoutDerived: Record<string, unknown> = {
    incident: incident && typeof incident === 'object' && !Array.isArray(incident)
      ? Object.fromEntries(Object.entries(incident as Record<string, unknown>).filter(([key]) => key !== 'duration'))
      : incident,
    entities: source.entities,
    instruments: source.instruments,
    assets: source.assets,
    timeline: source.timeline,
    uncertainties: source.uncertainties,
  };
  return validateModelOutput(withoutDerived);
}
