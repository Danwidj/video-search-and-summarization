// SPDX-License-Identifier: Apache-2.0

'use client';

import { useRouter } from 'next/navigation';
import { useEffect, useRef, useState } from 'react';

import { describeCode } from '@/modules/videos/domain/run-labels';

const MAX_PROMPT = 1000;

interface ModelOption {
  id: string;
  label: string;
}

/**
 * Analyse the already-stored video again (a new AI version) with one of the
 * approved models and an optional reviewer prompt typed here. Every attempt is
 * a new run; earlier versions and the reviewer's edits are not changed or
 * carried across, and the new version is not made official.
 */
export function ReanalysisCard({ videoId, onAttempted }: { videoId: string; onAttempted?: () => void }) {
  const router = useRouter();
  const [models, setModels] = useState<ModelOption[]>([]);
  const [model, setModel] = useState('');
  const [prompt, setPrompt] = useState('');
  const [busy, setBusy] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [result, setResult] = useState<{ tone: 'error' | 'ok'; lines: string[] } | null>(null);
  const timer = useRef<number | null>(null);

  useEffect(() => {
    void fetch('/api/models', { cache: 'no-store' })
      .then((response) => response.json() as Promise<{ models?: ModelOption[]; defaultModel?: string }>)
      .then((payload) => {
        setModels(payload.models || []);
        setModel(payload.defaultModel || payload.models?.[0]?.id || '');
      })
      .catch(() => undefined);
    return () => {
      if (timer.current) window.clearInterval(timer.current);
    };
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
        body: JSON.stringify({ model, ...(prompt.trim() ? { additionalInstruction: prompt } : {}) }),
      });
      const payload = (await response.json()) as {
        run?: { videoId: string; revisionId: number };
        error?: string;
        outcome?: string;
        code?: string;
        codes?: string[];
      };
      if (response.ok && payload.run) {
        router.push(`/reports/${encodeURIComponent(payload.run.videoId)}?revision=${payload.run.revisionId}`);
        return;
      }
      const lines =
        payload.outcome === 'contract_failed'
          ? [
              'The model answered, but the answer broke the incident contract, so no report was created. The attempt is recorded in the history.',
              ...(payload.codes || []).map(describeCode),
            ]
          : payload.outcome === 'request_failed'
            ? [
                'The model request did not produce a usable answer. The attempt is recorded in the history.',
                describeCode(payload.code || ''),
              ]
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
      <p className="text-xs text-ink/55">
        Runs the stored video again as a new AI version. Earlier versions and reviewer edits are kept as they are and are not used by the
        new run; the new version is not made official automatically.
      </p>
      <label className="mt-3 block text-xs font-bold">
        Model
        <select className="control mt-1" disabled={busy} onChange={(event) => setModel(event.target.value)} value={model}>
          {models.map((option) => (
            <option key={option.id} value={option.id}>
              {option.label}
            </option>
          ))}
        </select>
      </label>
      <label className="mt-3 block text-xs font-bold">
        Reviewer prompt (optional)
        <textarea
          className="control mt-1 min-h-[80px]"
          disabled={busy}
          maxLength={MAX_PROMPT}
          onChange={(event) => setPrompt(event.target.value)}
          placeholder="e.g. Pay particular attention to the person entering from the left side of the frame."
          value={prompt}
        />
      </label>
      <p className="mt-1 flex justify-between text-[11px] text-ink/45">
        <span>Adds context for this run; it can’t change the report format.</span>
        <span>
          {prompt.length}/{MAX_PROMPT}
        </span>
      </p>
      <button
        className="mt-3 rounded-full bg-ink px-4 py-2 text-xs font-semibold text-white disabled:opacity-50"
        disabled={busy || !model}
        onClick={() => void run()}
        type="button"
      >
        {busy ? `Analysing… ${elapsed}s` : 'Generate new version'}
      </button>
      {result && (
        <div
          aria-live="polite"
          className={`mt-3 rounded-xl p-3 text-xs ${result.tone === 'error' ? 'bg-[#fff6f2] text-[#8c3d25]' : 'bg-signal/10 text-moss'}`}
        >
          {result.lines.map((line) => (
            <p key={line}>{line}</p>
          ))}
        </div>
      )}
    </div>
  );
}
