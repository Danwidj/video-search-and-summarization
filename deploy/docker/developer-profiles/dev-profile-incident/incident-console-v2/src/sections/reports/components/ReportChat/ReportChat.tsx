// SPDX-License-Identifier: Apache-2.0
'use client';

import { type FormEvent, useEffect, useRef, useState } from 'react';

import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { chatRequestBody, type ChatTarget } from '@/lib/chat/report-chat';
import type { ChatCitation, ChatResponse } from '@/modules/chat/domain/chat';
import { formatClock } from '@/modules/reports/domain/normalize';

const SUGGESTIONS = ['What happened, in order?', 'Who is involved?', 'What was taken, or what could cause harm?'];

let messageSequence = 0;

type Message = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: ChatCitation[] /** The version label the answer came from. */;
  answeredFrom?: string;
};

/**
 * Floating / drawer "Ask about this incident" panel. It asks about `target`: the version on
 * screen in View, the unsaved draft in Edit. Each answer says which version it came
 * from, and its citations jump the video to the cited moment.
 */
export function ReportChat({
  videoId,
  target,
  onSeek,
  onClose,
}: {
  videoId: string;
  target: ChatTarget;
  onSeek: (seconds: number) => void;
  onClose: () => void;
}) {
  const [messages, setMessages] = useState<Message[]>([]);
  const [sessionId, setSessionId] = useState<string | undefined>();
  const [question, setQuestion] = useState('');
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState<string | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll to bottom whenever chat state updates
  useEffect(() => {
    scroller.current?.scrollTo({ top: scroller.current.scrollHeight });
  }, [messages, busy, failed]);

  async function send(text: string, history: Message[]) {
    messageSequence += 1;
    const next: Message[] = [...history, { id: `msg-${messageSequence}`, role: 'user', content: text }];
    setMessages(next);
    setBusy(true);
    setFailed(null);
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          chatRequestBody({ messages: next.map(({ role, content }) => ({ role, content })), sessionId, videoId, target }),
        ),
      });
      const payload = (await response.json()) as Partial<ChatResponse> & { error?: string };
      if (!response.ok || !payload.message) throw new Error(payload.error || 'No answer returned');
      setSessionId(payload.sessionId);
      messageSequence += 1;
      setMessages([...next, { ...payload.message, id: `msg-${messageSequence}`, answeredFrom: target.label }]);
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
    <section
      aria-label="Ask about this incident"
      className="flex h-full w-full flex-col overflow-hidden bg-card text-card-foreground"
      data-testid="report-chat"
    >
      <div className="flex items-start justify-between gap-2 border-b border-border bg-muted/40 px-3.5 py-3">
        <div className="min-w-0">
          <b className="text-sm">Ask about this incident</b>
          <p className="mt-1.5">
            <Badge
              className="text-[11px] font-semibold"
              data-testid="chat-target"
              title="The chat follows the version you have selected"
              variant="outline"
            >
              Asking about {target.label}
            </Badge>
          </p>
        </div>
        <div className="flex gap-1.5">
          <Button
            disabled={!messages.length || busy}
            onClick={() => {
              setMessages([]);
              setSessionId(undefined);
              setFailed(null);
            }}
            size="sm"
            type="button"
            variant="outline"
          >
            New chat
          </Button>
          <Button aria-label="Close chat" onClick={onClose} size="sm" type="button" variant="ghost">
            ✕
          </Button>
        </div>
      </div>
      <div className="flex min-h-0 flex-1 flex-col gap-2.5 overflow-auto px-3.5 py-3" ref={scroller}>
        {!messages.length && (
          <>
            <p className="max-w-[92%] self-start rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-[13px] leading-snug">
              Ask about the people, objects and events in this incident. Answers come from the version you have open, and link to the moment
              in the video.
            </p>
            <div className="flex flex-wrap gap-1.5">
              {SUGGESTIONS.map((suggestion) => (
                <Button
                  className="h-auto px-2.5 py-1 text-left text-xs font-semibold"
                  key={suggestion}
                  onClick={() => void send(suggestion, [])}
                  size="sm"
                  type="button"
                  variant="outline"
                >
                  {suggestion}
                </Button>
              ))}
            </div>
          </>
        )}
        {messages.map((message) =>
          message.role === 'user' ? (
            <p
              className="max-w-[92%] self-end rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-[13px] leading-snug text-primary-foreground"
              key={message.id}
            >
              {message.content}
            </p>
          ) : (
            <div
              className="max-w-[92%] self-start rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-[13px] leading-snug text-foreground"
              key={message.id}
            >
              <p className="whitespace-pre-wrap">{message.content}</p>
              {!!message.citations?.length && (
                <ul className="mt-2 grid gap-1.5" data-testid="chat-citations">
                  {message.citations.map((citation) => (
                    <li key={`${citation.itemId}-${citation.timestampSeconds}`}>
                      <button
                        aria-label={`Jump to ${citation.itemId} at ${formatClock(citation.timestampSeconds)}`}
                        className="grid w-full grid-cols-[52px_minmax(0,1fr)] items-center gap-2 rounded-xl border border-border bg-card p-1 text-left transition hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                        onClick={() => onSeek(citation.timestampSeconds)}
                        type="button"
                      >
                        {/* eslint-disable-next-line @next/next/no-img-element -- the agent's signed crop URL, used as given */}
                        {/* biome-ignore lint/performance/noImgElement: the agent's signed crop URL, used as given */}
                        <img alt="" className="h-9 w-[52px] rounded-md bg-muted object-cover" src={citation.cropImageUrl} />
                        <span className="min-w-0">
                          <b className="block truncate text-xs">
                            {citation.itemId} · {citation.itemType}
                          </b>
                          <span className="text-[11px] text-muted-foreground">jump to {formatClock(citation.timestampSeconds)}</span>
                        </span>
                      </button>
                    </li>
                  ))}
                </ul>
              )}
              <p className="mt-1.5 text-[10.5px] text-muted-foreground" data-testid="chat-answered-from">
                Answered from {message.answeredFrom}
              </p>
            </div>
          ),
        )}
        {busy && (
          <p
            aria-label="Searching evidence"
            className="self-start rounded-2xl bg-muted px-3 py-2 text-xs text-muted-foreground"
            role="status"
          >
            Searching evidence…
          </p>
        )}
        {failed && (
          <p
            className="self-start rounded-2xl bg-destructive/10 px-3 py-2 text-[13px] text-destructive"
            data-testid="chat-error"
            role="alert"
          >
            Chat is unavailable right now, so no answer was returned. <span className="text-[11px] opacity-70">({failed})</span>{' '}
            <button className="font-semibold underline" onClick={retry} type="button">
              Try again
            </button>
          </p>
        )}
      </div>
      <form className="flex gap-1.5 border-t border-border px-3 py-2.5" onSubmit={ask}>
        <Input
          aria-label="Question"
          className="min-w-0 flex-1"
          disabled={busy}
          maxLength={500}
          onChange={(event) => setQuestion(event.target.value)}
          placeholder="Ask a question…"
          value={question}
        />
        <Button disabled={busy || !question.trim()} size="sm" type="submit">
          Send
        </Button>
      </form>
    </section>
  );
}
