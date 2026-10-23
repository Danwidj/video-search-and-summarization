// SPDX-License-Identifier: Apache-2.0
'use client';

import Link from 'next/link';
import { useRouter } from 'next/navigation';
import { useCallback, useEffect, useRef, useState } from 'react';

import { AdvancedReportTools } from '@/sections/reports/components/AdvancedReportTools';
import { ReportEditPane } from '@/sections/reports/components/ReportEditPane';
import { ReportChat } from '@/sections/reports/components/ReportChat';
import { ReportPane } from '@/sections/reports/components/ReportPane';
import { ReportTimeline } from '@/sections/reports/components/ReportTimeline';
import { ReportVersions } from '@/sections/reports/components/ReportVersions';
import { chatTarget } from '@/lib/chat/report-chat';
import { draftChangeCount, draftToStructured } from '@/lib/reports/compare';
import { draftFromView, draftProblems, editFromDraft, type EditDraft } from '@/modules/reports/domain/edit-draft';
import { reportHeading, type ReportView } from '@/modules/reports/domain/report-view';
import type { RevisionSummary } from '@/modules/reports/domain/revision';

type LoadState =
  | { status: 'loading' }
  | { status: 'error'; message: string }
  | { status: 'ready'; report: ReportView };

type Mode = 'view' | 'edit';
interface EditBase { revisionId: number; revisionNo: number; report: ReportView }

// Human revisions still record who saved them; the mockup removed names from the UI, so the console sends a neutral one.
const SAVE_AUTHOR = 'Reviewer';

/** revisionId null opens the incident's official version, else its newest. startSeconds, when set, is where the player seeks once it has loaded. */
export function ReportPage({ videoId, revisionId, startSeconds = null }: { videoId: string; revisionId: number | null; startSeconds?: number | null }) {
  const router = useRouter();
  const [state, setState] = useState<LoadState>({ status: 'loading' });
  const [attempt, setAttempt] = useState(0);
  const [revisions, setRevisions] = useState<RevisionSummary[] | null>(null);
  const [revisionsError, setRevisionsError] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>('view');
  const [currentTime, setCurrentTime] = useState(0);
  // The player's own length, a second guard (besides the recorded length) before jumping to a time.
  const [playerDuration, setPlayerDuration] = useState<number | null>(null);
  const videoRef = useRef<HTMLVideoElement>(null);
  const startedAt = useRef(false);

  const [chatOpen, setChatOpen] = useState(false);
  const [draft, setDraft] = useState<EditDraft | null>(null);
  const [editBase, setEditBase] = useState<EditBase | null>(null);
  const [compareRevisionId, setCompareRevisionId] = useState<number | null>(null);
  const [compareReport, setCompareReport] = useState<ReportView | null>(null);
  const [compareError, setCompareError] = useState<string | null>(null);
  const [saveOpen, setSaveOpen] = useState(false);
  const [note, setNote] = useState('');
  const [saving, setSaving] = useState(false);
  const [saveProblems, setSaveProblems] = useState<string[]>([]);

  useEffect(() => {
    const controller = new AbortController();
    setState((previous) => (previous.status === 'ready' ? previous : { status: 'loading' }));
    fetch(`/api/reports/${encodeURIComponent(videoId)}${revisionId === null ? '' : `?revision=${revisionId}`}`, { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json()) as { report?: ReportView; error?: string };
        if (!response.ok || !payload.report) throw new Error(payload.error || `Report request failed with HTTP ${response.status}`);
        setState({ status: 'ready', report: payload.report });
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setState({ status: 'error', message: error instanceof Error ? error.message : 'Could not load the report' });
      });
    return () => controller.abort();
  }, [attempt, revisionId, videoId]);

  useEffect(() => {
    const controller = new AbortController();
    fetch(`/api/reports/${encodeURIComponent(videoId)}/revisions`, { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json()) as { revisions?: RevisionSummary[]; error?: string };
        if (!response.ok || !payload.revisions) throw new Error(payload.error || `Versions request failed with HTTP ${response.status}`);
        setRevisions(payload.revisions);
        setRevisionsError(null);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return;
        setRevisionsError(cause instanceof Error ? cause.message : 'Could not load the versions');
      });
    return () => controller.abort();
  }, [videoId, attempt]);

  // A is any saved version; the draft's own version is already loaded, so it needs no request.
  useEffect(() => {
    if (mode !== 'edit' || !editBase || compareRevisionId === null) return;
    if (compareRevisionId === editBase.revisionId) {
      setCompareReport(editBase.report);
      setCompareError(null);
      return;
    }
    const controller = new AbortController();
    setCompareError(null);
    fetch(`/api/reports/${encodeURIComponent(videoId)}?revision=${compareRevisionId}`, { cache: 'no-store', signal: controller.signal })
      .then(async (response) => {
        const payload = (await response.json()) as { report?: ReportView; error?: string };
        if (!response.ok || !payload.report) throw new Error(payload.error || `Version request failed with HTTP ${response.status}`);
        setCompareReport(payload.report);
      })
      .catch((cause: unknown) => {
        if (cause instanceof DOMException && cause.name === 'AbortError') return;
        setCompareError(cause instanceof Error ? cause.message : 'Could not load the comparison version');
        setCompareReport(null);
      });
    return () => controller.abort();
  }, [compareRevisionId, editBase, mode, videoId]);

  const seek = useCallback((seconds: number) => {
    const video = videoRef.current;
    if (!video) return;
    video.currentTime = seconds;
    void video.play().catch(() => undefined);
  }, []);

  const startEdit = useCallback((base: ReportView) => {
    setDraft(draftFromView(base));
    setEditBase({ revisionId: base.revisionId, revisionNo: base.revision.revisionNo, report: base });
    setCompareRevisionId(base.revisionId);
    setCompareReport(base);
    setCompareError(null);
    setMode('edit');
    setSaveOpen(false);
    setSaveProblems([]);
    setNote('');
  }, []);

  const openVersion = (id: number) => {
    setMode('view');
    setDraft(null);
    setEditBase(null);
    setSaveOpen(false);
    router.push(`/reports/${encodeURIComponent(videoId)}?revision=${id}`);
  };

  if (state.status === 'loading') {
    return (
      <div className="mx-auto max-w-[1500px] px-4 pb-16 pt-6 sm:px-6 lg:px-12" role="status">
        <div className="animate-pulse overflow-hidden rounded-[2rem] border border-ink/10 bg-white shadow-panel">
          <div className="h-12 border-b border-ink/10 bg-ink/5" />
          <div className="grid gap-px bg-ink/10 lg:grid-cols-[minmax(0,26rem)_1fr_16rem]"><div className="aspect-video bg-ink/10" /><div className="bg-white" /><div className="bg-white" /></div>
          <div className="space-y-3 p-8"><div className="h-4 rounded bg-ink/10" /><div className="h-4 rounded bg-ink/10" /><div className="h-4 w-3/4 rounded bg-ink/10" /></div>
          <span className="sr-only">Loading incident report</span>
        </div>
      </div>
    );
  }

  if (state.status === 'error') {
    return (
      <div className="mx-auto grid min-h-[65vh] max-w-xl place-items-center px-6 text-center">
        <div>
          <p className="font-mono text-xs uppercase tracking-[0.2em] text-clay">Report unavailable</p>
          <h1 className="mt-3 text-3xl font-semibold">We couldn&apos;t reopen this analysis.</h1>
          <p className="mt-4 text-sm leading-6 text-ink/60">{state.message}</p>
          <div className="mt-7 flex justify-center gap-3">
            <button className="rounded-full bg-ink px-5 py-3 text-sm font-semibold text-white" onClick={() => setAttempt((value) => value + 1)} type="button">Try again</button>
            <Link className="rounded-full border border-ink/15 px-5 py-3 text-sm font-semibold" href="/">New analysis</Link>
          </div>
        </div>
      </div>
    );
  }

  const { report } = state;
  const officialRevision = (revisions ?? []).find((revision) => revision.isOfficial);
  const heading = reportHeading(mode === 'edit' && editBase ? editBase.report : report);
  const filename = (mode === 'edit' && editBase ? editBase.report : report).run.filename;
  const draftStructured = mode === 'edit' && draft ? draftToStructured(draft) : null;
  const changes = draft && editBase ? draftChangeCount(editBase.report.structured, draft) : 0;
  const problems = draft ? draftProblems(draft) : [];
  const officialLabel = officialRevision ? `v${officialRevision.revisionNo}` : 'none';

  function switchMode(next: Mode) {
    if (next === 'view') {
      setMode('view');
      setSaveOpen(false);
      return;
    }
    if (draft && editBase) setMode('edit');
    else startEdit(report);
  }

  async function save() {
    if (!draft || !editBase || saving) return;
    const trimmed = note.trim();
    if (!trimmed) {
      setSaveProblems(['Add a note for the new version.']);
      return;
    }
    if (problems.length) {
      setSaveProblems(problems);
      return;
    }
    setSaving(true);
    setSaveProblems([]);
    try {
      const response = await fetch(`/api/reports/${encodeURIComponent(videoId)}/edit`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ parentId: editBase.revisionId, editedBy: SAVE_AUTHOR, note: trimmed, edit: editFromDraft(draft) }),
      });
      const payload = (await response.json()) as { error?: string; violations?: Array<{ message: string }>; revision?: { revisionId: number } };
      if (!response.ok || !payload.revision) {
        setSaveProblems(payload.violations?.length ? payload.violations.map((violation) => violation.message) : [payload.error || 'Save failed']);
        return;
      }
      const savedId = payload.revision.revisionId;
      setDraft(null);
      setEditBase(null);
      setCompareReport(null);
      setCompareRevisionId(null);
      setMode('view');
      setSaveOpen(false);
      setNote('');
      setAttempt((value) => value + 1);
      router.push(`/reports/${encodeURIComponent(videoId)}?revision=${savedId}`);
    } catch (cause) {
      setSaveProblems([cause instanceof Error ? cause.message : 'Save failed']);
    } finally {
      setSaving(false);
    }
  }

  return (
    <div className="mx-auto max-w-[1500px] px-4 pb-16 pt-2 sm:px-6 lg:px-12">
      <article className="report-sheet overflow-clip rounded-[2rem] border border-ink/10 bg-white shadow-panel" data-testid="report-page">
        <div className="flex flex-wrap items-center gap-x-4 gap-y-1 border-b border-ink/10 px-5 py-3 text-sm">
          <Link className="font-semibold text-moss" href="/library" id="back-to-library">← Library</Link>
          <h1 className="min-w-0 flex-1 truncate text-sm font-semibold" title={filename}>{heading}<span className="ml-2 font-normal text-ink/45">{filename}</span></h1>
          <button aria-expanded={chatOpen} className="rounded-full border border-ink/15 px-3 py-1 text-xs font-semibold text-moss" data-testid="chat-toggle" onClick={() => setChatOpen((open) => !open)} type="button">Ask about this incident</button>
          <div aria-label="Report mode" className="flex shrink-0 rounded-full border border-ink/15 p-0.5 text-xs font-semibold" role="tablist">
            <button aria-selected={mode === 'view'} className={`rounded-full px-3 py-1 ${mode === 'view' ? 'bg-ink text-white' : 'text-ink/60'}`} onClick={() => switchMode('view')} role="tab" type="button">View</button>
            <button aria-selected={mode === 'edit'} className={`rounded-full px-3 py-1 ${mode === 'edit' ? 'bg-ink text-white' : 'text-ink/60'}`} onClick={() => switchMode('edit')} role="tab" type="button">Edit</button>
          </div>
        </div>

        <div className="sticky top-0 z-20 grid border-b border-ink/10 bg-white lg:h-[clamp(190px,30vh,300px)] lg:grid-cols-[minmax(0,26rem)_minmax(0,1fr)_16rem]" data-testid="report-band">
          <video
            className="aspect-video w-full bg-black object-contain lg:h-full"
            controls
            onLoadedMetadata={(event) => {
              const length = event.currentTarget.duration;
              setPlayerDuration(Number.isFinite(length) && length > 0 ? length : null);
              if (startSeconds !== null && !startedAt.current) { startedAt.current = true; event.currentTarget.currentTime = startSeconds; }
            }}
            onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)}
            ref={videoRef}
            src={report.run.playbackUrl}
          />
          <div className="hidden min-h-0 overflow-hidden border-l border-ink/10 sm:flex sm:flex-col">
            <ReportTimeline currentTime={currentTime} onSeek={seek} structured={draftStructured ?? report.structured} videoSeconds={playerDuration ?? report.modelOutput?.timelineCheck.videoDurationSeconds ?? null} />
          </div>
          <div className="min-h-0 overflow-hidden border-l border-ink/10 max-lg:max-h-72">
            <ReportVersions
              compareRevisionId={mode === 'edit' ? compareRevisionId : null}
              currentRevisionId={report.revisionId}
              error={revisionsError}
              mode={mode}
              onCompare={(id) => setCompareRevisionId(id)}
              onOfficialChanged={() => setAttempt((value) => value + 1)}
              onOpen={openVersion}
              revisions={revisions}
              videoId={videoId}
            />
          </div>
        </div>

        {!officialRevision && revisions && (
          <p className="border-b border-[#e8d49a] bg-[#fffaf0] px-5 py-2 text-xs text-[#765300]" data-testid="official-status">
            No official version has been selected for this video. Star a version to make it official.
          </p>
        )}

        {mode === 'edit' && compareError && <p className="border-b border-[#e8d49a] bg-[#fffaf0] px-5 py-2 text-xs text-[#765300]" data-testid="compare-error">Could not load the A version: {compareError}</p>}

        {mode === 'view' ? (
          <ReportPane onSeek={seek} playerDuration={playerDuration} report={report} />
        ) : draft && editBase ? (
          <ReportEditPane
            a={compareReport?.structured ?? null}
            aRevisionNo={compareReport?.revision.revisionNo ?? editBase.revisionNo}
            baseRevisionNo={editBase.revisionNo}
            draft={draft}
            onChange={setDraft}
            onSeek={seek}
            title={reportHeading(editBase.report)}
            videoId={videoId}
            videoSrc={report.run.playbackUrl}
          />
        ) : null}

        <div className="sticky bottom-0 z-20 flex items-center justify-between gap-3 border-t border-ink/10 bg-white/95 px-5 py-3 text-sm backdrop-blur">
          {mode === 'view' ? (
            <>
              <span className="text-ink/60"><b>v{report.revision.revisionNo}</b> {report.official.isOfficial ? 'is the official version' : 'is not the official version'}</span>
              <button className="rounded-full bg-moss px-5 py-2 text-sm font-semibold text-white" onClick={() => startEdit(report)} type="button">Edit from v{report.revision.revisionNo}</button>
            </>
          ) : (
            <>
              <span className="min-w-0 text-ink/60">
                {editBase && (
                  <><b>Draft</b> from v{editBase.revisionNo} · {changes ? <><b>{changes}</b> unsaved change{changes === 1 ? '' : 's'}</> : 'no changes yet'} · official is <b>{officialLabel}</b></>
                )}
              </span>
              <div className="relative shrink-0">
                {saveOpen && (
                  <div className="absolute bottom-full right-0 z-30 mb-2 w-[min(22rem,85vw)] rounded-2xl border border-ink/15 bg-white p-4 shadow-panel" data-testid="save-note">
                    <label className="block text-xs font-bold" htmlFor="savenote">Note for the new version (required)
                      <textarea aria-label="Note for the new version" className="control mt-1 min-h-[84px]" id="savenote" onChange={(event) => setNote(event.target.value)} placeholder="What changed and why, e.g. raised severity to 4 and added the phone" value={note} />
                    </label>
                    {saveProblems.length > 0 && <ul aria-live="polite" className="mt-2 list-disc pl-5 text-xs text-clay" data-testid="save-problems">{saveProblems.map((problem) => <li key={problem}>{problem}</li>)}</ul>}
                    <div className="mt-3 flex justify-end gap-2">
                      <button className="rounded-full border border-ink/15 px-3 py-1.5 text-xs font-semibold" disabled={saving} onClick={() => { setSaveOpen(false); setSaveProblems([]); }} type="button">Cancel</button>
                      <button className="rounded-full bg-moss px-4 py-1.5 text-xs font-semibold text-white disabled:opacity-50" disabled={saving || !note.trim()} onClick={() => void save()} type="button">{saving ? 'Saving…' : 'Save as new version'}</button>
                    </div>
                  </div>
                )}
                <button className="rounded-full bg-moss px-5 py-2 text-sm font-semibold text-white disabled:opacity-50" disabled={changes === 0 || saving} onClick={() => setSaveOpen(true)} type="button">Save as new version</button>
              </div>
            </>
          )}
        </div>
      </article>
      {mode === 'view' && <AdvancedReportTools report={report} />}
      {chatOpen && <ReportChat onClose={() => setChatOpen(false)} onSeek={seek} target={chatTarget(mode === 'edit' && draft && editBase ? { revision: editBase.report.revision, isOfficial: editBase.report.official.isOfficial, draft } : { revision: report.revision, isOfficial: report.official.isOfficial, draft: null })} videoId={videoId} />}
    </div>
  );
}
