// SPDX-License-Identifier: Apache-2.0

// Server-side validation of a structured (Class A) reviewer edit, built from
// the incident-contract-v2 schema itself (no second schema): the editable
// incident properties plus the contract's own entities / instruments / assets
// item schemas, then the contract's ID and holder rules and the window order.
// Class B (model-generated) and Class C (provenance) fields are rejected.

import Ajv2020 from 'ajv/dist/2020.js';
import type { ValidateFunction } from 'ajv';

import { schema } from '@/lib/contract/load';
import type { IncidentContractReport } from '@/lib/contract/types';
import { crossFieldViolations, type ContractViolation } from '@/lib/contract/validate';
import type { StructuredEdit } from '@/lib/reports/edit-draft';

export const EDITABLE_INCIDENT_FIELDS = ['type', 'start_timestamp', 'end_timestamp', 'description', 'severity_level'] as const;
const EDIT_COLLECTIONS = ['incident', 'entities', 'instruments', 'assets'] as const;

export class StructuredEditError extends Error {
  status: 400 | 422;
  violations: ContractViolation[];
  notEditable: string[];

  constructor(status: 400 | 422, message: string, violations: ContractViolation[] = [], notEditable: string[] = []) {
    super(message);
    this.name = 'StructuredEditError';
    this.status = status;
    this.violations = violations;
    this.notEditable = notEditable;
  }
}

let compiled: ValidateFunction | null = null;

function editValidator(): ValidateFunction {
  if (compiled) return compiled;
  const contract = schema() as { properties: Record<string, { properties?: Record<string, unknown> }> };
  const incidentProperties = contract.properties.incident.properties!;
  const editSchema = {
    type: 'object',
    additionalProperties: false,
    required: [...EDIT_COLLECTIONS],
    properties: {
      incident: {
        type: 'object',
        additionalProperties: false,
        required: [...EDITABLE_INCIDENT_FIELDS],
        properties: Object.fromEntries(EDITABLE_INCIDENT_FIELDS.map((field) => [field, incidentProperties[field]])),
      },
      entities: contract.properties.entities,
      instruments: contract.properties.instruments,
      assets: contract.properties.assets,
    },
  };
  compiled = new Ajv2020({ allErrors: true, strict: false }).compile(editSchema);
  return compiled;
}

/** Keys the reviewer may not edit (Class B model output, Class C provenance, derived duration, confidence). */
export function notEditableKeys(edit: unknown): string[] {
  if (!edit || typeof edit !== 'object' || Array.isArray(edit)) return [];
  const blocked = Object.keys(edit).filter((key) => !(EDIT_COLLECTIONS as readonly string[]).includes(key));
  const incident = (edit as { incident?: unknown }).incident;
  if (incident && typeof incident === 'object' && !Array.isArray(incident)) {
    blocked.push(...Object.keys(incident).filter((key) => !(EDITABLE_INCIDENT_FIELDS as readonly string[]).includes(key)).map((key) => `incident.${key}`));
  }
  return blocked;
}

export function validateStructuredEdit(edit: unknown): StructuredEdit {
  const blocked = notEditableKeys(edit);
  if (blocked.length) {
    throw new StructuredEditError(400, `Only structured fields can be edited; not editable: ${blocked.join(', ')}`, [], blocked);
  }
  const validate = editValidator();
  if (!validate(edit)) {
    const violations: ContractViolation[] = (validate.errors ?? []).map((error) => {
      const path = error.instancePath ? error.instancePath.slice(1) : '<root>';
      return { code: 'SCHEMA_VIOLATION', path, message: `${path}: ${error.message ?? error.keyword}` };
    });
    throw new StructuredEditError(422, `The edit does not satisfy the incident contract: ${violations.map((v) => v.message).join('; ')}`, violations);
  }
  const typed = edit as StructuredEdit;
  // The contract's own cross-field rules; the timeline is model output and not part of an edit.
  const pseudoReport = { ...typed, incident: { ...typed.incident }, timeline: [], uncertainties: [] } as unknown as IncidentContractReport;
  const violations = crossFieldViolations(pseudoReport);
  if (violations.length) {
    throw new StructuredEditError(422, `The edit does not satisfy the incident contract: ${violations.map((v) => v.message).join('; ')}`, violations);
  }
  return typed;
}
