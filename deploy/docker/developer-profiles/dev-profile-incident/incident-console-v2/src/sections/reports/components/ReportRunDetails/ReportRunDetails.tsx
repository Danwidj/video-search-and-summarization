// SPDX-License-Identifier: Apache-2.0
'use client';

import { Accordion, AccordionContent, AccordionItem, AccordionTrigger } from '@/components/ui/accordion';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { formatTimestamp } from '@/lib/time';
import type { ReportView } from '@/modules/reports/domain/report-view';

export function RunDetailsPanel({ report }: { report: ReportView }) {
  const { run } = report;
  const request = run.request;
  const response = run.response;
  return (
    <section className="border-t border-border px-6 py-6 sm:px-8">
      <Accordion className="w-full" collapsible type="single">
        <AccordionItem className="rounded-2xl border border-border bg-muted/40 px-5" value="run-details">
          <AccordionTrigger className="cursor-pointer py-4 text-sm font-semibold hover:no-underline">
            <span>Run &amp; model output details</span>
          </AccordionTrigger>
          <AccordionContent className="border-t border-border pt-4 pb-2">
            <dl className="grid gap-x-6 gap-y-4 text-xs sm:grid-cols-2 lg:grid-cols-4">
              <Provenance label="Model" value={run.model} />
              <Provenance label="Contract / prompt version" value={run.promptVersion || 'Legacy prompt'} />
              <Provenance label="Model run" value={run.modelRunId ?? 'Not recorded'} />
              <Provenance label="Generated" value={formatTimestamp(run.generatedAt)} />
              {run.status && (
                <Provenance
                  label="Analysis outcome"
                  value={`${OUTCOME_LABELS[run.status]}${run.statusInferred ? ' (recorded before outcomes were stored)' : ''}`}
                />
              )}
              {request && <Provenance label="Additional instruction" value={request.additionalInstruction || 'None'} />}
              {response && <Provenance label="Finish reason" value={response.finishReason || 'Not returned'} />}
              {response && <Provenance label="Token usage" value={response.usage ? JSON.stringify(response.usage) : 'Not returned'} />}
              {request?.inferenceConfig && <Provenance label="Inference settings" value={JSON.stringify(request.inferenceConfig)} />}
              {request?.promptSha256 && <Provenance label="Prompt SHA-256" value={request.promptSha256} />}
              {request?.schemaSha256 && <Provenance label="Schema SHA-256" value={request.schemaSha256} />}
              {run.notesKind === 'contract' && (
                <Provenance
                  label="Validation policy"
                  value={run.validation?.policy ?? 'Full contract validity (recorded before core-scored-v1)'}
                />
              )}
              {run.validation?.fullContractValid !== undefined && (
                <Provenance
                  label="Full contract validity (first response)"
                  value={run.validation.fullContractValid ? 'Valid' : 'Not valid: only ID or unscored-field issues'}
                />
              )}
              {request && 'videoDurationSeconds' in request && (
                <Provenance
                  label="Video length checked against"
                  value={
                    typeof request.videoDurationSeconds === 'number'
                      ? `${Number(request.videoDurationSeconds.toFixed(3))} s`
                      : 'Unknown (not checked)'
                  }
                />
              )}
            </dl>
            {run.notesKind === 'invalid-contract' && (
              <Alert className="mt-4" variant="destructive">
                <AlertDescription>The stored model output could not be re-validated: {run.notesError}</AlertDescription>
              </Alert>
            )}
            {run.notesKind === 'none' && (
              <p className="mt-4 text-xs italic text-muted-foreground">The original model output was not retained for this run.</p>
            )}
            {run.status === 'valid_after_structural_repair' && <RepairDetails run={run} />}
            {run.rawModelOutput && (
              <Block
                title={
                  run.status === 'valid_after_structural_repair'
                    ? 'Original raw model response (before ID normalization)'
                    : 'Raw model response'
                }
              >
                {run.rawModelOutput}
              </Block>
            )}
            {response?.reasoningContent && <Block title="Model reasoning">{response.reasoningContent}</Block>}
            {run.originalReport !== undefined && (
              <Block
                title={
                  run.status === 'valid_after_structural_repair'
                    ? 'Validated model output (after ID normalization)'
                    : 'Original validated model output'
                }
              >
                {JSON.stringify(run.originalReport, null, 2)}
              </Block>
            )}
            {run.legacyReviewerEdits && (
              <Block title="Reviewer edits made with the earlier editor">{JSON.stringify(run.legacyReviewerEdits, null, 2)}</Block>
            )}
          </AccordionContent>
        </AccordionItem>
      </Accordion>
    </section>
  );
}

const OUTCOME_LABELS: Record<NonNullable<ReportView['run']['status']>, string> = {
  valid_first_pass: 'Valid on first pass',
  valid_after_structural_repair: 'Valid after structural repair',
  contract_failed: 'Contract failed',
  request_failed: 'Request failed',
};

function RepairDetails({ run }: { run: ReportView['run'] }) {
  const repair = run.repair ?? {};
  const operations = Array.isArray(repair.operations) ? (repair.operations as Array<Record<string, unknown>>) : [];
  const describe = (operation: Record<string, unknown>) => {
    if (operation.op === 'reorder')
      return `Reordered ${String(operation.collection)}: ${JSON.stringify(operation.from)} → ${JSON.stringify(operation.to)}`;
    if (operation.op === 'rename-id')
      return `Renamed ${String(operation.collection)} ID ${JSON.stringify(operation.from)} → ${JSON.stringify(operation.to)}`;
    if (operation.op === 'remap-reference')
      return `Updated reference ${String(operation.path)}: ${JSON.stringify(operation.from)} → ${JSON.stringify(operation.to)}`;
    return JSON.stringify(operation);
  };
  return (
    <Alert className="mt-6 rounded-xl border border-amber-300 bg-amber-50/70 p-4 text-xs text-amber-950" data-testid="repair-details">
      <AlertTitle className="text-xs font-bold uppercase tracking-[0.12em] text-amber-800">
        Contract repair applied (IDs only) · {String(repair.ruleSet ?? '')}
      </AlertTitle>
      <AlertDescription>
        <p className="mt-2 text-inherit">
          The model&apos;s first response broke only identifier rules. Identifiers and list order were normalized; no text or value was
          changed, and the result passed validation again.
        </p>
        <p className="mt-3 font-semibold text-inherit">First-pass violations</p>
        <ul className="mt-1 list-disc pl-5">
          {(run.firstPassViolations ?? [])
            .filter((violation) => violation.scope !== 'enrichment')
            .map((violation) => (
              <li key={`${violation.code}:${violation.message}`}>
                <span className="font-mono">{violation.code}</span>: {violation.message}
              </li>
            ))}
        </ul>
        <p className="mt-3 font-semibold text-inherit">Repair operations</p>
        <ul className="mt-1 list-disc pl-5">
          {operations.map((operation) => (
            <li className="font-mono" key={describe(operation)}>
              {describe(operation)}
            </li>
          ))}
        </ul>
      </AlertDescription>
    </Alert>
  );
}

function Provenance({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="font-bold uppercase tracking-widest text-muted-foreground">{label}</dt>
      <dd className="mt-1 break-all font-mono text-foreground/80">{value}</dd>
    </div>
  );
}

function Block({ title, children }: { title: string; children: string }) {
  return (
    <div className="mt-6">
      <h4 className="text-xs font-bold uppercase tracking-[0.12em] text-muted-foreground">{title}</h4>
      <pre className="mt-2 max-h-80 overflow-auto whitespace-pre-wrap rounded-xl bg-card border border-border p-4 font-mono text-xs leading-5 text-card-foreground">
        {children}
      </pre>
    </div>
  );
}
