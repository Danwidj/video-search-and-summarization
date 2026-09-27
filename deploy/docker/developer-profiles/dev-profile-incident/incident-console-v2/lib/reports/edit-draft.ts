// SPDX-License-Identifier: Apache-2.0

// Browser-safe shape of a structured (Class A) reviewer edit and the helpers
// the editor uses. Identifiers are managed here, never typed by the reviewer:
// every change renumbers E#/I#/A# by position and carries instrument holders
// with their entity. Validation happens server-side
// (lib/contract/structured-edit.ts) and again in the database function.

import type { ReportView } from '@/lib/reports/report-view';

export const EDITABLE_INCIDENT_TYPES = ['road accident', 'burglary', 'explosion', 'assault', 'animal attack'] as const;
export const EDITABLE_ENTITY_TYPES = ['human', 'animal', 'unknown'] as const;

export interface StructuredEdit {
  incident: { type: string; start_timestamp: number; end_timestamp: number; description: string; severity_level: number };
  entities: Array<{ entity_id: string; type: string; description: string }>;
  instruments: Array<{ instrument_id: string; entity_id: string | null; name: string; description: string; threat_level: number }>;
  assets: Array<{ asset_id: string; name: string; description: string }>;
}

/** An in-progress edit: values a legacy run may lack (type, times, threat level) start empty and must be chosen. */
export interface EditDraft {
  incident: { type: string | null; start_timestamp: number | null; end_timestamp: number | null; description: string; severity_level: number | null };
  entities: Array<{ key: string; type: string; description: string }>;
  instruments: Array<{ key: string; holderKey: string | null; name: string; description: string; threat_level: number | null }>;
  assets: Array<{ key: string; name: string; description: string }>;
}

let keySequence = 0;
export const newKey = (prefix: string) => `${prefix}-${Date.now().toString(36)}-${(keySequence += 1)}`;

/**
 * Start an edit from the current structured values. Legacy values are
 * normalised for this edit only: contract types, integer seconds, E#/I#/A#
 * IDs by position, legacy 'person' -> 'human'. Values that cannot be mapped
 * (e.g. a legacy type outside the contract, an unrated threat) start empty.
 */
export function draftFromView(view: ReportView): EditDraft {
  const { incident, entities, instruments, assets } = view.structured;
  const allowedType = (EDITABLE_INCIDENT_TYPES as readonly string[]).includes(incident.type ?? '') ? incident.type : null;
  const entityKeys = new Map(entities.map((entity, index) => [entity.entityId, `entity-${index}`]));
  return {
    incident: {
      type: allowedType,
      start_timestamp: incident.startSeconds,
      end_timestamp: incident.endSeconds,
      description: incident.description ?? '',
      severity_level: incident.severityLevel !== null && incident.severityLevel >= 1 && incident.severityLevel <= 5 ? incident.severityLevel : null,
    },
    entities: entities.map((entity, index) => ({
      key: `entity-${index}`,
      type: (EDITABLE_ENTITY_TYPES as readonly string[]).includes(entity.type) ? entity.type : 'unknown',
      description: entity.description,
    })),
    instruments: instruments.map((instrument, index) => ({
      key: `instrument-${index}`,
      holderKey: instrument.entityId ? entityKeys.get(instrument.entityId) ?? null : null,
      name: instrument.name,
      description: instrument.description,
      threat_level: instrument.threatLevel !== null && instrument.threatLevel >= 1 && instrument.threatLevel <= 5 ? instrument.threatLevel : null,
    })),
    assets: assets.map((asset, index) => ({ key: `asset-${index}`, name: asset.name, description: asset.description })),
  };
}

/** Problems that stop the draft from becoming a complete edit (shown before sending). */
export function draftProblems(draft: EditDraft): string[] {
  const problems: string[] = [];
  const { incident } = draft;
  if (!incident.type) problems.push('Choose an incident type.');
  if (incident.start_timestamp === null || incident.end_timestamp === null) problems.push('Enter the incident start and end in seconds.');
  else if (incident.end_timestamp < incident.start_timestamp) problems.push('The incident end must not be before its start.');
  if (incident.severity_level === null) problems.push('Choose a severity level.');
  if (draft.instruments.some((instrument) => instrument.threat_level === null)) problems.push('Rate the threat level of every instrument (1-5).');
  return problems;
}

/** The edit sent to the server: sequential IDs by position, holders resolved to the renumbered entity IDs. */
export function editFromDraft(draft: EditDraft): StructuredEdit {
  const problems = draftProblems(draft);
  if (problems.length) throw new Error(problems.join(' '));
  const entityIdByKey = new Map(draft.entities.map((entity, index) => [entity.key, `E${index + 1}`]));
  return {
    incident: {
      type: draft.incident.type!,
      start_timestamp: draft.incident.start_timestamp!,
      end_timestamp: draft.incident.end_timestamp!,
      description: draft.incident.description,
      severity_level: draft.incident.severity_level!,
    },
    entities: draft.entities.map((entity, index) => ({ entity_id: `E${index + 1}`, type: entity.type, description: entity.description })),
    instruments: draft.instruments.map((instrument, index) => ({
      instrument_id: `I${index + 1}`,
      entity_id: instrument.holderKey ? entityIdByKey.get(instrument.holderKey) ?? null : null,
      name: instrument.name,
      description: instrument.description,
      threat_level: instrument.threat_level!,
    })),
    assets: draft.assets.map((asset, index) => ({ asset_id: `A${index + 1}`, name: asset.name, description: asset.description })),
  };
}
