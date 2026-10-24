// SPDX-License-Identifier: Apache-2.0

export type Filters = { type: string; severity: string; day: string; hour: string };
export type Range = { after: string; before: string } | null;
export type LinkFilters = Partial<Filters> & { kind?: string; entityType?: string; instrument?: string; asset?: string };
/** The library-page URL whose total equals the clicked number: official scope, the same period and filters, exact names. */
export function href(f: LinkFilters, range: Range) {
  const p = new URLSearchParams({ scope: 'official' });
  if (range) {
    p.set('after', range.after);
    p.set('before', range.before);
  }
  if (f.type) p.set('type', f.type);
  if (f.severity) p.set('severity', f.severity);
  if (f.kind) p.set('kind', f.kind);
  if (f.day) p.set('day', f.day);
  if (f.entityType) p.set('entityType', f.entityType);
  if (f.instrument) p.set('instrument', f.instrument);
  if (f.asset) p.set('asset', f.asset);
  if (f.instrument || f.asset) p.set('match', 'exact');
  if (f.hour) {
    p.set('fromTime', `${f.hour.padStart(2, '0')}:00`);
    p.set('toTime', `${f.hour.padStart(2, '0')}:59:59.999`);
  }
  return `/library?${p}`;
}
