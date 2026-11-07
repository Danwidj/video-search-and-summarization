// SPDX-License-Identifier: Apache-2.0

// Chat edits: the report chat asks the agent's report editor for changes to the live draft and applies what comes back.
// The agent sees a snapshot of the draft (snake_case, items by their stable draft key) and proposes edits in its own
// argument shapes; this file turns them into the applier's (apply-agent-actions.ts). Pure and browser-safe.
// A request takes seconds, so the reviewer may edit meanwhile: an action whose target changed since the snapshot was
// taken is skipped rather than written over. The caller stores the result with one changeDraft, so Undo reverts the
// whole request.

import { type AgentAction, type AppliedAction, type SkippedAction, applyAgentActions } from '@/lib/edits/apply-agent-actions';
import type { EditDraft } from '@/modules/reports/domain/edit-draft';

/** What a draft item's key stands for in the chat edit highlight; the incident header has no key of its own. */
export const INCIDENT_HIGHLIGHT_KEY = 'incident';

/** The draft in the shape POST /api/v1/incidents/{id}/investigate takes as `draft` (the draft-edits snapshot). */
export function draftSnapshot(draft: EditDraft): Record<string, unknown> {
  const { incident } = draft;
  return {
    incident: {
      type: incident.type,
      title: incident.title,
      start_timestamp: incident.start_timestamp,
      end_timestamp: incident.end_timestamp,
      description: incident.description,
      severity_level: incident.severity_level,
      severity_reason: incident.severity_reason,
    },
    entities: draft.entities.map((entity) => ({
      key: entity.key,
      type: entity.type || 'unknown',
      description: entity.description,
      first_seen_seconds: entity.firstSeenSeconds,
      last_seen_seconds: entity.lastSeenSeconds,
      timestamp_seconds: entity.timestampSeconds,
      label: entity.label,
    })),
    instruments: draft.instruments.map((instrument) => ({
      key: instrument.key,
      holder_key: instrument.holderKey,
      name: instrument.name,
      description: instrument.description,
      threat_level: instrument.threat_level,
      timestamp_seconds: instrument.timestampSeconds,
      label: instrument.label,
    })),
    assets: draft.assets.map((asset) => ({
      key: asset.key,
      name: asset.name,
      description: asset.description,
      timestamp_seconds: asset.timestampSeconds,
      label: asset.label,
    })),
  };
}

export interface ProposedAction {
  tool: string;
  args: Record<string, unknown>;
}

const PREFIX = 'propose_';

/** Only the keys whose value is set, renamed through `names`; a key not in `names` is dropped. */
const rename = (args: Record<string, unknown>, names: Record<string, string>): Record<string, unknown> =>
  Object.fromEntries(
    Object.entries(names)
      .filter(([from]) => args[from] !== undefined && args[from] !== null)
      .map(([from, to]) => [to, args[from]]),
  );

const COLLECTIONS = ['entities', 'instruments', 'assets'] as const;
const UPSERT_TOOL = { entities: 'upsert_entity', instruments: 'upsert_instrument', assets: 'upsert_asset' } as const;

/**
 * The agent's proposals as applier actions. Argument names change (item_key to itemKey); a delete is an op of the
 * item's own tool, found by the key; an entity's timestamp is a separate timeline action, as the applier has no field
 * for it. Seconds of an added item and a severity reason have no applier field and are dropped.
 */
export function toApplierActions(draft: EditDraft, proposals: ProposedAction[]): AgentAction[] {
  const actions: AgentAction[] = [];
  const push = (tool: string, args: Record<string, unknown>) => actions.push({ id: `chat-${actions.length + 1}`, tool, args });
  for (const { tool: raw, args } of proposals) {
    const tool = raw.startsWith(PREFIX) ? raw.slice(PREFIX.length) : raw;
    switch (tool) {
      case 'set_incident_fields': {
        const fields = rename(args, {
          type: 'type',
          title: 'title',
          description: 'description',
          start_timestamp: 'startSeconds',
          end_timestamp: 'endSeconds',
        });
        if (typeof args.severity_level === 'number') fields.severity = String(args.severity_level);
        push(tool, fields);
        break;
      }
      case 'set_timeline_item':
        push(tool, rename(args, { item_key: 'itemKey', timestamp_seconds: 'timestampSeconds', label: 'label' }));
        break;
      case 'upsert_entity': {
        push(
          tool,
          rename(args, {
            op: 'op',
            item_key: 'itemKey',
            entity_type: 'entityType',
            description: 'description',
            first_seen_seconds: 'firstSeenSeconds',
            last_seen_seconds: 'lastSeenSeconds',
          }),
        );
        if (args.op === 'edit' && typeof args.timestamp_seconds === 'number')
          push('set_timeline_item', { itemKey: args.item_key, timestampSeconds: args.timestamp_seconds });
        break;
      }
      case 'upsert_instrument':
        push(
          tool,
          rename(args, {
            op: 'op',
            item_key: 'itemKey',
            name: 'name',
            description: 'description',
            threat_level: 'threatLevel',
            timestamp_seconds: 'timestampSeconds',
          }),
        );
        break;
      case 'upsert_asset':
        push(
          tool,
          rename(args, {
            op: 'op',
            item_key: 'itemKey',
            name: 'name',
            description: 'description',
            timestamp_seconds: 'timestampSeconds',
          }),
        );
        break;
      case 'set_instrument_holder':
        push(tool, { instrumentKey: args.instrument_key, holderKey: args.holder_key ?? null });
        break;
      case 'delete_item': {
        const collection = COLLECTIONS.find((name) => draft[name].some((item) => item.key === args.item_key));
        push(collection ? UPSERT_TOOL[collection] : tool, { op: 'delete', itemKey: args.item_key });
        break;
      }
      default:
        push(tool, args);
    }
  }
  return actions;
}

/** The keys an action targets in the draft it was proposed for: existing items only, `incident` for the incident fields. */
function targets(action: AgentAction): string[] {
  const args = (action.args ?? {}) as Record<string, unknown>;
  if (action.tool === 'set_incident_fields') return [INCIDENT_HIGHLIGHT_KEY];
  return [args.itemKey, args.instrumentKey, args.holderKey].filter((key): key is string => typeof key === 'string');
}

const items = (draft: EditDraft) => [...draft.entities, ...draft.instruments, ...draft.assets];
const same = (a: unknown, b: unknown) => JSON.stringify(a) === JSON.stringify(b);

/** Whether the reviewer changed what an action targets between the snapshot the agent saw and the draft now. */
function changedSince(sent: EditDraft, now: EditDraft, key: string): boolean {
  if (key === INCIDENT_HIGHLIGHT_KEY) return !same(sent.incident, now.incident);
  const before = items(sent).find((item) => item.key === key);
  const after = items(now).find((item) => item.key === key);
  return !same(before, after);
}

export interface ChatEditResult {
  draft: EditDraft;
  applied: AppliedAction[];
  skipped: SkippedAction[];
  /** The keys of the items the edit added or changed, and `incident` for the incident fields: what the page highlights. */
  changedKeys: string[];
  /** The keys of the items the edit removed: a change too, though the page has nothing left to highlight for them. */
  removedKeys: string[];
}

const NO_CHANGE = 'no change: the draft already had this';
const DELETE_TOOL = 'delete_item';

/**
 * Applies the agent's proposals to the draft as it is now, one at a time. `sent` is the draft the agent was shown: an action
 * on an item the reviewer changed since is skipped with that reason. An action that leaves the draft as it was is skipped
 * with NO_CHANGE, and a delete is reported as a delete with the item it removed.
 */
export function applyChatEdit(now: EditDraft, sent: EditDraft, proposals: ProposedAction[]): ChatEditResult {
  const applied: AppliedAction[] = [];
  const skipped: SkippedAction[] = [];
  let draft = now;
  for (const action of toApplierActions(sent, proposals)) {
    if (targets(action).some((target) => changedSince(sent, now, target))) {
      skipped.push({ id: action.id, tool: action.tool, reason: 'you changed this while the assistant was working' });
      continue;
    }
    const result = applyAgentActions(draft, [action]);
    const [failure] = result.skipped;
    if (failure) {
      skipped.push(failure);
      continue;
    }
    if (same(draft, result.draft)) {
      skipped.push({ id: action.id, tool: action.tool, reason: NO_CHANGE });
      continue;
    }
    const args = action.args as Record<string, unknown>;
    const removed = args.op === 'delete' ? items(draft).find((item) => item.key === args.itemKey) : undefined;
    const [done] = result.applied;
    const note = [removed && `deleted "${removed.label || removed.key}"`, done?.note].filter(Boolean).join('; ');
    applied.push({ id: action.id, tool: removed ? DELETE_TOOL : action.tool, note: note || undefined });
    draft = result.draft;
  }
  const before = new Map(items(now).map((item) => [item.key, item]));
  const after = new Map(items(draft).map((item) => [item.key, item]));
  const changedKeys = items(draft)
    .filter((item) => !same(before.get(item.key), item))
    .map((item) => item.key);
  if (!same(now.incident, draft.incident)) changedKeys.unshift(INCIDENT_HIGHLIGHT_KEY);
  const removedKeys = [...before.keys()].filter((key) => !after.has(key));
  return { draft, applied, skipped, changedKeys, removedKeys };
}
