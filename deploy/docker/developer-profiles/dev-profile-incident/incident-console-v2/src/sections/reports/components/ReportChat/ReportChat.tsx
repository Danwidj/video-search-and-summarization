// SPDX-License-Identifier: Apache-2.0
'use client';

import { FormEvent, useEffect, useRef, useState } from 'react';

import { chatRequestBody, type ChatTarget } from '@/lib/chat/report-chat';
import type { ChatCitation, ChatResponse } from '@/modules/chat/domain/chat';
import { formatClock } from '@/modules/reports/domain/normalize';

const SUGGESTIONS = ['What happened, in order?', 'Who is involved?', 'What was taken, or what could cause harm?'];

type Message = { role: 'user' | 'assistant'; content: string; citations?: ChatCitation[]; /** The version label the answer came from. */ answeredFrom?: string };

/**
 * Floating "Ask about this incident" panel. It asks about `target`: the version on
 * screen in View, the unsaved draft in Edit. Each answer says which version it came
 * from, and its citations jump the video to the cited moment.
 */
export function ReportChat({ videoId, target, onSeek, onClose }: { videoId: string; target: ChatTarget; onSeek: (seconds: number) => void; onClose: () => void }) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);
  useEffect(() => { scroller.current?.scrollTo({ top: scroller.current.scrollHeight }); }, [messages, busy, failed]);

  async function send(text: string, history: Message[]) {
    const next: Message[] = [...history, { role: 'user', content: text }];
    setMessages(next);
    setBusy(true);
    setFailed(null);
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(chatRequestBody({ messages: next.map(({ role, content }) => ({ role, content })), sessionId, videoId, target })),
      });
      const payload = (await response.json()) as Partial<ChatResponse> & { error?: string };
      if (!response.ok || !payload.message) throw new Error(payload.error || 'No answer returned');
      setSessionId(payload.sessionId);
      setMessages([...next, { ...payload.message, answeredFrom: target.label }]);
    } catch (cause) {
      setFailed(cause instanceof Error ? cause.message : 'Chat failed');
    } finally {
      setBusy(false);
    }
  }

  function ask(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text || busy) return;
    setQuestion('');
    void send(text, messages);
  }

  function retry() {
    const last = messages[messages.length - 1];
    if (last?.role === 'user') void send(last.content, messages.slice(0, -1));
  }

  return (
    <section aria-label="Ask about this incident" className="print-hidden fixed bottom-16 right-4 z-40 flex h-[min(580px,calc(100vh-7rem))] w-[min(400px,calc(100vw-2rem))] flex-col overflow-clip rounded-[1.2rem] border border-ink/15 bg-white shadow-panel" data-testid="report-chat" role="dialog">
      <div className="flex items-start justify-between gap-2 border-b border-ink/10 bg-[#eef2e9] px-3.5 py-3">
        <div className="min-w-0">
          <b className="text-sm">Ask about this incident</b>
          <p className="mt-1.5"><span className="inline-block rounded-full border border-ink/15 bg-white px-2.5 py-0.5 text-[11px] font-semibold text-moss" data-testid="chat-target" title="The chat follows the version you have selected">Asking about {target.label}</span></p>
        </div>
        <div className="flex gap-1.5">
          <button className="rounded-full border border-ink/15 px-2.5 py-0.5 text-xs font-semibold disabled:opacity-40" disabled={!messages.length || busy} onClick={() => { setMessages([]); setSessionId(undefined); setFailed(null); }} type="button">New chat</button>
          <button aria-label="Close chat" className="rounded-full border border-ink/15 px-2.5 py-0.5 text-xs font-semibold" onClick={onClose} type="button">✕</button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-auto px-3.5 py-3" ref={scroller}>
        {!messages.length && (
          <>
            <p className="max-w-[92%] self-start rounded-2xl rounded-bl-sm bg-canvas px-3 py-2 text-[13px] leading-snug">Ask about the people, objects and events in this incident. Answers come from the version you have open, and link to the moment in the video.</p>
            <div className="flex flex-wrap gap-1.5">{SUGGESTIONS.map((suggestion) => <button className="rounded-full border border-ink/15 px-2.5 py-1 text-left text-xs font-semibold" key={suggestion} onClick={() => void send(suggestion, [])} type="button">{suggestion}</button>)}</div>
          </>
        )}
        {messages.map((message, index) => message.role === 'user'
          ? <p className="max-w-[92%] self-end rounded-2xl rounded-br-sm bg-moss px-3 py-2 text-[13px] leading-snug text-white" key={index}>{message.content}</p>
          : (
            <div className="max-w-[92%] self-start rounded-2xl rounded-bl-sm bg-canvas px-3 py-2 text-[13px] leading-snug" key={index}>
              <p className="whitespace-pre-wrap">{message.content}</p>
              {!!message.citations?.length && (
                <ul className="mt-2 grid gap-1.5" data-testid="chat-citations">
                  {message.citations.map((citation) => (
                    <li key={`${citation.itemId}-${citation.timestampSeconds}`}>
                      <button aria-label={`Jump to ${citation.itemId} at ${formatClock(citation.timestampSeconds)}`} className="grid w-full grid-cols-[52px_minmax(0,1fr)] items-center gap-2 rounded-xl border border-ink/15 bg-white p-1 text-left hover:border-moss" onClick={() => onSeek(citation.timestampSeconds)} type="button">
                        {/* eslint-disable-next-line @next/next/no-img-element -- the agent's signed crop URL, used as given */}
                        <img alt="" className="h-9 w-[52px] rounded-md bg-ink/80 object-cover" src={citation.cropImageUrl} />
                        <span className="min-w-0"><b className="block truncate text-xs">{citation.itemId} · {citation.itemType}</b><span className="text-[11px] text-ink/55">jump to {formatClock(citation.timestampSeconds)}</span></span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-1.5 text-[10.5px] text-ink/50" data-testid="chat-answered-from">Answered from {message.answeredFrom}</p>
            </div>
          ))}
        {busy && <p aria-label="Searching evidence" className="self-start rounded-2xl bg-canvas px-3 py-2 text-xs text-ink/50" role="status">Searching evidence…</p>}
        {failed && (
          <p className="self-start rounded-2xl bg-[#fff6f2] px-3 py-2 text-[13px] text-[#8c3d25]" data-testid="chat-error" role="alert">
            Chat is unavailable right now, so no answer was returned. <span className="text-[11px] opacity-70">({failed})</span> <button className="font-semibold underline" onClick={retry} type="button">Try again</button>
          </p>
        )}
      </div>
      <form className="flex gap-1.5 border-t border-ink/10 px-3 py-2.5" onSubmit={ask}>
        <input aria-label="Question" className="control min-w-0 flex-1" disabled={busy} maxLength={500} onChange={(event) => setQuestion(event.target.value)} placeholder="Ask a question…" value={question} />
        <button className="rounded-full bg-moss px-4 text-xs font-semibold text-white disabled:opacity-50" disabled={busy || !question.trim()} type="submit">Send</button>
      </form>
    </section>
  );
}
