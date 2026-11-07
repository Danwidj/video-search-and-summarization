// SPDX-License-Identifier: Apache-2.0
'use client';

import { type FormEvent, useEffect, useRef, useState } from 'react';
import { XIcon } from 'lucide-react';

import { Alert, AlertDescription } from '@/components/ui/alert';
import { Badge } from '@/components/ui/badge';
import { Bubble, BubbleContent } from '@/components/ui/bubble';
import { Button } from '@/components/ui/button';
import { Card } from '@/components/ui/card';
import { Input } from '@/components/ui/input';
import { Marker, MarkerContent } from '@/components/ui/marker';
import { Message } from '@/components/ui/message';
import { SheetClose } from '@/components/ui/sheet';
import {
  MessageScroller,
  MessageScrollerContent,
  MessageScrollerProvider,
  MessageScrollerViewport,
} from '@/components/ui/message-scroller';
import {
  type AnswerSource,
  answerSourceLine,
  type ChatTarget,
  chatHistory,
  chatRequestBody,
  citationTitle,
  offersVideoCheck,
} from '@/lib/chat/report-chat';
import { evidenceRows, pendingEvidenceExchange, splitEvidenceActions } from '@/lib/chat/evidence-ask';
import { segmentChatText } from '@/lib/chat/timestamps';
import { draftSnapshot, type ProposedAction } from '@/lib/edits/chat-edit';
import type { BoxOpening } from '@/lib/evidence/box-tool';
import type { EditDraft } from '@/modules/reports/domain/edit-draft';
import type { AppliedAction, ChatCitation, ChatResponse, ChatStep, SkippedAction, VideoOffer } from '@/modules/chat/domain/chat';
import { formatClock } from '@/modules/reports/domain/normalize';
import { ChatStepsView } from './ChatStepsView';

const SUGGESTIONS = ['Show the timeline of events'];

const CHAT_FAILED = 'The chat service is unavailable right now. Please try again in a moment.';

let messageSequence = 0;

/** A reply body as JSON; a proxy's HTML error page reads as an empty reply rather than a parse error on screen. */
async function readReply(response: Response): Promise<unknown> {
  return response.json().catch(() => ({}));
}

type ChatMessage = {
  id: string;
  role: 'user' | 'assistant';
  content: string;
  citations?: ChatCitation[] /** The version label the answer came from. */;
  answeredFrom?: string;
  /** chat-contract-v2: the report could not answer this question. */
  insufficientEvidence?: boolean;
  /** chat-contract-v3: where the answer came from; a fresh video check is 'video'. */
  source?: AnswerSource;
  videoOffer?: VideoOffer;
  /** Times the agent found the report does not hold. They stay plain text. */
  unknownTimes?: string[];
  steps?: ChatStep[];
  applied?: AppliedAction[];
  skipped?: SkippedAction[];
  wallMs?: number;
  /** The reply's questions to the reviewer about new evidence, in order (its content is those questions, one per line). */
  questions?: string[];
  /** The reply opened the box tool for new evidence at this second, with this name. */
  openedBox?: BoxOpening;
};

/** One conversation. The report page holds it, so closing the panel does not lose it. */
export type ChatThread = {
  messages: ChatMessage[];
  sessionId?: string;
  busy: boolean;
  failed: string | null;
};

export const EMPTY_CHAT_THREAD: ChatThread = { messages: [], busy: false, failed: null };

/** An answer's text as written, each video time in it a button that jumps there. */
function AnswerText({
  content,
  durationSeconds,
  onSeek,
  unsupported,
}: {
  content: string;
  durationSeconds: number | null;
  onSeek: (seconds: number) => void;
  unsupported?: string[];
}) {
  return (
    <p className="whitespace-pre-wrap" data-testid="chat-answer">
      {segmentChatText(content, { durationSeconds, unsupported }).map((segment, index) =>
        segment.kind === 'time' ? (
          <button
            aria-label={`Jump to ${segment.text} in the video`}
            className="rounded-sm font-semibold text-primary tabular-nums underline underline-offset-2 hover:no-underline focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
            data-testid="chat-time"
            // biome-ignore lint/suspicious/noArrayIndexKey: segments are derived from one fixed text, in order
            key={index}
            onClick={() => onSeek(segment.seconds)}
            type="button"
          >
            {segment.text}
          </button>
        ) : (
          segment.text
        ),
      )}
    </p>
  );
}

/**
 * Floating / drawer "Ask about this incident" panel. It asks about `target`: the version on
 * screen in View, the unsaved draft in Edit. Each answer says which version it came
 * from, and every video time in it, like its citations, jumps the video to that moment.
 */
export function ReportChat({
  videoId,
  target,
  thread,
  onThreadChange,
  onSeek,
  durationSeconds = null,
  titles = {},
  edits,
}: {
  videoId: string;
  target: ChatTarget;
  thread: ChatThread;
  onThreadChange: (change: Partial<ChatThread>) => void;
  onSeek: (seconds: number) => void;
  /** The player's length, once known: a time past it is not offered as a jump. */
  durationSeconds?: number | null;
  /** Each cited item's name (citationTitles), so a citation is shown without its id. */
  titles?: Record<string, string>;
  /**
   * Lets a question change the draft . `current` is the draft as it is when the question
   * is sent; `apply` takes the agent's proposals, made for that draft, and returns what it applied and skipped.
   * A box the agent opened for new evidence (`opening`) is shown in Edit, the box tool open on it.
   */
  edits?: {
    current: () => EditDraft;
    apply: (sent: EditDraft, proposals: ProposedAction[], opening?: BoxOpening) => { applied: AppliedAction[]; skipped: SkippedAction[] };
  };
}) {
  const { messages, sessionId, busy, failed } = thread;
  const [question, setQuestion] = useState('');
  const scrollerViewportRef = useRef<HTMLDivElement>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: scroll to bottom whenever chat state updates
  useEffect(() => {
    scrollerViewportRef.current?.scrollTo({ top: scrollerViewportRef.current.scrollHeight });
  }, [messages, busy, failed]);

  async function send(text: string, history: ChatMessage[]) {
    messageSequence += 1;
    const next: ChatMessage[] = [...history, { id: `msg-${messageSequence}`, role: 'user', content: text }];
    onThreadChange({ messages: next, busy: true, failed: null });
    const sent = edits?.current();
    try {
      const response = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(
          chatRequestBody({
            messages: chatHistory(next).map(({ role, content }) => ({ role, content })),
            sessionId,
            videoId,
            target,
            ...(sent ? { editDraft: draftSnapshot(sent) } : {}),
            evidence: pendingEvidenceExchange(next) ?? undefined,
          }),
        ),
      });
      const payload = (await readReply(response)) as Partial<ChatResponse> & { error?: string };
      if (!response.ok || !payload.message) throw new Error(payload.error || CHAT_FAILED);
      // A question for the reviewer is the reply; a box opening goes to the page; the other edits join the draft in one
      // change (one Undo), then the message says what happened to each.
      const actions = payload.message.actions ?? [];
      const { questions, opening, rest } = splitEvidenceActions(actions, sent ?? null);
      const outcome = edits && sent && actions.length ? edits.apply(sent, rest, opening) : undefined;
      messageSequence += 1;
      onThreadChange({
        sessionId: payload.sessionId,
        messages: [
          ...next,
          {
            ...payload.message,
            content: questions.length ? questions.join('\n') : payload.message.content,
            id: `msg-${messageSequence}`,
            answeredFrom: target.label,
            unknownTimes: payload.grounding?.unknownTimes,
            steps: payload.message.steps,
            applied: outcome?.applied ?? payload.message.applied,
            skipped: outcome?.skipped ?? payload.message.skipped,
            wallMs: payload.message.wallMs,
            questions: questions.length ? questions : undefined,
            openedBox: opening,
          },
        ],
      });
    } catch (cause) {
      // A fetch that never reached the server is a TypeError whose message means nothing to a reviewer.
      onThreadChange({ failed: cause instanceof Error && !(cause instanceof TypeError) ? cause.message : CHAT_FAILED });
    } finally {
      onThreadChange({ busy: false });
    }
  }

  /** Runs the fresh look the reviewer confirmed. Its result joins the conversation as its own, labelled message. */
  async function checkVideo(answer: ChatMessage) {
    const asked = messages.slice(0, messages.indexOf(answer)).findLast((message) => message.role === 'user');
    if (!asked) return;
    const kept = messages.map((message) => (message === answer ? { ...message, videoOffer: undefined } : message));
    onThreadChange({ messages: kept, busy: true, failed: null });
    let content: string;
    try {
      const response = await fetch('/api/chat/video-check', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ videoId, question: asked.content, storedAnswer: answer.content }),
      });
      const payload = (await readReply(response)) as { content?: string; error?: string };
      if (!response.ok || !payload.content) throw new Error(payload.error || 'No result was returned.');
      content = payload.content;
    } catch (cause) {
      const reason = cause instanceof Error && !(cause instanceof TypeError) ? cause.message : 'The check could not be reached.';
      content = `The video check did not finish: ${reason} The answer above from the stored report stands.`;
    }
    messageSequence += 1;
    onThreadChange({
      messages: [...kept, { id: `msg-${messageSequence}`, role: 'assistant', content, source: 'video', answeredFrom: target.label }],
      busy: false,
    });
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
    <Card
      aria-label="Ask about this incident"
      className="flex h-full w-full flex-col overflow-hidden rounded-none border-0 bg-card text-card-foreground shadow-none"
      data-testid="report-chat"
    >
      <div className="relative flex min-h-24 items-center border-b border-border/70 bg-muted/40 px-5 py-5 pr-14">
        <div className="min-w-0">
          <h2 className="text-lg font-bold tracking-tight text-foreground">Ask about this incident</h2>
          <p className="mt-1.5">
            <Badge
              className="text-[11px] font-semibold"
              data-testid="chat-target"
              title="The chat follows the version you have selected"
              variant="outline"
            >
              {target.label}
            </Badge>
          </p>
        </div>
        <SheetClose asChild>
          <Button aria-label="Close chat" className="absolute top-3 right-3" size="icon-sm" type="button" variant="ghost">
            <XIcon aria-hidden="true" />
          </Button>
        </SheetClose>
        <Button
          className="absolute right-4 bottom-3"
          disabled={!messages.length || busy}
          onClick={() => onThreadChange({ messages: [], sessionId: undefined, failed: null })}
          size="xs"
          type="button"
          variant="outline"
        >
          New chat
        </Button>
      </div>
      <MessageScrollerProvider>
        <MessageScroller className="flex min-h-0 flex-1 flex-col">
          <MessageScrollerViewport className="flex-1 overflow-auto px-3.5 py-3" ref={scrollerViewportRef}>
            <MessageScrollerContent className="flex flex-col gap-2.5">
              {!messages.length && (
                <>
                  <p className="max-w-[92%] self-start rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-[13px] leading-snug text-muted-foreground">
                    Ask about the people, objects and events in this incident. Answers come from the stored report for the version you have
                    open, not from a new look at the video. Times in an answer jump to that moment.
                  </p>
                  <div className="flex flex-wrap gap-1.5">
                    {SUGGESTIONS.map((suggestion) => (
                      <Button
                        className="h-auto px-2.5 py-1 text-left text-xs font-semibold"
                        key={suggestion}
                        onClick={() => void send(suggestion, [])}
                        size="xs"
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
                  <Message align="end" className="self-end" key={message.id}>
                    <Bubble>
                      <BubbleContent className="rounded-2xl rounded-br-sm bg-primary px-3 py-2 text-[13px] leading-snug text-primary-foreground">
                        {message.content}
                      </BubbleContent>
                    </Bubble>
                  </Message>
                ) : (
                  <Message align="start" className="self-start" key={message.id}>
                    <Bubble variant="muted">
                      <BubbleContent className="rounded-2xl rounded-bl-sm bg-muted px-3 py-2 text-[13px] leading-snug text-foreground">
                        {message.source === 'video' ? (
                          // A fresh look's times are not checked against anything, so they stay plain text.
                          <p className="whitespace-pre-wrap" data-testid="chat-video-result">
                            {message.content}
                          </p>
                        ) : (
                          <AnswerText
                            content={message.content}
                            durationSeconds={durationSeconds}
                            onSeek={onSeek}
                            unsupported={message.unknownTimes}
                          />
                        )}
                        {!!message.citations?.length && (
                          <ul className="mt-2 grid gap-1.5" data-testid="chat-citations">
                            {message.citations.map((citation) => (
                              <li key={`${citation.itemId}-${citation.timestampSeconds}`}>
                                <button
                                  aria-label={`Jump to ${citationTitle(titles, citation)} at ${formatClock(citation.timestampSeconds)}`}
                                  className="grid w-full grid-cols-[52px_minmax(0,1fr)] items-center gap-2 rounded-xl border border-border bg-card p-1 text-left transition hover:border-primary focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
                                  onClick={() => onSeek(citation.timestampSeconds)}
                                  type="button"
                                >
                                  {citation.cropImageUrl ? (
                                    // eslint-disable-next-line @next/next/no-img-element -- the agent's signed crop URL, used as given
                                    // biome-ignore lint/performance/noImgElement: the agent's signed crop URL, used as given
                                    <img alt="" className="h-9 w-[52px] rounded-md bg-muted object-cover" src={citation.cropImageUrl} />
                                  ) : (
                                    <span
                                      aria-hidden="true"
                                      className="h-9 w-[52px] rounded-md bg-muted"
                                      data-testid="chat-citation-no-crop"
                                    />
                                  )}
                                  <span className="min-w-0">
                                    <b className="block truncate text-xs" data-testid="chat-citation-title">
                                      {citationTitle(titles, citation)}
                                    </b>
                                    <span className="text-[11px] text-muted-foreground">
                                      jump to {formatClock(citation.timestampSeconds)}
                                    </span>
                                  </span>
                                </button>
                              </li>
                            ))}
                          </ul>
                        )}
                        {message.insufficientEvidence && (
                          <Badge className="mt-2" data-testid="chat-insufficient" variant="secondary">
                            Not in this report
                          </Badge>
                        )}
                        {offersVideoCheck(message.videoOffer, durationSeconds) && (
                          <div className="mt-2 grid gap-1.5" data-testid="chat-video-offer">
                            <p className="text-xs">
                              {message.videoOffer?.reason} Checking the original video runs a new AI look. It can take a minute and does not
                              change the report.
                            </p>
                            <Button disabled={busy} onClick={() => void checkVideo(message)} size="xs" type="button" variant="outline">
                              Check original video
                            </Button>
                          </div>
                        )}
                        {(Boolean(message.steps?.length) ||
                          Boolean(message.applied?.length) ||
                          Boolean(message.skipped?.length) ||
                          evidenceRows(message).length > 0) && (
                          <ChatStepsView
                            applied={message.applied}
                            evidence={evidenceRows(message)}
                            skipped={message.skipped}
                            steps={message.steps}
                            wallMs={message.wallMs}
                          />
                        )}
                        <p className="mt-1.5 text-[10.5px] text-muted-foreground" data-testid="chat-answered-from">
                          {answerSourceLine(message.source, message.answeredFrom ?? '')}
                        </p>
                      </BubbleContent>
                    </Bubble>
                  </Message>
                ),
              )}
              {busy && (
                <Marker className="self-start rounded-2xl bg-muted px-3 py-2 text-xs text-muted-foreground">
                  <MarkerContent aria-label="Reading the report" role="status">
                    Reading the report…
                  </MarkerContent>
                </Marker>
              )}
              {failed && (
                <Alert
                  className="self-start rounded-2xl border-destructive/30 bg-destructive/10 px-3 py-2 text-[13px] text-destructive"
                  data-testid="chat-error"
                  variant="destructive"
                >
                  <AlertDescription>
                    {failed}{' '}
                    <button
                      className="font-semibold underline focus-visible:ring-2 focus-visible:ring-ring focus-visible:outline-hidden"
                      onClick={retry}
                      type="button"
                    >
                      Try again
                    </button>
                  </AlertDescription>
                </Alert>
              )}
            </MessageScrollerContent>
          </MessageScrollerViewport>
        </MessageScroller>
      </MessageScrollerProvider>
      <form className="flex gap-1.5 border-t border-border px-3 py-2.5" onSubmit={ask}>
        <Input
          aria-label="Question"
          className="h-8 min-w-0 flex-1 text-xs"
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
    </Card>
  );
}
