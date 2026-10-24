// SPDX-License-Identifier: Apache-2.0

'use client';

import { useState } from 'react';

import { EvidenceFrame } from '@/sections/evidence/components/EvidenceFrame';
import { EvidenceFramePicker } from '@/sections/evidence/components/EvidenceFramePicker';
import type { FramePick } from '@/lib/evidence/frame-picker';
import {
  deleteDraftItem,
  draftItemName,
  isDraftEntity,
  isDraftInstrument,
  isSavedEntity,
  isSavedInstrument,
  pairReport,
  revertBlocked,
  revertDraftItem,
  rowDiffers,
  savedItemId,
  savedItemName,
  type PairRow,
  type Structured,
} from '@/lib/reports/compare';
import { EDITABLE_ENTITY_TYPES, EDITABLE_INCIDENT_TYPES, type EditDraft } from '@/modules/reports/domain/edit-draft';
import { formatClock } from '@/modules/reports/domain/normalize';

function severityStyle(level: number | null): string {
  if (level !== null && level >= 4) return 'bg-[#ffe8df] text-[#9b3518]';
  if (level === 3) return 'bg-[#fff1c7] text-[#765300]';
  return 'bg-signal/15 text-moss';
}

const capitalize = (value: string | null) => (value ? value[0].toUpperCase() + value.slice(1) : 'Unclassified');
const clock = (seconds: number | null) => (seconds === null ? '—' : formatClock(seconds));
const rowKey = (row: PairRow) => `${row.kind}-${row.b?.key ?? (row.a ? savedItemId(row.a) : '')}`;

/**
 * Edit mode's pane: the version the draft started from (A) on the left and the
 * editable draft (B) on the right, field by field and evidence row by row. A
 * is never editable. Delete removes a draft item (and the instruments an entity
 * holds); Revert puts an edited or deleted item back exactly as A has it.
 * Replace image picks a frame from the video and a rectangle on it; the crop
 * and its frame second go into the draft item. Add evidence is not part of
 * this pane yet.
 */
export function ReportEditPane({
  a,
  aRevisionNo,
  baseRevisionNo,
  draft,
  title,
  videoId,
  videoSrc,
  onChange,
  onSeek,
}: {
  a: Structured | null;
  aRevisionNo: number;
  baseRevisionNo: number;
  draft: EditDraft;
  title: string;
  videoId: string;
  videoSrc: string;
  onChange: (draft: EditDraft) => void;
  onSeek: (seconds: number) => void;
}) {
  const [picking, setPicking] = useState<PairRow['b'] | null>(null);
  const pairing = pairReport(a, draft);
  const patchIncident = (patch: Partial<EditDraft['incident']>) => onChange({ ...draft, incident: { ...draft.incident, ...patch } });
  const patchEntity = (key: string, patch: Partial<EditDraft['entities'][number]>) =>
    onChange({ ...draft, entities: draft.entities.map((entity) => (entity.key === key ? { ...entity, ...patch } : entity)) });
  const patchInstrument = (key: string, patch: Partial<EditDraft['instruments'][number]>) =>
    onChange({
      ...draft,
      instruments: draft.instruments.map((instrument) => (instrument.key === key ? { ...instrument, ...patch } : instrument)),
    });
  const patchAsset = (key: string, patch: Partial<EditDraft['assets'][number]>) =>
    onChange({ ...draft, assets: draft.assets.map((asset) => (asset.key === key ? { ...asset, ...patch } : asset)) });
  const remove = (row: PairRow) => {
    if (row.b) onChange(deleteDraftItem(draft, row.kind, row.b.key));
  };
  const revert = (row: PairRow) => {
    if (a) onChange(revertDraftItem(draft, a, row));
  };
  const replace = (row: PairRow) => {
    if (row.b) setPicking(row.b);
  };
  const applyPick = (item: NonNullable<PairRow['b']>, pick: FramePick) => {
    if (item.pendingImage && item.imageUrl) URL.revokeObjectURL(item.imageUrl);
    const frame = {
      timestampSeconds: pick.timestampSeconds,
      image: null,
      imageUrl: pick.previewUrl,
      pendingImage: pick.blob,
      imageTimestampSeconds: pick.timestampSeconds,
      imageBox: pick.box,
    };
    if (isDraftEntity(item)) patchEntity(item.key, frame);
    else if (isDraftInstrument(item)) patchInstrument(item.key, frame);
    else patchAsset(item.key, frame);
    setPicking(null);
  };
  const holderOptions = draft.entities.map((entity, index) => ({ key: entity.key, label: `${index + 1}. ${entity.label || entity.type}` }));
  const draftHolder = (instrument: EditDraft['instruments'][number]) => {
    if (!instrument.holderKey) return 'unknown';
    const holder = draft.entities.find((entity) => entity.key === instrument.holderKey);
    return holder ? holder.label || holder.type : 'unknown';
  };
  const savedHolder = (instrument: PairRow['a']) => {
    if (!instrument || !isSavedInstrument(instrument) || !instrument.entityId) return 'unknown';
    const holder = a?.entities.find((entity) => entity.entityId === instrument.entityId);
    return holder ? holder.label || holder.type : instrument.entityId;
  };
  const inherited = (row: PairRow) => {
    const entity = row.a;
    if (!entity || !isSavedEntity(entity) || !a) return '';
    const names = a.instruments.filter((instrument) => instrument.entityId === entity.entityId).map((instrument) => instrument.name);
    return names.length ? `Holds ${names.join(', ')}` : 'Holds nothing visible';
  };

  return (
    <div className="px-5 pb-6 sm:px-8" data-testid="report-edit-pane">
      <div
        className="mt-4 grid gap-2 rounded-2xl border border-ink/10 bg-white/95 px-3 py-2 text-xs sm:grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)] sm:gap-4"
        data-testid="compare-header"
      >
        <span className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink/45">Compare</span>
        <div className="min-w-0 rounded-xl bg-[#fdf0ea] px-3 py-2" data-side="A">
          <span className="font-mono text-[10.5px] font-bold uppercase tracking-wide text-[#9b3518]">A</span> <b>v{aRevisionNo}</b>{' '}
          <span className="text-ink/50">read-only</span>
        </div>
        <div className="min-w-0 rounded-xl bg-[#eef5e6] px-3 py-2" data-side="B">
          <span className="font-mono text-[10.5px] font-bold uppercase tracking-wide text-moss">B</span> <b>Draft</b>{' '}
          <span className="text-ink/50">from v{baseRevisionNo} · editable</span>
        </div>
      </div>

      <section className="mt-5" data-testid="report-fields-compare">
        <h3 className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink/45">Report fields</h3>
        <dl className="m-0">
          <PairField
            label="Title"
            left={title}
            right={
              <span className="text-ink/60">
                {title} <span className="text-[11px] text-ink/40">(model-generated)</span>
              </span>
            }
          />
          <PairField
            label="Incident type"
            left={capitalize(a?.incident.type ?? null)}
            right={
              <select
                aria-label="Draft incident type"
                className="control"
                onChange={(event) => patchIncident({ type: event.target.value || null })}
                value={draft.incident.type ?? ''}
              >
                <option value="">Choose…</option>
                {EDITABLE_INCIDENT_TYPES.map((type) => (
                  <option key={type} value={type}>
                    {capitalize(type)}
                  </option>
                ))}
              </select>
            }
          />
          <PairField
            label="Severity"
            left={
              <span className={`rounded-full px-3 py-0.5 text-xs font-bold ${severityStyle(a?.incident.severityLevel ?? null)}`}>
                {a?.incident.severityLevel ?? '—'}/5
              </span>
            }
            right={
              <select
                aria-label="Draft severity"
                className={`control font-bold ${severityStyle(draft.incident.severity_level)}`}
                onChange={(event) => patchIncident({ severity_level: event.target.value ? Number(event.target.value) : null })}
                value={draft.incident.severity_level ?? ''}
              >
                <option value="">Choose…</option>
                {[1, 2, 3, 4, 5].map((level) => (
                  <option key={level} value={level}>
                    {level}/5
                  </option>
                ))}
              </select>
            }
          />
          <PairField
            label="Confidence"
            left={a?.incident.confidenceScore != null ? `${Math.round(a.incident.confidenceScore * 100)}%` : '—'}
            right={
              <span className="text-ink/55">
                {a?.incident.confidenceScore != null ? `${Math.round(a.incident.confidenceScore * 100)}%` : '—'}{' '}
                <span className="text-[11px] text-ink/40">set by the model</span>
              </span>
            }
          />
          <PairField
            label="Time range"
            left={a?.incident.startSeconds != null ? `${clock(a.incident.startSeconds)}–${clock(a.incident.endSeconds)}` : 'Not recorded'}
            right={
              <span className="flex flex-wrap items-center gap-1.5">
                <span className="font-mono text-[11px] text-ink/45">{clock(draft.incident.start_timestamp)}</span>
                <input
                  aria-label="Draft incident start in seconds"
                  className="control w-20"
                  inputMode="numeric"
                  min={0}
                  onChange={(event) =>
                    patchIncident({
                      start_timestamp: event.target.value === '' ? null : Math.max(0, Math.floor(Number(event.target.value))),
                    })
                  }
                  step={1}
                  type="number"
                  value={draft.incident.start_timestamp ?? ''}
                />
                <span>–</span>
                <input
                  aria-label="Draft incident end in seconds"
                  className="control w-20"
                  inputMode="numeric"
                  min={0}
                  onChange={(event) =>
                    patchIncident({ end_timestamp: event.target.value === '' ? null : Math.max(0, Math.floor(Number(event.target.value))) })
                  }
                  step={1}
                  type="number"
                  value={draft.incident.end_timestamp ?? ''}
                />
                <span className="font-mono text-[11px] text-ink/45">{clock(draft.incident.end_timestamp)}</span>
              </span>
            }
          />
          <PairField
            label="Summary"
            left={<span className="whitespace-pre-wrap">{a?.incident.description ?? 'No summary was recorded.'}</span>}
            right={
              <textarea
                aria-label="Draft summary"
                className="control min-h-[92px]"
                onChange={(event) => patchIncident({ description: event.target.value })}
                value={draft.incident.description}
              />
            }
          />
        </dl>
      </section>

      <section className="mt-6" data-testid="evidence-compare">
        <div className="flex items-center justify-between gap-3 rounded-xl border border-ink/10 bg-white/95 px-3 py-2">
          <h3 className="font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink/45">
            Evidence items · {pairing.liveCount}
          </h3>
          <span className="text-[11px] text-ink/40">A is read-only · B is your draft</span>
        </div>
        {pairing.rows.length === 0 ? (
          <p className="mt-3 rounded-xl border border-dashed border-ink/15 p-4 text-sm text-ink/45" data-testid="edit-evidence-empty">
            This version has no evidence items.
          </p>
        ) : (
          <div className="mt-3 space-y-5">
            {pairing.units.map((unit) => (
              <div data-unit={unit.kind} key={unit.kind === 'entity' ? rowKey(unit.entity!) : unit.kind}>
                {unit.kind !== 'entity' && (
                  <div className="mb-2">
                    <b className="font-mono text-[10.5px] uppercase tracking-wider text-ink/45">
                      {unit.kind === 'loose' ? 'Holder unknown' : 'Assets'}
                    </b>
                    <span className="ml-2 text-[11px] text-ink/40">
                      {unit.kind === 'loose' ? 'instruments no entity visibly holds' : 'no holder, no threat level'}
                    </span>
                  </div>
                )}
                {unit.entity && (
                  <PairRowView
                    a={a}
                    aRevisionNo={aRevisionNo}
                    draft={draft}
                    draftHolder={draftHolder}
                    holderOptions={holderOptions}
                    inherited={inherited(unit.entity)}
                    onRemove={remove}
                    onReplace={replace}
                    onRevert={revert}
                    onSeek={onSeek}
                    patchAsset={patchAsset}
                    patchEntity={patchEntity}
                    patchInstrument={patchInstrument}
                    row={unit.entity}
                    savedHolder={savedHolder}
                  />
                )}
                {unit.rows.map((row) => (
                  <div className="sm:pl-14" key={rowKey(row)}>
                    <div className="mb-1 hidden font-mono text-[10px] uppercase tracking-wider text-ink/35 sm:block">holds ↳</div>
                    <PairRowView
                      a={a}
                      aRevisionNo={aRevisionNo}
                      draft={draft}
                      draftHolder={draftHolder}
                      holderOptions={holderOptions}
                      inherited=""
                      onRemove={remove}
                      onReplace={replace}
                      onRevert={revert}
                      onSeek={onSeek}
                      patchAsset={patchAsset}
                      patchEntity={patchEntity}
                      patchInstrument={patchInstrument}
                      row={row}
                      savedHolder={savedHolder}
                    />
                  </div>
                ))}
              </div>
            ))}
          </div>
        )}
      </section>

      {picking && (
        <EvidenceFramePicker
          initialSeconds={picking.timestampSeconds ?? 0}
          label={draftItemName(picking) || 'evidence'}
          onClose={() => setPicking(null)}
          onPick={(pick) => applyPick(picking, pick)}
          range={
            isDraftEntity(picking) && picking.firstSeenSeconds !== null
              ? { first: picking.firstSeenSeconds, last: picking.lastSeenSeconds ?? picking.firstSeenSeconds }
              : null
          }
          videoId={videoId}
          videoSrc={videoSrc}
        />
      )}
    </div>
  );
}

function PairField({ label, left, right }: { label: string; left: React.ReactNode; right: React.ReactNode }) {
  return (
    <div className="grid gap-1.5 border-b border-ink/10 py-3 sm:grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)] sm:gap-4">
      <dt className="pt-0.5 font-mono text-[10.5px] font-bold uppercase tracking-[0.14em] text-ink/45">{label}</dt>
      <dd className="m-0 min-w-0 text-sm leading-6 text-ink/80">{left}</dd>
      <dd className="m-0 min-w-0 text-sm leading-6 text-ink/80">{right}</dd>
    </div>
  );
}

type PatchEntity = (key: string, patch: Partial<EditDraft['entities'][number]>) => void;
type PatchInstrument = (key: string, patch: Partial<EditDraft['instruments'][number]>) => void;
type PatchAsset = (key: string, patch: Partial<EditDraft['assets'][number]>) => void;

function PairRowView({
  a,
  aRevisionNo,
  draft,
  row,
  inherited,
  savedHolder,
  draftHolder,
  holderOptions,
  onRemove,
  onReplace,
  onRevert,
  onSeek,
  patchEntity,
  patchInstrument,
  patchAsset,
}: {
  a: Structured | null;
  aRevisionNo: number;
  draft: EditDraft;
  row: PairRow;
  inherited: string;
  savedHolder: (instrument: PairRow['a']) => string;
  draftHolder: (instrument: EditDraft['instruments'][number]) => string;
  holderOptions: Array<{ key: string; label: string }>;
  onRemove: (row: PairRow) => void;
  onReplace: (row: PairRow) => void;
  onRevert: (row: PairRow) => void;
  onSeek: (seconds: number) => void;
  patchEntity: PatchEntity;
  patchInstrument: PatchInstrument;
  patchAsset: PatchAsset;
}) {
  const changed = rowDiffers(row, draft);
  const blocked = revertBlocked(row, draft);
  return (
    <div
      className="grid gap-2 border-b border-ink/10 py-3 last:border-0 sm:grid-cols-[6rem_minmax(0,1fr)_minmax(0,1fr)] sm:gap-4"
      data-row-kind={row.kind}
    >
      <span className="font-mono text-[10.5px] font-bold uppercase tracking-wider text-ink/40">{row.kind}</span>
      <div className="min-w-0" data-side="A">
        {row.a ? (
          <ReadCard inherited={inherited} item={row.a} onSeek={onSeek} savedHolder={savedHolder} />
        ) : (
          <p
            className="rounded-2xl border border-dashed border-moss/40 bg-moss/5 p-4 text-xs font-semibold text-moss"
            data-testid="new-in-b"
          >
            New in B
          </p>
        )}
      </div>
      <div className="min-w-0" data-side="B">
        {row.b ? (
          <EditCard
            draftHolder={draftHolder}
            holderOptions={holderOptions}
            item={row.b}
            onRemove={() => onRemove(row)}
            onReplace={() => onReplace(row)}
            onRevert={changed ? () => onRevert(row) : null}
            onSeek={onSeek}
            patchAsset={patchAsset}
            patchEntity={patchEntity}
            patchInstrument={patchInstrument}
          />
        ) : (
          <div
            className="rounded-2xl border border-dashed border-ink/20 bg-[repeating-linear-gradient(45deg,#f4efe9,#f4efe9_8px,#efe7de_8px,#efe7de_16px)] p-4 text-xs text-[#9b3518]"
            data-testid="deleted-in-b"
          >
            <b className="block text-sm">Deleted</b>
            <span>Removed from your draft.</span>
            <div className="mt-2">
              <button
                className="rounded-full border border-ink/20 bg-white px-3 py-1 text-[11px] font-semibold text-ink disabled:opacity-40"
                disabled={blocked}
                onClick={() => onRevert(row)}
                title={blocked ? 'Revert its holder first' : 'Bring it back exactly as A has it'}
                type="button"
              >
                Revert to v{aRevisionNo}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

function ReadCard({
  item,
  inherited,
  savedHolder,
  onSeek,
}: {
  item: NonNullable<PairRow['a']>;
  inherited: string;
  savedHolder: (instrument: PairRow['a']) => string;
  onSeek: (seconds: number) => void;
}) {
  return (
    <CardFrame imageUrl={item.evidence?.imageUrl ?? null} name={savedItemName(item)} onSeek={onSeek} seconds={item.timestampSeconds}>
      <p className="text-sm font-semibold">{savedItemName(item)}</p>
      <p className="text-ink/60">{item.description}</p>
      {isSavedInstrument(item) && (
        <p className="text-ink/50">
          Threat {item.threatLevel ?? 'unrated'}
          {item.threatLevel !== null ? '/5' : ''}
        </p>
      )}
      {isSavedInstrument(item) && (
        <p>
          Held by <b>{savedHolder(item)}</b>
        </p>
      )}
      {isSavedEntity(item) && inherited && <p>{inherited}</p>}
      {isSavedEntity(item) && item.firstSeenSeconds !== null && (
        <p className="text-ink/50">
          On screen {formatClock(item.firstSeenSeconds)}–{formatClock(item.lastSeenSeconds ?? item.firstSeenSeconds)}
        </p>
      )}
      <p className="text-ink/50">
        Most visible at <b className="font-mono">{clock(item.timestampSeconds)}</b>
      </p>
    </CardFrame>
  );
}

function EditCard({
  item,
  holderOptions,
  draftHolder,
  onRemove,
  onReplace,
  onRevert,
  onSeek,
  patchEntity,
  patchInstrument,
  patchAsset,
}: {
  item: NonNullable<PairRow['b']>;
  holderOptions: Array<{ key: string; label: string }>;
  draftHolder: (instrument: EditDraft['instruments'][number]) => string;
  onRemove: () => void;
  onReplace: () => void;
  onRevert: (() => void) | null;
  onSeek: (seconds: number) => void;
  patchEntity: PatchEntity;
  patchInstrument: PatchInstrument;
  patchAsset: PatchAsset;
}) {
  return (
    <CardFrame imageUrl={item.imageUrl} name={draftItemName(item)} onSeek={onSeek} seconds={item.timestampSeconds}>
      {isDraftEntity(item) ? (
        <>
          <input
            aria-label="Entity name"
            className="control"
            onChange={(event) => patchEntity(item.key, { label: event.target.value })}
            placeholder={item.type}
            value={item.label}
          />
          <select
            aria-label="Entity type"
            className="control mt-1"
            onChange={(event) => patchEntity(item.key, { type: event.target.value })}
            value={item.type}
          >
            {EDITABLE_ENTITY_TYPES.map((type) => (
              <option key={type} value={type}>
                {capitalize(type)}
              </option>
            ))}
          </select>
        </>
      ) : isDraftInstrument(item) ? (
        <input
          aria-label="Instrument name"
          className="control"
          onChange={(event) => patchInstrument(item.key, { name: event.target.value })}
          value={item.name}
        />
      ) : (
        <input
          aria-label="Asset name"
          className="control"
          onChange={(event) => patchAsset(item.key, { name: event.target.value })}
          value={item.name}
        />
      )}
      <textarea
        aria-label="Description"
        className="control mt-1 min-h-[60px]"
        onChange={(event) =>
          isDraftEntity(item)
            ? patchEntity(item.key, { description: event.target.value })
            : isDraftInstrument(item)
              ? patchInstrument(item.key, { description: event.target.value })
              : patchAsset(item.key, { description: event.target.value })
        }
        value={item.description}
      />
      {isDraftInstrument(item) && (
        <div className="mt-1 grid grid-cols-2 gap-1.5">
          <select
            aria-label="Threat level"
            className="control"
            onChange={(event) => patchInstrument(item.key, { threat_level: event.target.value ? Number(event.target.value) : null })}
            value={item.threat_level ?? ''}
          >
            <option value="">Threat level…</option>
            {[1, 2, 3, 4, 5].map((level) => (
              <option key={level} value={level}>
                threat {level}/5
              </option>
            ))}
          </select>
          <select
            aria-label="Held by"
            className="control"
            onChange={(event) => patchInstrument(item.key, { holderKey: event.target.value || null })}
            value={item.holderKey ?? ''}
          >
            <option value="">Holder not determined</option>
            {holderOptions.map((option) => (
              <option key={option.key} value={option.key}>
                held by {option.label}
              </option>
            ))}
          </select>
        </div>
      )}
      {isDraftInstrument(item) && (
        <p className="text-ink/50">
          Held by <b>{draftHolder(item)}</b>
        </p>
      )}
      <p className="text-ink/50">
        Most visible at <b className="font-mono">{clock(item.timestampSeconds)}</b>
      </p>
      <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] font-semibold">
        <button className="rounded-full px-2 py-0.5 text-ink hover:bg-ink/5" onClick={onReplace} type="button">
          Replace image
        </button>
        <button className="rounded-full px-2 py-0.5 text-clay hover:bg-clay/10" onClick={onRemove} type="button">
          Delete
        </button>
        {onRevert && (
          <button className="rounded-full px-2 py-0.5 text-moss hover:bg-moss/10" onClick={onRevert} type="button">
            Revert to A
          </button>
        )}
      </div>
    </CardFrame>
  );
}

function CardFrame({
  imageUrl,
  name,
  seconds,
  onSeek,
  children,
}: {
  imageUrl: string | null;
  name: string;
  seconds: number | null;
  onSeek: (seconds: number) => void;
  children: React.ReactNode;
}) {
  return (
    <article className="w-full max-w-[22rem] overflow-hidden rounded-2xl border border-ink/10 bg-white text-xs">
      <button
        aria-label={seconds === null ? `${name} image` : `Play video from ${formatClock(seconds)}: ${name}`}
        className="block w-full disabled:cursor-default"
        disabled={seconds === null}
        onClick={() => seconds !== null && onSeek(seconds)}
        type="button"
      >
        <EvidenceFrame aspect={2} className="!rounded-none" label={name || 'Evidence'} seconds={seconds} src={imageUrl} />
      </button>
      <div className="space-y-1 p-3">{children}</div>
    </article>
  );
}
