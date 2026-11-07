// SPDX-License-Identifier: Apache-2.0

/**
 * The Markdown of one version of an incident report, in the order the captain set: an overview table, the summary, the
 * severity rationale, the evidence (people, instruments, assets; each with its crop on the left), the timeline table and the
 * version history. The agent turns it into the PDF (A4, the stylesheet and the running header and footer), so this file
 * decides the content and returns the header and footer text beside it. Image URLs are the signed evidence URLs the report
 * already holds: the agent fetches them, and nothing here logs them.
 */

import type { ReportView, StructuredAsset, StructuredEntity, StructuredInstrument } from '@/modules/reports/domain/report-view';

export interface ReportPdfOptions {
  includeImages: boolean;
  includeTimeline: boolean;
  includeHistory: boolean;
}

export interface ReportPdfHistoryRow {
  revisionNo: number;
  kind: 'ai' | 'human';
  note: string | null;
  createdAt: string | null;
}

export interface ReportPdfImage {
  alt: string;
  url: string;
}

export interface ReportPdfMarkdown {
  markdown: string;
  /** The running header (every page): "Incident report" and the title. */
  runningHeader: string;
  /** The footer (every page, with the page numbers added by the PDF step): version, generated time in SGT. */
  footer: string;
  images: ReportPdfImage[];
}

/** The dialog's defaults: evidence images and the timeline on, the version history off. */
export const DEFAULT_REPORT_PDF_OPTIONS: ReportPdfOptions = { includeImages: true, includeTimeline: true, includeHistory: false };

/** m:ss, or h:mm:ss from an hour; "Not recorded" for a missing time. */
export function clockText(seconds: number | null | undefined): string {
  if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return 'Not recorded';
  const total = Math.max(0, Math.floor(seconds));
  const hours = Math.floor(total / 3600);
  const minutes = Math.floor((total % 3600) / 60);
  const secs = String(total % 60).padStart(2, '0');
  return hours > 0 ? `${hours}:${String(minutes).padStart(2, '0')}:${secs}` : `${minutes}:${secs}`;
}

/** A stored time: naive UTC as the schema writes it, or a value that carries its own zone. */
export function parseNaiveUtc(value: string | null | undefined): Date | null {
  if (typeof value !== 'string' || !value.trim()) return null;
  const text = value.trim();
  const iso = /^\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2}(\.\d+)?)?$/.test(text) ? `${text.replace(' ', 'T')}Z` : text;
  const date = new Date(iso);
  return Number.isNaN(date.getTime()) ? null : date;
}

/** A stored time (naive UTC) as "8 Nov 2026, 11:15 SGT". */
export function sgtText(value: string | null | undefined): string {
  const date = parseNaiveUtc(value);
  if (!date) return 'Not recorded';
  const parts = new Intl.DateTimeFormat('en-GB', {
    timeZone: 'Asia/Singapore',
    day: 'numeric',
    month: 'short',
    year: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).formatToParts(date);
  const part = (type: Intl.DateTimeFormatPartTypes) => parts.find((p) => p.type === type)?.value ?? '';
  return `${part('day')} ${part('month')} ${part('year')}, ${part('hour')}:${part('minute')} SGT`;
}

/** A Markdown table cell: one line, with pipes escaped. */
export function cell(value: string | number | null | undefined): string {
  const text = value === null || value === undefined || value === '' ? '-' : String(value);
  return text.replace(/\|/g, '\\|').replace(/\r?\n/g, ' ').trim();
}

const versionKind = (kind: 'ai' | 'human') => (kind === 'human' ? 'Human' : 'Model');

/** The item's evidence number across the whole report: E1 for the first item of People, then Instruments, then Assets. */
interface Evidence {
  id: string;
  group: 'People' | 'Instruments' | 'Assets';
  name: string;
  description: string;
  timestampSeconds: number | null;
  firstSeenSeconds?: number | null;
  lastSeenSeconds?: number | null;
  holder?: string;
  holds?: string;
  imageUrl: string | null;
}

function evidenceList(view: ReportView): Evidence[] {
  const people = view.structured.entities;
  const instruments = view.structured.instruments;
  const assets = view.structured.assets;
  const byEntity = new Map(people.map((entity) => [entity.entityId, entity] as const));
  const holdsOf = (entityId: string) =>
    instruments
      .filter((instrument) => instrument.entityId === entityId)
      .map((instrument) => instrument.name)
      .join(', ');
  const items: Omit<Evidence, 'id'>[] = [
    ...people.map((entity: StructuredEntity) => ({
      group: 'People' as const,
      name: entity.label || entity.type,
      description: entity.description,
      timestampSeconds: entity.timestampSeconds,
      firstSeenSeconds: entity.firstSeenSeconds,
      lastSeenSeconds: entity.lastSeenSeconds,
      holds: holdsOf(entity.entityId) || undefined,
      imageUrl: entity.evidence?.imageUrl ?? null,
    })),
    ...instruments.map((instrument: StructuredInstrument) => ({
      group: 'Instruments' as const,
      name: instrument.name,
      description: instrument.description,
      timestampSeconds: instrument.timestampSeconds,
      holder: instrument.entityId ? (byEntity.get(instrument.entityId)?.label ?? undefined) : undefined,
      imageUrl: instrument.evidence?.imageUrl ?? null,
    })),
    ...assets.map((asset: StructuredAsset) => ({
      group: 'Assets' as const,
      name: asset.name,
      description: asset.description,
      timestampSeconds: asset.timestampSeconds,
      imageUrl: asset.evidence?.imageUrl ?? null,
    })),
  ];
  return items.map((item, index) => ({ ...item, id: `E${index + 1}` }));
}

function detailLines(item: Evidence): string {
  const lines = [`**${item.id}** · ${cell(item.name)}`, cell(item.description)];
  lines.push(`Most visible at ${clockText(item.timestampSeconds)}`);
  if (item.firstSeenSeconds !== undefined && item.firstSeenSeconds !== null) {
    lines.push(`Seen from ${clockText(item.firstSeenSeconds)} to ${clockText(item.lastSeenSeconds)}`);
  }
  if (item.holder) lines.push(`Held by ${cell(item.holder)}`);
  if (item.holds) lines.push(`Holds ${cell(item.holds)}`);
  return lines.join('<br>');
}

export function buildReportMarkdown(
  view: ReportView,
  options: ReportPdfOptions = DEFAULT_REPORT_PDF_OPTIONS,
  history: ReportPdfHistoryRow[] = [],
  generatedAt: string = new Date().toISOString(),
): ReportPdfMarkdown {
  const { incident } = view.structured;
  const title = (incident.title?.trim() || (incident.type ? `${incident.type} report` : 'Incident report')).replace(/\r?\n/g, ' ');
  const versionLabel = `v${view.revision.revisionNo}`;
  const state = view.official.isOfficial ? 'Official' : versionKind(view.revision.kind);
  const images: ReportPdfImage[] = [];
  const lines: string[] = [];

  lines.push(`# ${title}`, '');
  lines.push('## Overview', '', '| Field | Value |', '|-------|-------|');
  const overview: Array<[string, string]> = [
    ['Title', title],
    ['Incident type', cell(incident.type ?? 'Unclassified')],
    ['Severity', incident.severityLevel === null ? '-' : `${incident.severityLevel}/5`],
    [
      'Time range in the video',
      incident.startSeconds === null ? '-' : `${clockText(incident.startSeconds)} to ${clockText(incident.endSeconds)}`,
    ],
    ['Video', `${cell(view.videoId)} (${clockText(incident.duration)})`],
    ['Version', `${versionLabel}, ${state}`],
    ['Saved by and when', `${cell(view.revision.createdBy ?? 'Model run')}, ${sgtText(view.revision.createdAt)}`],
  ];
  for (const [field, value] of overview) lines.push(`| **${field}** | ${value} |`);
  lines.push('');

  lines.push('## Summary', '', cell(incident.description ?? 'No summary was recorded.'), '');
  lines.push('## Severity rationale', '', cell(incident.severityReason ?? 'No severity rationale was recorded.'), '');

  const evidence = evidenceList(view);
  if (evidence.length > 0) lines.push('## Evidence', '');
  for (const group of ['People', 'Instruments', 'Assets'] as const) {
    const items = evidence.filter((item) => item.group === group);
    if (items.length === 0) continue;
    lines.push(`### ${group}`, '');
    for (const item of items) {
      const url = item.imageUrl;
      if (options.includeImages && url) {
        const alt = `${item.id} ${item.name}, snapshot at ${clockText(item.timestampSeconds)}`;
        images.push({ alt, url });
        lines.push('| Image | Item |', '|-------|------|', `| ![${alt}](${url}) | ${detailLines(item)} |`, '');
      } else {
        lines.push('| Item |', '|------|', `| ${detailLines(item)} |`, '');
      }
    }
  }

  if (options.includeTimeline) {
    const rows = [...evidence].sort((a, b) => (a.timestampSeconds ?? Infinity) - (b.timestampSeconds ?? Infinity));
    if (rows.length > 0) {
      lines.push('## Timeline', '', '| Time | Item | What happens |', '|------|------|--------------|');
      for (const item of rows) {
        lines.push(`| ${clockText(item.timestampSeconds)} | ${item.id} ${cell(item.name)} | ${cell(item.description)} |`);
      }
      lines.push('');
    }
  }

  if (options.includeHistory && history.length > 0) {
    lines.push('## Version history', '', '| Version | Kind | Date | Note |', '|---------|------|------|------|');
    for (const row of history) {
      const note = row.kind === 'ai' ? 'Model run' : (row.note ?? '-');
      lines.push(`| v${row.revisionNo} | ${versionKind(row.kind)} | ${sgtText(row.createdAt)} | ${cell(note)} |`);
    }
    lines.push('');
  }

  return {
    markdown: `${lines.join('\n').trimEnd()}\n`,
    runningHeader: `Incident report · ${title}`,
    footer: `${versionLabel} · ${state} · generated ${sgtText(generatedAt)}`,
    images,
  };
}

export type ReportPdfFormat = 'pdf' | 'markdown';

export interface ReportPdfRequest {
  format: ReportPdfFormat;
  /** The version to make the report from; the current one when absent. */
  revisionId: number | null;
  options: ReportPdfOptions;
}

/** Reads the route's body: an unknown format or a bad version is refused; each option is a boolean, defaults otherwise. */
export function parseReportPdfRequest(body: unknown): ReportPdfRequest | { error: string } {
  if (!body || typeof body !== 'object') return { error: 'The request body must be a JSON object' };
  const input = body as Record<string, unknown>;
  const format = input.format ?? 'pdf';
  if (format !== 'pdf' && format !== 'markdown') return { error: 'The format must be pdf or markdown' };
  const revision = input.revisionId ?? null;
  if (revision !== null && (typeof revision !== 'number' || !Number.isSafeInteger(revision) || revision < 1)) {
    return { error: 'The version must be a positive whole number' };
  }
  const given = (input.options && typeof input.options === 'object' ? input.options : {}) as Record<string, unknown>;
  const flag = (key: keyof ReportPdfOptions) =>
    typeof given[key] === 'boolean' ? (given[key] as boolean) : DEFAULT_REPORT_PDF_OPTIONS[key];
  return {
    format,
    revisionId: revision,
    options: { includeImages: flag('includeImages'), includeTimeline: flag('includeTimeline'), includeHistory: flag('includeHistory') },
  };
}
