// SPDX-License-Identifier: Apache-2.0

// id-normalization-v1: the only repair the application applies to a
// contract-invalid first response. It changes identifiers, the one structured
// reference to them (instruments[].entity_id) and list order - nothing else.
// It is attempted only when every first-pass violation is repair-eligible, it
// never edits free text or any substantive value, and the caller must re-run
// the full strict validator on its output. eval/ never uses it: eval scores
// the original first response only.

import type { IncidentContractReport } from '@/lib/contract/types';
import type { ContractViolation, ContractViolationCode } from '@/lib/contract/validate';

export const REPAIR_RULE_SET = 'id-normalization-v1';

/** Always repair-eligible. */
const ELIGIBLE_CODES: ReadonlySet<ContractViolationCode> = new Set([
  'ID_NOT_SEQUENTIAL_ENTITY',
  'ID_NOT_SEQUENTIAL_INSTRUMENT',
  'ID_NOT_SEQUENTIAL_ASSET',
]);

/**
 * Eligible only when the unknown holder is a malformed entity ID that the
 * renumbering maps to an existing entity. The validator reports this code only
 * when the holder matches no entity ID at all, so in practice it always ends in
 * INSTRUMENT_HOLDER_UNRESOLVABLE below; it is listed so the approved rule is
 * implemented literally rather than silently dropped.
 */
const CONDITIONALLY_ELIGIBLE_CODES: ReadonlySet<ContractViolationCode> = new Set(['INSTRUMENT_HOLDER_UNKNOWN']);

export type RepairIneligibility =
  | 'INELIGIBLE_VIOLATION'
  | 'DUPLICATE_ID'
  | 'RENAMED_ID_IN_FREE_TEXT'
  | 'TARGET_ID_IN_FREE_TEXT'
  | 'INSTRUMENT_HOLDER_UNRESOLVABLE'
  | 'INVARIANCE_CHECK_FAILED';

export type RepairOperation =
  | { op: 'reorder'; collection: Collection; from: string[]; to: string[] }
  | { op: 'rename-id'; collection: Collection; from: string; to: string }
  | { op: 'remap-reference'; path: string; from: string; to: string };

export type RepairResult =
  | { eligible: false; ruleSet: string; reason: RepairIneligibility; blockingCodes: ContractViolationCode[]; detail: string }
  | { eligible: true; ruleSet: string; operations: RepairOperation[]; repaired: IncidentContractReport };

type Collection = 'entities' | 'instruments' | 'assets';

const COLLECTIONS: Array<{ collection: Collection; key: 'entity_id' | 'instrument_id' | 'asset_id'; prefix: string }> = [
  { collection: 'entities', key: 'entity_id', prefix: 'E' },
  { collection: 'instruments', key: 'instrument_id', prefix: 'I' },
  { collection: 'assets', key: 'asset_id', prefix: 'A' },
];

function ineligible(reason: RepairIneligibility, blockingCodes: ContractViolationCode[], detail: string): RepairResult {
  return { eligible: false, ruleSet: REPAIR_RULE_SET, reason, blockingCodes, detail };
}

/** Every free-text value in the report; identifiers are never rewritten inside these. */
function freeTexts(report: IncidentContractReport): string[] {
  const { incident } = report;
  return [
    incident.title,
    incident.description,
    incident.severity_reason,
    incident.location ?? '',
    ...report.entities.map((item) => item.description),
    ...report.instruments.flatMap((item) => [item.name, item.description]),
    ...report.assets.flatMap((item) => [item.name, item.description]),
    ...report.timeline.map((event) => event.description),
    ...report.uncertainties,
  ];
}

function hasWordOrDigit(value: string): boolean {
  return /[A-Za-z0-9]/.test(value);
}

function mentionedInText(token: string, texts: string[]): boolean {
  const escaped = token.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
  const pattern = new RegExp(`(?<![A-Za-z0-9])${escaped}(?![A-Za-z0-9])`);
  return texts.some((text) => pattern.test(text));
}

/**
 * Semantic projection used by the invariance check: everything except the
 * identifiers and list order. Each instrument carries its holder's content
 * instead of the holder's ID, so a remapped reference must still point at the
 * same entity.
 */
function semanticProjection(report: IncidentContractReport): string {
  const entityById = new Map(report.entities.map((entity) => [entity.entity_id, entity]));
  const sorted = (items: unknown[]) => items.map((item) => JSON.stringify(item)).sort();
  return JSON.stringify({
    incident: report.incident,
    timeline: report.timeline,
    uncertainties: report.uncertainties,
    entities: sorted(report.entities.map(({ entity_id: _id, ...rest }) => rest)),
    instruments: sorted(report.instruments.map(({ instrument_id: _id, entity_id: holder, ...rest }) => {
      const entity = holder === null ? null : entityById.get(holder);
      return { ...rest, holder: entity ? { type: entity.type, description: entity.description } : holder };
    })),
    assets: sorted(report.assets.map(({ asset_id: _id, ...rest }) => rest)),
  });
}

/**
 * Apply id-normalization-v1 to a schema-valid first response whose
 * cross-field violations are `violations`. Returns the repaired report and the
 * exact operations, or why it is not eligible. The caller re-validates.
 */
export function attemptIdNormalization(report: IncidentContractReport, violations: ContractViolation[]): RepairResult {
  const blocking = violations.filter((violation) => !ELIGIBLE_CODES.has(violation.code) && !CONDITIONALLY_ELIGIBLE_CODES.has(violation.code));
  if (blocking.length || !violations.length) {
    return ineligible('INELIGIBLE_VIOLATION', [...new Set(blocking.map((violation) => violation.code))], blocking.map((violation) => violation.message).join('; ') || 'no violations to repair');
  }

  const texts = freeTexts(report);
  const operations: RepairOperation[] = [];
  const mappings = new Map<Collection, Map<string, string>>();
  const reordered: Partial<Record<Collection, unknown[]>> = {};

  for (const { collection, key, prefix } of COLLECTIONS) {
    const items = report[collection] as unknown as Array<Record<string, unknown>>;
    const ids = items.map((item) => String(item[key]));
    const n = ids.length;
    if (new Set(ids).size !== n) return ineligible('DUPLICATE_ID', [], `${collection} has duplicate IDs ${JSON.stringify(ids)}`);

    const wellFormed = new RegExp(`^${prefix}([1-9][0-9]*)$`);
    const finalNumber = new Array<number | null>(n).fill(null);
    const used = new Set<number>();
    ids.forEach((id, index) => {
      const match = wellFormed.exec(id);
      if (match && Number(match[1]) <= n) {
        finalNumber[index] = Number(match[1]);
        used.add(Number(match[1]));
      }
    });
    const free = Array.from({ length: n }, (_, index) => index + 1).filter((number) => !used.has(number));
    const mapping = new Map<string, string>();
    ids.forEach((id, index) => {
      if (finalNumber[index] === null) finalNumber[index] = free.shift()!;
      mapping.set(id, `${prefix}${finalNumber[index]}`);
    });
    for (const [from, to] of mapping) {
      if (from === to) continue;
      if (hasWordOrDigit(from) && mentionedInText(from, texts)) {
        return ineligible('RENAMED_ID_IN_FREE_TEXT', [], `${from} would be renamed to ${to} but is mentioned in free text`);
      }
      if (mentionedInText(to, texts)) {
        return ineligible('TARGET_ID_IN_FREE_TEXT', [], `${from} would be renamed to ${to}, which free text already mentions`);
      }
      operations.push({ op: 'rename-id', collection, from, to });
    }
    mappings.set(collection, mapping);

    const renamed = items.map((item) => ({ ...item, [key]: mapping.get(String(item[key]))! }));
    const sorted = [...renamed].sort((a, b) => Number(String(a[key]).slice(1)) - Number(String(b[key]).slice(1)));
    const before = renamed.map((item) => String(item[key]));
    const after = sorted.map((item) => String(item[key]));
    if (before.some((id, index) => id !== after[index])) operations.push({ op: 'reorder', collection, from: before, to: after });
    reordered[collection] = sorted;
  }

  const entityMapping = mappings.get('entities')!;
  const instruments = (reordered.instruments as IncidentContractReport['instruments']).map((instrument, index) => {
    if (instrument.entity_id === null) return instrument;
    const target = entityMapping.get(instrument.entity_id);
    if (target === undefined) return null;
    if (target !== instrument.entity_id) operations.push({ op: 'remap-reference', path: `instruments/${index}/entity_id`, from: instrument.entity_id, to: target });
    return { ...instrument, entity_id: target };
  });
  if (instruments.some((instrument) => instrument === null)) {
    return ineligible('INSTRUMENT_HOLDER_UNRESOLVABLE', ['INSTRUMENT_HOLDER_UNKNOWN'], 'an instrument holder matches no entity ID, so ID normalization cannot resolve it');
  }

  const repaired: IncidentContractReport = {
    ...report,
    entities: reordered.entities as IncidentContractReport['entities'],
    instruments: instruments as IncidentContractReport['instruments'],
    assets: reordered.assets as IncidentContractReport['assets'],
  };
  if (semanticProjection(repaired) !== semanticProjection(report)) {
    return ineligible('INVARIANCE_CHECK_FAILED', [], 'the repair would change content other than identifiers and order');
  }
  return { eligible: true, ruleSet: REPAIR_RULE_SET, operations, repaired };
}
