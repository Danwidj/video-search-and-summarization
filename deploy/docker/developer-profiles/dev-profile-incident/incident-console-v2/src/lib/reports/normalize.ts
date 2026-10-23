// SPDX-License-Identifier: Apache-2.0

// Value normalisation for the relational projection, which holds two
// generations of data: incident-contract-v2 runs (integer seconds as text,
// contract enums) and legacy console runs ("M:SS" / "H:MM:SS" strings,
// fighting/animal types, 'person' entities). Display-only: stored rows are
// never rewritten here.

const LEGACY_INCIDENT_TYPES: Record<string, string> = {
  fighting: 'assault',
  animal: 'animal attack',
};

const LEGACY_ENTITY_TYPES: Record<string, string> = {
  person: 'human',
};

/** Seconds from an integer, integer text, "M:SS" or "H:MM:SS"; null when absent or unparseable. */
export function parseTimestamp(value: unknown): number | null {
  if (typeof value === 'number') return Number.isFinite(value) && value >= 0 ? Math.floor(value) : null;
  if (typeof value !== 'string') return null;
  const text = value.trim();
  if (/^\d+$/.test(text)) return Number(text);
  const match = /^(\d+):(\d{1,2})(?::(\d{1,2}))?$/.exec(text);
  if (!match) return null;
  const [first, second, third] = [match[1], match[2], match[3]].map((part) => (part === undefined ? undefined : Number(part)));
  return third === undefined ? first! * 60 + second! : first! * 3600 + second! * 60 + third;
}

export function formatClock(seconds: number): string {
  const whole = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(whole / 3600);
  const minutes = Math.floor((whole % 3600) / 60);
  const rest = String(whole % 60).padStart(2, '0');
  return hours ? `${hours}:${String(minutes).padStart(2, '0')}:${rest}` : `${minutes}:${rest}`;
}

export function canonicalIncidentType(value: unknown): string | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  const text = value.trim();
  return LEGACY_INCIDENT_TYPES[text.toLowerCase()] ?? text;
}

export function canonicalEntityType(value: unknown): string {
  if (typeof value !== 'string' || !value.trim()) return 'unknown';
  const text = value.trim().toLowerCase();
  return LEGACY_ENTITY_TYPES[text] ?? text;
}
