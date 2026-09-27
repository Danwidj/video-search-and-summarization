// SPDX-License-Identifier: Apache-2.0

'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import { describeCode } from '@/lib/runs/labels';

const MAX_INSTRUCTION = 1000;

interface ModelOption { id: string; label: string }

/**
 * Analyse the already-stored video again with one of the approved models and
 * an optional additional instruction. Every attempt is a new run; earlier
 * runs and reports are never changed and the new report is not made official.
 */
export function ReanalysisCard({ videoId, onAttempted }: { videoId: string; onAttempted?: () => void }) {
  const router = useRouter();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState('');
  const [available, setAvailable] = useState(true);
  const [instruction, setInstruction] = useState('');
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<{ tone: 'error' | 'ok'; lines: string[] } | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    void fetch('/api/models', { cache: 'no-store' })
      .then((response) => response.json() as Promise<{ models?: ModelOption[]; defaultModel?: string; modelSelection?: boolean }>)
      .then((payload) => {
        setModels(payload.models || []);
        setModel(payload.defaultModel || payload.models?.[0]?.id || '');
        setAvailable(payload.modelSelection !== false);
      })
      .catch(() => undefined);
    return () => { if (timer.current) window.clearInterval(timer.current); };
  }, []);

  async function run() {
    if (busy || !model) return;
    setBusy(true);
    setResult(null);
    setElapsed(0);
    const started = Date.now();
    timer.current = window.setInterval(() => setElapsed(Math.floor((Date.now() - started) / 1000)), 1000);
    try {
      const response = await fetch(`/api/videos/${encodeURIComponent(videoId)}/runs`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model, ...(instruction.trim() ? { additionalInstruction: instruction } : {}) }),
      });
      const payload = (await response.json()) as { run?: { videoId: string; modelRunId: string }; error?: string; outcome?: string; code?: string; codes?: string[] };
      if (response.ok && payload.run) {
        router.push(`/reports/${encodeURIComponent(payload.run.videoId)}?run=${encodeURIComponent(payload.run.modelRunId)}`);
        return;
      }
      const lines = payload.outcome === 'contract_failed'
        ? ['The model answered, but the answer broke the incident contract, so no report was created. The attempt is recorded in the history.', ...(payload.codes || []).map(describeCode)]
        : payload.outcome === 'request_failed'
          ? ['The model request did not produce a usable answer. The attempt is recorded in the history.', describeCode(payload.code || '')]
          : [payload.error || `Re-analysis failed (HTTP ${response.status})`];
      setResult({ tone: 'error', lines });
      onAttempted?.();
    } catch (cause) {
      setResult({ tone: 'error', lines: [cause instanceof Error ? cause.message : 'Re-analysis failed'] });
    } finally {
      if (timer.current) window.clearInterval(timer.current);
      setBusy(false);
    }
  }

  return (
    <div data-testid="reanalysis-card">
      <p className="text-xs text-ink/55">Runs the stored video again. Every attempt is kept as a new run; earlier reports are not changed and the new report is not made official automatically.</p>
      {!available ? <p className="mt-3 text-sm text-clay">Model selection is only available in gateway analysis mode.</p> : (
        <>
          <label className="mt-3 block text-xs font-bold">Model
            <select className="control mt-1" disabled={busy} onChange={(event) => setModel(event.target.value)} value={model}>
              {models.map((option) => <option key={option.id} value={option.id}>{option.label}</option>)}
            </select>
          </label>
          <label className="mt-3 block text-xs font-bold">Additional instruction for this video (optional)
            <textarea className="control mt-1 min-h-[80px]" disabled={busy} maxLength={MAX_INSTRUCTION} onChange={(event) => setInstruction(event.target.value)} placeholder="e.g. Pay particular attention to the person entering from the left side of the frame." value={instruction} />
          </label>
          <p className="mt-1 flex justify-between text-[11px] text-ink/45"><span>Adds context; it can’t change the report format.</span><span>{instruction.length}/{MAX_INSTRUCTION}</span></p>
          <button className="mt-3 rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white disabled:opacity-50" disabled={busy || !model} onClick={() => void run()} type="button">
            {busy ? `Analysing… ${elapsed}s` : 'Generate new report'}
          </button>
        </>
      )}
      {result && <div aria-live="polite" className={`mt-3 rounded-xl p-3 text-xs ${result.tone === 'error' ? 'bg-[#fff6f2] text-[#8c3d25]' : 'bg-signal/10 text-moss'}`}>{result.lines.map((line, index) => <p key={index}>{line}</p>)}</div>}
    </div>
  );
}
