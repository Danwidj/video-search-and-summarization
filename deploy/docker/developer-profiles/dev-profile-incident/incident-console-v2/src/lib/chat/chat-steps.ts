// SPDX-License-Identifier: Apache-2.0

// Pure helpers for the expandable "What I did" chat steps view.

/** Summary label shown in the trigger badge (e.g. "2 tools · 1 applied · 1 skipped"). */
export function summaryLabel(stepCount: number, appliedCount: number, skippedCount: number): string {
  const parts: string[] = [];
  if (stepCount > 0) {
    parts.push(`${stepCount} ${stepCount === 1 ? 'tool' : 'tools'}`);
  }
  if (appliedCount > 0) {
    parts.push(`${appliedCount} applied`);
  }
  if (skippedCount > 0) {
    parts.push(`${skippedCount} skipped`);
  }
  return parts.join(' · ');
}

/** Whether a chat message holds any steps, edit actions or new-evidence rows worth expanding. */
export function hasStepsOrActions(message: { steps?: unknown[]; applied?: unknown[]; skipped?: unknown[]; evidence?: unknown[] }): boolean {
  return (
    (Array.isArray(message.steps) && message.steps.length > 0) ||
    (Array.isArray(message.applied) && message.applied.length > 0) ||
    (Array.isArray(message.skipped) && message.skipped.length > 0) ||
    (Array.isArray(message.evidence) && message.evidence.length > 0)
  );
}
