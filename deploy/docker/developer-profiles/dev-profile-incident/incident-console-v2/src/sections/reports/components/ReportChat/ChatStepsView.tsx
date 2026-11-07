// SPDX-License-Identifier: Apache-2.0
'use client';

import { useId, useState } from 'react';
import { ChevronDownIcon, ChevronUpIcon } from 'lucide-react';
import { Badge } from '@/components/ui/badge';
import { hasStepsOrActions, summaryLabel } from '@/lib/chat/chat-steps';
import type { AppliedAction, ChatStep, SkippedAction } from '@/modules/chat/domain/chat';

export interface ChatStepsViewProps {
  steps?: ChatStep[];
  applied?: AppliedAction[];
  skipped?: SkippedAction[];
  wallMs?: number;
  className?: string;
  defaultOpen?: boolean;
}

export function ChatStepsView({ steps = [], applied = [], skipped = [], wallMs, className, defaultOpen = false }: ChatStepsViewProps) {
  const [open, setOpen] = useState(defaultOpen);
  const contentId = useId();

  if (!hasStepsOrActions({ steps, applied, skipped })) return null;

  const stepCount = steps.length;
  const appliedCount = applied.length;
  const skippedCount = skipped.length;
  const summary = summaryLabel(stepCount, appliedCount, skippedCount);

  return (
    <div className={`mt-2 w-full border-t border-border/70 pt-2 ${className ?? ''}`} data-testid="chat-steps-view">
      <button
        aria-controls={contentId}
        aria-expanded={open}
        className="flex w-full cursor-pointer items-center justify-between gap-1.5 rounded-md py-0.5 text-left text-xs font-medium text-muted-foreground transition-colors hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring"
        data-testid="chat-steps-trigger"
        onClick={() => setOpen((prev) => !prev)}
        type="button"
      >
        <span className="flex items-center gap-1.5 font-semibold text-foreground">
          <span>What I did</span>
          {summary && (
            <Badge className="px-1.5 py-0 text-[10px] font-normal" data-testid="chat-steps-summary" variant="outline">
              {summary}
            </Badge>
          )}
        </span>
        {open ? (
          <ChevronUpIcon aria-hidden="true" className="size-3.5 text-muted-foreground shrink-0" />
        ) : (
          <ChevronDownIcon aria-hidden="true" className="size-3.5 text-muted-foreground shrink-0" />
        )}
      </button>

      {open && (
        <div className="mt-2.5 flex flex-col gap-2.5 text-xs" data-testid="chat-steps-content" id={contentId}>
          {stepCount > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">Tools used ({stepCount})</span>
              <ol className="m-0 flex list-none flex-col gap-1.5 p-0">
                {steps.map((step, index) => (
                  <li
                    className="flex flex-col gap-1 rounded-lg border border-border/70 bg-card p-2 text-xs"
                    data-testid="chat-step-item"
                    // biome-ignore lint/suspicious/noArrayIndexKey: steps are an ordered list from the agent run
                    key={`${step.tool}-${index}`}
                  >
                    <div className="flex items-center justify-between gap-1.5">
                      <span className="truncate font-mono text-[11.5px] font-semibold text-foreground" data-testid="chat-step-tool">
                        {step.tool}
                      </span>
                      <div className="flex shrink-0 items-center gap-1.5">
                        {step.ok ? (
                          <Badge className="px-1.5 py-0 text-[10px] font-medium" variant="secondary">
                            ok
                          </Badge>
                        ) : (
                          <Badge className="px-1.5 py-0 text-[10px] font-medium" variant="destructive">
                            failed
                          </Badge>
                        )}
                        <span className="text-[10.5px] tabular-nums text-muted-foreground">{step.ms} ms</span>
                      </div>
                    </div>
                    {step.args && Object.keys(step.args).length > 0 && (
                      <div className="mt-0.5">
                        <span className="text-[10.5px] text-muted-foreground">Parameters:</span>
                        <pre className="mt-0.5 max-h-32 overflow-x-auto whitespace-pre-wrap rounded bg-muted/70 p-1.5 font-mono text-[10.5px] text-foreground break-all">
                          {JSON.stringify(step.args, null, 2)}
                        </pre>
                      </div>
                    )}
                    {step.error && <p className="mt-0.5 text-[11px] font-medium text-destructive">{step.error}</p>}
                  </li>
                ))}
              </ol>
            </div>
          )}

          {appliedCount > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                Changes applied ({appliedCount})
              </span>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {applied.map((action, index) => (
                  <li
                    className="flex flex-col gap-0.5 rounded-lg border border-border/70 bg-card p-2 text-xs"
                    data-testid="chat-applied-action"
                    key={action.id ?? `${action.tool}-${index}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <Badge className="px-1.5 py-0 text-[10px] font-medium text-foreground" variant="outline">
                        Applied
                      </Badge>
                      <span className="font-mono text-xs font-semibold text-foreground">{action.tool}</span>
                    </div>
                    {action.note && <p className="mt-0.5 text-[11px] text-muted-foreground">{action.note}</p>}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {skippedCount > 0 && (
            <div className="flex flex-col gap-1.5">
              <span className="text-[11px] font-semibold tracking-wide text-muted-foreground uppercase">
                Changes skipped ({skippedCount})
              </span>
              <ul className="m-0 flex list-none flex-col gap-1.5 p-0">
                {skipped.map((action, index) => (
                  <li
                    className="flex flex-col gap-0.5 rounded-lg border border-border/70 bg-card p-2 text-xs"
                    data-testid="chat-skipped-action"
                    key={action.id ?? `${action.tool}-${index}`}
                  >
                    <div className="flex items-center gap-1.5">
                      <Badge className="px-1.5 py-0 text-[10px] font-medium text-muted-foreground" variant="secondary">
                        Skipped
                      </Badge>
                      <span className="font-mono text-xs font-semibold text-foreground">{action.tool}</span>
                    </div>
                    <p className="mt-0.5 text-[11px] text-muted-foreground">{action.reason}</p>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {typeof wallMs === 'number' && wallMs > 0 && (
            <p className="text-right text-[10.5px] tabular-nums text-muted-foreground">Total duration: {wallMs} ms</p>
          )}
        </div>
      )}
    </div>
  );
}
