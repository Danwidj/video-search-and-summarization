// SPDX-License-Identifier: Apache-2.0
'use client';

import { Badge } from '@/components/ui/badge';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { ToggleGroup, ToggleGroupItem } from '@/components/ui/toggle-group';
import type { CameraOption } from '@/lib/reports/cameras';

/** Picks which camera feeds the player, the evidence frames and the report fields: toggles from sm, a select below. */
export function CameraSwitcher({
  options,
  value,
  onChange,
}: {
  options: CameraOption[];
  value: string | null;
  onChange: (video: string) => void;
}) {
  return (
    <div
      className="flex flex-wrap items-center gap-x-3 gap-y-2 border-b border-border bg-muted/40 px-5 py-2.5 sm:px-8"
      data-testid="camera-switcher"
    >
      <span className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-muted-foreground">Camera</span>
      <ToggleGroup
        aria-label="Camera"
        className="hidden min-w-0 flex-wrap sm:flex"
        onValueChange={(next) => next && onChange(next)}
        size="sm"
        spacing={1}
        type="single"
        value={value ?? ''}
        variant="outline"
      >
        {options.map((option) => (
          <ToggleGroupItem
            className="text-xs font-semibold"
            disabled={!option.selectable}
            key={option.video}
            title={option.reason ?? undefined}
            value={option.video}
          >
            {option.video}
            {!option.selectable && (
              <Badge className="ml-1.5 px-1.5 text-[10px]" variant="secondary">
                {option.reason?.includes('removed') ? 'removed' : 'unavailable'}
              </Badge>
            )}
          </ToggleGroupItem>
        ))}
      </ToggleGroup>
      <div className="min-w-0 flex-1 sm:hidden">
        <Select onValueChange={onChange} value={value ?? undefined}>
          <SelectTrigger aria-label="Camera" className="w-full" size="sm">
            <SelectValue placeholder="No camera can be shown" />
          </SelectTrigger>
          <SelectContent>
            {options.map((option) => (
              <SelectItem disabled={!option.selectable} key={option.video} value={option.video}>
                {option.video}
                {option.reason ? ` (${option.reason.includes('removed') ? 'removed' : 'unavailable'})` : ''}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
    </div>
  );
}
