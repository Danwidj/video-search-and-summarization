// SPDX-License-Identifier: Apache-2.0

// Applies the chat editor's proposed actions (chat editor report, section 3) to an edit draft. Pure and browser-safe.
// The caller passes the draft in and stores the returned one with a single change, so Undo reverts the whole chat request.
// An action that cannot be applied is skipped and reported with its reason; the other actions still apply. Problems the
// result still has come from draftProblems, the same check a hand edit gets. Evidence actions are not applied here: a box
// is only trusted once the reviewer confirms it (report section 5): a change_evidence action
// becomes an unconfirmed proposal on the item (lib/evidence/evidence-proposals.ts), and draftProblems blocks Save until
// the reviewer confirms, adjusts or dismisses it.

import { z } from 'zod';
import { proposeEvidence } from '@/lib/evidence/evidence-proposals';
import { deleteDraftItem } from '@/lib/reports/compare';
import {
  EDITABLE_ENTITY_TYPES,
  EDITABLE_INCIDENT_TYPES,
  type EditDraft,
  draftProblems,
  newEntityDraft,
  newItemDetails,
} from '@/modules/reports/domain/edit-draft';
import { parseReviewerTrack } from '@/modules/reports/domain/reviewer-item';

export interface AgentAction {
  id: string;
  tool: string;
  args: unknown;
}

export interface AppliedAction {
  id: string;
  tool: string;
  /** What the reviewer should know beyond the action itself, such as items removed along with it. */
  note?: string;
}

export interface SkippedAction {
  id: string;
  tool: string;
  reason: string;
}

export interface ApplyResult {
  draft: EditDraft;
  applied: AppliedAction[];
  skipped: SkippedAction[];
  problems: string[];
}

type DraftEntity = EditDraft['entities'][number];
type DraftInstrument = EditDraft['instruments'][number];
type DraftAsset = EditDraft['assets'][number];
type DraftItem = DraftEntity | DraftInstrument | DraftAsset;

interface Outcome {
  draft: EditDraft;
  note?: string;
}

type Handler = (draft: EditDraft, args: unknown) => Outcome;

/** Thrown for an action that cannot be applied; any other error is a bug and is not caught. */
class CannotApply extends Error {}

const cannot = (reason: string): never => {
  throw new CannotApply(reason);
};

const EVIDENCE_REASON = 'evidence changes are not applied here; the reviewer confirms each box in the editor';

const itemKey = z.string().min(1);
const seconds = z.number().finite().min(0);
const threatLevel = z.number().int().min(1).max(5);

const incidentFields = z
  .object({
    type: z.enum(EDITABLE_INCIDENT_TYPES),
    title: z.string().trim().min(1),
    description: z.string(),
    severity: z.string().regex(/^[1-5]$/, 'must be a severity from 1 to 5'),
    startSeconds: seconds,
    endSeconds: seconds,
  })
  .partial()
  .strict();

const timelineItem = z.object({ itemKey, timestampSeconds: seconds.optional(), label: z.string().optional() }).strict();

const entityFields = {
  entityType: z.enum(EDITABLE_ENTITY_TYPES).optional(),
  name: z.string().optional(),
  description: z.string().optional(),
  firstSeenSeconds: seconds.optional(),
  lastSeenSeconds: seconds.optional(),
};
const upsertEntity = z.discriminatedUnion('op', [
  z.object({ op: z.literal('add'), ...entityFields }).strict(),
  z.object({ op: z.literal('edit'), itemKey, ...entityFields }).strict(),
  z.object({ op: z.literal('delete'), itemKey }).strict(),
]);

const instrumentFields = {
  name: z.string().optional(),
  description: z.string().optional(),
  threatLevel: threatLevel.optional(),
  timestampSeconds: seconds.optional(),
};
const upsertInstrument = z.discriminatedUnion('op', [
  z.object({ op: z.literal('add'), ...instrumentFields }).strict(),
  z.object({ op: z.literal('edit'), itemKey, ...instrumentFields }).strict(),
  z.object({ op: z.literal('delete'), itemKey }).strict(),
]);

const assetFields = {
  name: z.string().optional(),
  description: z.string().optional(),
  timestampSeconds: seconds.optional(),
};
const upsertAsset = z.discriminatedUnion('op', [
  z.object({ op: z.literal('add'), ...assetFields }).strict(),
  z.object({ op: z.literal('edit'), itemKey, ...assetFields }).strict(),
  z.object({ op: z.literal('delete'), itemKey }).strict(),
]);

const setInstrumentHolder = z.object({ instrumentKey: itemKey, holderKey: itemKey.nullable() }).strict();

/** The fields that are set, without the ones left out. */
const defined = <T extends object>(values: T): Partial<T> =>
  Object.fromEntries(Object.entries(values).filter(([, value]) => value !== undefined)) as Partial<T>;

const parse = <T>(schema: z.ZodType<T>, args: unknown): T => {
  const result = schema.safeParse(args);
  if (!result.success) {
    const [issue] = result.error.issues;
    throw new CannotApply(`invalid arguments: ${issue.path.join('.') || 'arguments'} ${issue.message}`);
  }
  return result.data;
};

const patchByKey = <T extends { key: string }>(items: T[], key: string, patch: Partial<T>): T[] =>
  items.map((item) => (item.key === key ? Object.assign({}, item, patch) : item));

const ensureKey = (items: Array<{ key: string }>, key: string, label: string): void => {
  if (!items.some((item) => item.key === key)) cannot(`no ${label} with key "${key}"`);
};

const ensureAnyItem = (draft: EditDraft, key: string): void => {
  const items: DraftItem[] = [...draft.entities, ...draft.instruments, ...draft.assets];
  if (!items.some((item) => item.key === key)) cannot(`no item with key "${key}"`);
};

const requireChange = (patch: object, what: string): void => {
  if (Object.keys(patch).length === 0) cannot(`no ${what} to change`);
};

const setIncidentFields: Handler = (draft, args) => {
  const data = parse(incidentFields, args);
  const patch = defined({
    type: data.type,
    title: data.title,
    description: data.description,
    severity_level: data.severity === undefined ? undefined : Number(data.severity),
    start_timestamp: data.startSeconds,
    end_timestamp: data.endSeconds,
  });
  requireChange(patch, 'incident field');
  return { draft: { ...draft, incident: { ...draft.incident, ...patch } } };
};

const setTimelineItem: Handler = (draft, args) => {
  const data = parse(timelineItem, args);
  const patch = defined({ timestampSeconds: data.timestampSeconds, label: data.label });
  requireChange(patch, 'timeline field');
  ensureAnyItem(draft, data.itemKey);
  return {
    draft: {
      ...draft,
      entities: patchByKey(draft.entities, data.itemKey, patch),
      instruments: patchByKey(draft.instruments, data.itemKey, patch),
      assets: patchByKey(draft.assets, data.itemKey, patch),
    },
  };
};

const addEntity = (draft: EditDraft, data: z.infer<typeof upsertEntity> & { op: 'add' }): Outcome => {
  const entity = newEntityDraft(
    draft,
    defined({
      type: data.entityType,
      label: data.name,
      description: data.description,
      firstSeenSeconds: data.firstSeenSeconds,
      lastSeenSeconds: data.lastSeenSeconds,
    }),
  );
  return { draft: { ...draft, entities: [...draft.entities, entity] } };
};

const upsertEntityHandler: Handler = (draft, args) => {
  const data = parse(upsertEntity, args);
  if (data.op === 'add') return addEntity(draft, data);
  ensureKey(draft.entities, data.itemKey, 'entity');
  if (data.op === 'delete') {
    const held = draft.instruments.filter((instrument) => instrument.holderKey === data.itemKey).length;
    return {
      draft: deleteDraftItem(draft, 'entity', data.itemKey),
      note: held ? `also removed the ${held} instrument${held === 1 ? '' : 's'} it held` : undefined,
    };
  }
  const patch = defined({
    type: data.entityType,
    label: data.name,
    description: data.description,
    firstSeenSeconds: data.firstSeenSeconds,
    lastSeenSeconds: data.lastSeenSeconds,
  });
  requireChange(patch, 'entity field');
  return { draft: { ...draft, entities: patchByKey(draft.entities, data.itemKey, patch) } };
};

const upsertInstrumentHandler: Handler = (draft, args) => {
  const data = parse(upsertInstrument, args);
  if (data.op === 'add') {
    const base = newItemDetails('instrument', draft);
    const instrument: DraftInstrument = {
      ...base,
      ...defined({ timestampSeconds: data.timestampSeconds }),
      label: data.name ?? '',
      holderKey: null,
      name: data.name ?? '',
      description: data.description ?? '',
      threat_level: data.threatLevel ?? null,
    };
    return { draft: { ...draft, instruments: [...draft.instruments, instrument] } };
  }
  ensureKey(draft.instruments, data.itemKey, 'instrument');
  if (data.op === 'delete') return { draft: deleteDraftItem(draft, 'instrument', data.itemKey) };
  const patch = defined({
    name: data.name,
    description: data.description,
    threat_level: data.threatLevel,
    timestampSeconds: data.timestampSeconds,
  });
  requireChange(patch, 'instrument field');
  return { draft: { ...draft, instruments: patchByKey(draft.instruments, data.itemKey, patch) } };
};

const upsertAssetHandler: Handler = (draft, args) => {
  const data = parse(upsertAsset, args);
  if (data.op === 'add') {
    const base = newItemDetails('asset', draft);
    const asset: DraftAsset = {
      ...base,
      ...defined({ timestampSeconds: data.timestampSeconds }),
      label: data.name ?? '',
      name: data.name ?? '',
      description: data.description ?? '',
    };
    return { draft: { ...draft, assets: [...draft.assets, asset] } };
  }
  ensureKey(draft.assets, data.itemKey, 'asset');
  if (data.op === 'delete') return { draft: deleteDraftItem(draft, 'asset', data.itemKey) };
  const patch = defined({ name: data.name, description: data.description, timestampSeconds: data.timestampSeconds });
  requireChange(patch, 'asset field');
  return { draft: { ...draft, assets: patchByKey(draft.assets, data.itemKey, patch) } };
};

const setHolder: Handler = (draft, args) => {
  const data = parse(setInstrumentHolder, args);
  ensureKey(draft.instruments, data.instrumentKey, 'instrument');
  if (data.holderKey !== null) ensureKey(draft.entities, data.holderKey, 'entity');
  return { draft: { ...draft, instruments: patchByKey(draft.instruments, data.instrumentKey, { holderKey: data.holderKey }) } };
};

const notApplied: Handler = () => cannot(EVIDENCE_REASON);

const evidenceBox = z.tuple([
  z.number().min(0).max(1000),
  z.number().min(0).max(1000),
  z.number().min(0).max(1000),
  z.number().min(0).max(1000),
]);
const windowSeconds = z.number().finite().min(0).max(30);

// A re-track names the seed (seconds, box) the tracker ran from; `track` is the tracker's answer, added by the page before applying.
const changeEvidenceArgs = z.discriminatedUnion('op', [
  z
    .object({
      op: z.literal('retrack'),
      itemKey,
      seconds: seconds.optional(),
      box: evidenceBox.optional(),
      backSeconds: windowSeconds.optional(),
      forwardSeconds: windowSeconds.optional(),
      locateConfidence: z.enum(['checked', 'unchecked']).optional(),
      track: z.unknown().optional(),
      reason: z.string().optional(),
    })
    .strict(),
  z.object({ op: z.literal('set_image'), itemKey, seconds, box: evidenceBox, reason: z.string().optional() }).strict(),
]);

/** A re-track or set-image proposal on an existing item; the track a re-track carries is the tracker's answer, already fetched. */
const changeEvidence: Handler = (draft, args) => {
  const data = parse(changeEvidenceArgs, args);
  ensureAnyItem(draft, data.itemKey);
  const reason = data.reason ?? null;
  if (data.op === 'set_image') {
    return {
      draft: proposeEvidence(draft, data.itemKey, { kind: 'set_image', pick: { seconds: data.seconds, box: data.box }, reason }),
      note: 'proposed; the reviewer confirms the image before saving',
    };
  }
  const track = parseReviewerTrack(data.track);
  if (!track) return cannot('the tracker produced no usable track for this item');
  return {
    draft: proposeEvidence(draft, data.itemKey, { kind: 'retrack', track, reason }),
    note: 'proposed; the reviewer confirms the track before saving',
  };
};

// A Map, not an object: a tool named "constructor" must be unknown, not a prototype property.
const HANDLERS = new Map<string, Handler>([
  ['set_incident_fields', setIncidentFields],
  ['set_timeline_item', setTimelineItem],
  ['upsert_entity', upsertEntityHandler],
  ['upsert_instrument', upsertInstrumentHandler],
  ['upsert_asset', upsertAssetHandler],
  ['set_instrument_holder', setHolder],
  ['change_evidence', changeEvidence],
  ['add_evidence', notApplied],
]);

/** Applies the actions in order to a copy of the draft; the input draft is never changed. */
export function applyAgentActions(draft: EditDraft, actions: AgentAction[]): ApplyResult {
  let next = draft;
  const applied: AppliedAction[] = [];
  const skipped: SkippedAction[] = [];
  for (const { id, tool, args } of actions) {
    const handler = HANDLERS.get(tool);
    if (!handler) {
      skipped.push({ id, tool, reason: `unknown tool "${tool}"` });
      continue;
    }
    try {
      const outcome = handler(next, args);
      next = outcome.draft;
      applied.push(outcome.note ? { id, tool, note: outcome.note } : { id, tool });
    } catch (error) {
      if (!(error instanceof CannotApply)) throw error;
      skipped.push({ id, tool, reason: error.message });
    }
  }
  return { draft: next, applied, skipped, problems: draftProblems(next) };
}
