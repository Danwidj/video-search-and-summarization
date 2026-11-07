// SPDX-License-Identifier: Apache-2.0

// Pure rules for evidence changes the chat editor proposes for an existing item (re-track, set image). A proposal sits beside
// the item and changes nothing about it until the reviewer confirms it; confirming runs the same functions the buttons use
// (retrackDraftItem, setImagePick), so Save, the only point where crops are cut, sees an ordinary reviewer change.

import { retrackDraftItem } from '@/lib/evidence/box-tool';
import { setImagePick } from '@/lib/evidence/image-pick';
import { draftItemName } from '@/lib/reports/compare';
import type { EditDraft } from '@/modules/reports/domain/edit-draft';
import type { EvidenceProposal, ImagePick, ReviewerTrack } from '@/modules/reports/domain/reviewer-item';
import type { EvidenceItemType } from '@/modules/reports/domain/revision';

type DraftItem = EditDraft['entities'][number] | EditDraft['instruments'][number] | EditDraft['assets'][number];

/** The kind and item for a draft key, or null when no item has it. */
export function findDraftItem(draft: EditDraft, key: string): { kind: EvidenceItemType; item: DraftItem } | null {
  const entity = draft.entities.find((item) => item.key === key);
  if (entity) return { kind: 'entity', item: entity };
  const instrument = draft.instruments.find((item) => item.key === key);
  if (instrument) return { kind: 'instrument', item: instrument };
  const asset = draft.assets.find((item) => item.key === key);
  return asset ? { kind: 'asset', item: asset } : null;
}

const withProposal = (draft: EditDraft, key: string, proposal: EvidenceProposal | null): EditDraft => {
  const patch = <T extends { key: string }>(items: T[]): T[] => items.map((item) => (item.key === key ? { ...item, proposal } : item));
  return { ...draft, entities: patch(draft.entities), instruments: patch(draft.instruments), assets: patch(draft.assets) };
};

/** The draft with an unconfirmed proposal on an item (replacing any earlier one); the item itself is untouched. */
export function proposeEvidence(draft: EditDraft, key: string, proposal: EvidenceProposal): EditDraft {
  if (!findDraftItem(draft, key)) throw new Error(`no item with key "${key}"`);
  return withProposal(draft, key, proposal);
}

/** The draft with an item's proposal dropped, the item exactly as it was. */
export function dismissProposal(draft: EditDraft, key: string): EditDraft {
  return withProposal(draft, key, null);
}

/** The proposal applied through the same path as a hand edit, then cleared. An item with no proposal is returned as it is. */
export function confirmProposal(draft: EditDraft, key: string): EditDraft {
  const found = findDraftItem(draft, key);
  if (!found?.item.proposal) return draft;
  const { kind, item } = found;
  const proposal = item.proposal as EvidenceProposal;
  const confirmed =
    proposal.kind === 'set_image'
      ? setImagePick(draft, kind, key, proposal.pick)
      : retrackDraftItem(draft, kind, key, {
          itemType: kind,
          name: draftItemName(item),
          description: item.description,
          aiProposal: null,
          track: proposal.track,
        });
  return withProposal(confirmed, key, null);
}

/** The draft with an adjusted pick (Set image dialog) or track (track editor) confirmed in place of the proposal. */
export function confirmAdjusted(draft: EditDraft, key: string, adjusted: ImagePick | ReviewerTrack): EditDraft {
  const found = findDraftItem(draft, key);
  const proposal = found?.item.proposal;
  if (!found || !proposal) return draft;
  const next: EvidenceProposal =
    proposal.kind === 'set_image' ? { ...proposal, pick: adjusted as ImagePick } : { ...proposal, track: adjusted as ReviewerTrack };
  return confirmProposal(withProposal(draft, key, next), key);
}

/** How many items still wait on the reviewer. */
export function pendingProposalCount(draft: EditDraft): number {
  return [...draft.entities, ...draft.instruments, ...draft.assets].filter((item) => item.proposal).length;
}

const clock = (seconds: number) => `${seconds.toFixed(1)} s`;

/** One plain line about a proposal for its card, including where a re-track lost the item. */
export function describeProposal(proposal: EvidenceProposal): string {
  if (proposal.kind === 'set_image') return `Set the image to the frame at ${clock(proposal.pick.seconds)}.`;
  const { track } = proposal;
  const span = `${clock(track.span[0])} to ${clock(track.span[1])}`;
  if (!track.partial) return `Re-track from ${span}.`;
  return `Re-track from ${span}; the tracker lost the item${track.lostAt === null ? '' : ` at ${clock(track.lostAt)}`}.`;
}
