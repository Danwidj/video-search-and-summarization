// SPDX-License-Identifier: Apache-2.0

// The shared P1 -> RP1 call pattern (.docs/prompt-contract-plan.md §4), identical to eval/ and vss-agent:
// P1 = one video (signed URL) first, then the contract prompt, schema enforced via response_format;
// RP1 = text-only report from the validated P1 JSON. No repair calls, no retries on invalid output.

import { contractPart, type IncidentContractReport } from '@/lib/analysis/contract-types';
import {
  extractionPrompt,
  p1Request,
  parseContractContent,
  reportPromptTemplate,
  responseFormat,
  rp1Request,
} from '@/lib/analysis/contract';
import type { GatewayClient, GatewayCompletionRequest } from '@/lib/gateway/client';

export function p1CompletionRequest(model: string, videoUrl: string): GatewayCompletionRequest {
  return {
    model,
    messages: [
      {
        role: 'user',
        content: [
          { type: 'video_url', video_url: { url: videoUrl } },
          { type: 'text', text: extractionPrompt() },
        ],
      },
    ],
    stream: false,
    ...p1Request(),
    response_format: responseFormat(),
  };
}

export function rp1CompletionRequest(report: IncidentContractReport): GatewayCompletionRequest {
  const { model, ...settings } = rp1Request();
  const prompt = reportPromptTemplate().replace('{structured_incident_json}', JSON.stringify(contractPart(report), null, 2));
  return { model, messages: [{ role: 'user', content: prompt }], stream: false, ...settings };
}

export interface P1Result {
  report: IncidentContractReport;
  rawModelOutput: string;
  model: string;
}

/** One P1 call, parsed strictly. Throws (ContractError for contract violations) instead of repairing. */
export async function runP1(gateway: GatewayClient, model: string, videoUrl: string): Promise<P1Result> {
  const completion = await gateway.complete(p1CompletionRequest(model, videoUrl));
  const choice = completion.choices[0];
  const content = choice?.message.content ?? '';
  if (!content && choice?.finish_reason === 'length') {
    throw new Error('The VLM ran out of tokens before returning the report (finish_reason=length)');
  }
  return { report: parseContractContent(content), rawModelOutput: content, model: completion.model || model };
}

export interface RP1Result {
  reportText?: string;
  reportTextError?: string;
}

/** One RP1 call. Never throws: a failed prose report must not discard a valid P1 report. */
export async function runRP1(gateway: GatewayClient, report: IncidentContractReport): Promise<RP1Result> {
  try {
    const completion = await gateway.complete(rp1CompletionRequest(report));
    const text = completion.choices[0]?.message.content?.trim();
    if (!text) return { reportTextError: 'RP1 returned no final content' };
    return { reportText: text };
  } catch (error) {
    return { reportTextError: error instanceof Error ? error.message : String(error) };
  }
}
