// SPDX-License-Identifier: Apache-2.0

// The Find incidents tab's filters. The URL is the filter state: parsing a
// query string and writing it back are inverse, so dashboard links, shared
// links, refresh and back/forward all land on the same list. Pure, so tests
// can import it.

export type IncidentSort = 'newest' | 'oldest';

export interface IncidentFilters {
  search: string;
  type: string;
  /** '', a band (low, medium, high) or one level (1 to 5). */
  severity: string;
  /** Only the official version of each incident. */
  official: boolean;
  /** Version kind: '', ai or human. */
  kind: string;
  entity: string;
  instrument: string;
  asset: string;
  entityType: string;
  exact: boolean;
  after: string;
  before: string;
  fromTime: string;
  toTime: string;
  day: string;
  sort: IncidentSort;
  page: number;
}

export const EMPTY_FILTERS: IncidentFilters = {
  search: '',
  type: '',
  severity: '',
  official: false,
  kind: '',
  entity: '',
  instrument: '',
  asset: '',
  entityType: '',
  exact: false,
  after: '',
  before: '',
  fromTime: '',
  toTime: '',
  day: '',
  sort: 'newest',
  page: 1,
};

/** Query keys whose presence means the URL carries filters to apply on arrival. */
export const FILTER_KEYS = [
  'search',
  'type',
  'severity',
  'kind',
  'entity',
  'instrument',
  'asset',
  'scope',
  'entityType',
  'match',
  'after',
  'before',
  'fromTime',
  'toTime',
  'day',
  'sort',
  'page',
];

export function parseFilters(query: URLSearchParams): IncidentFilters {
  const get = (key: string) => query.get(key) ?? '';
  const page = Number(get('page'));
  return {
    search: get('search'),
    type: get('type') === 'all' ? '' : get('type'),
    severity: get('severity') === 'all' ? '' : get('severity'),
    official: get('scope') === 'official',
    kind: get('kind') === 'all' ? '' : get('kind'),
    entity: get('entity'),
    instrument: get('instrument'),
    asset: get('asset'),
    entityType: get('entityType'),
    exact: get('match') === 'exact',
    after: get('after'),
    before: get('before'),
    fromTime: get('fromTime'),
    toTime: get('toTime'),
    day: get('day'),
    sort: get('sort') === 'oldest' ? 'oldest' : 'newest',
    page: Number.isInteger(page) && page > 0 ? page : 1,
  };
}

/** The /api/reports and URL query for a set of filters; defaults are left out. */
export function filterParams(filters: IncidentFilters): URLSearchParams {
  const p = new URLSearchParams();
  const set = (key: string, value: string) => {
    if (value.trim()) p.set(key, value.trim());
  };
  set('search', filters.search);
  set('type', filters.type);
  set('severity', filters.severity);
  set('kind', filters.kind);
  set('entity', filters.entity);
  set('instrument', filters.instrument);
  set('asset', filters.asset);
  set('entityType', filters.entityType);
  if (filters.official) p.set('scope', 'official');
  if (filters.exact) p.set('match', 'exact');
  set('after', filters.after);
  set('before', filters.before);
  set('fromTime', filters.fromTime);
  set('toTime', filters.toTime);
  set('day', filters.day);
  if (filters.sort !== 'newest') p.set('sort', filters.sort);
  if (filters.page > 1) p.set('page', String(filters.page));
  return p;
}

export interface ActiveFilter {
  key: string;
  label: string;
  /** What clearing this chip resets. */
  clear: Partial<IncidentFilters>;
}

const SEVERITY_LABEL: Record<string, string> = { low: 'Low (1-2)', medium: 'Medium (3)', high: 'High (4-5)' };

/** One removable chip per active filter (the sort and page are not filters). */
export function activeFilters(f: IncidentFilters): ActiveFilter[] {
  const chips: ActiveFilter[] = [];
  if (f.search.trim()) chips.push({ key: 'search', label: `Text: ${f.search.trim()}`, clear: { search: '' } });
  if (f.type) chips.push({ key: 'type', label: `Type: ${f.type}`, clear: { type: '' } });
  if (f.official) chips.push({ key: 'official', label: 'Official only', clear: { official: false } });
  if (f.severity) chips.push({ key: 'severity', label: `Severity: ${SEVERITY_LABEL[f.severity] ?? f.severity}`, clear: { severity: '' } });
  if (f.kind) chips.push({ key: 'kind', label: f.kind === 'human' ? 'Human versions' : 'AI versions', clear: { kind: '' } });
  if (f.entityType) chips.push({ key: 'entityType', label: `Entity type: ${f.entityType}`, clear: { entityType: '' } });
  if (f.entity) chips.push({ key: 'entity', label: `Entity: ${f.entity}`, clear: { entity: '' } });
  if (f.instrument) chips.push({ key: 'instrument', label: `Instrument: ${f.instrument}`, clear: { instrument: '' } });
  if (f.asset) chips.push({ key: 'asset', label: `Asset: ${f.asset}`, clear: { asset: '' } });
  if (f.after || f.before)
    chips.push({
      key: 'date',
      label: `Added: ${f.after.slice(0, 10) || 'any'} to ${f.before.slice(0, 10) || 'now'}`,
      clear: { after: '', before: '' },
    });
  if (f.fromTime || f.toTime)
    chips.push({ key: 'time', label: `Time: ${f.fromTime || '00:00'} to ${f.toTime || '24:00'}`, clear: { fromTime: '', toTime: '' } });
  if (f.day)
    chips.push({
      key: 'day',
      label: `Weekday: ${['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'][Number(f.day)] ?? f.day}`,
      clear: { day: '' },
    });
  return chips;
}

export type DatePreset = 'any' | 'today' | '7d' | '30d';

const localDate = (date: Date) =>
  `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, '0')}-${String(date.getDate()).padStart(2, '0')}`;

/** The `after` value a preset stands for, in the viewer's local calendar. */
export function presetAfter(preset: DatePreset, now = new Date()): string {
  if (preset === 'any') return '';
  const back = preset === 'today' ? 0 : preset === '7d' ? 6 : 29;
  return `${localDate(new Date(now.getFullYear(), now.getMonth(), now.getDate() - back))}T00:00:00`;
}
