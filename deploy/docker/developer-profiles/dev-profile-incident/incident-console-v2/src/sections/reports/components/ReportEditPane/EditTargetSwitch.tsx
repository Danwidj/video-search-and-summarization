// SPDX-License-Identifier: Apache-2.0

'use client';

import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';

export type EditTarget = 'camera' | 'overview';

/**
 * Chooses what edit mode edits: the selected camera's report or the incident overview. A save writes one of them,
 * so while the draft has unsaved changes the other choice is off until they are saved or reverted.
 */
export function EditTargetSwitch({
  cameraName,
  locked,
  onChange,
  target,
}: {
  cameraName: string;
  locked: boolean;
  onChange: (target: EditTarget) => void;
  target: EditTarget;
}) {
  return (
    <div className="mt-4 flex flex-wrap items-center gap-x-3 gap-y-1.5" data-testid="edit-target">
      <span className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink-caption">Editing</span>
      <ToggleGroup
        aria-label="What to edit"
        onValueChange={(value) => {
          if (value === 'camera' || value === 'overview') onChange(value);
        }}
        size="sm"
        type="single"
        value={target}
        variant="outline"
      >
        <ToggleGroupItem className="text-xs font-semibold" disabled={locked && target !== 'overview'} value="overview">
          Overview
        </ToggleGroupItem>
        <ToggleGroupItem
          className="max-w-56 truncate text-xs font-semibold"
          disabled={locked && target !== 'camera'}
          title={cameraName}
          value="camera"
        >
          {cameraName}
        </ToggleGroupItem>
      </ToggleGroup>
      {locked && <span className="text-[11px] text-ink-caption">Save or revert your changes to switch.</span>}
    </div>
  );
}
