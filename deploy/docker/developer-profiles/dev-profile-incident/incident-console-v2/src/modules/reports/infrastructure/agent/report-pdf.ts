// SPDX-License-Identifier: Apache-2.0

/**
 * Posts a report's Markdown to the agent, which fetches the evidence images itself and returns the PDF. The image URLs are
 * signed: nothing here logs them, and a failure names only the agent's reason.
 */

export class ReportPdfError extends Error {
  readonly reason: string;
  readonly status: number;

  constructor(reason: string, status: number) {
    super(reason);
    this.reason = reason;
    this.status = status;
  }
}

export interface AgentPdf {
  pdf: ArrayBuffer;
  missingImages: number;
}

export async function requestReportPdf(
  agentUrl: string,
  input: { markdown: string; runningHeader: string; footer: string },
  signal: AbortSignal,
): Promise<AgentPdf> {
  let response: Response;
  try {
    response = await fetch(`${agentUrl.replace(/\/$/, '')}/api/v1/incidents/report-pdf`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(input),
      signal,
    });
  } catch {
    throw new ReportPdfError('The agent could not be reached, so the PDF was not made. Try again.', 503);
  }
  if (!response.ok) {
    const detail = (await response.json().catch(() => null)) as { detail?: unknown } | null;
    const reason = typeof detail?.detail === 'string' ? detail.detail : 'The agent could not make the PDF. Try again.';
    throw new ReportPdfError(reason, response.status === 422 ? 422 : 502);
  }
  return { pdf: await response.arrayBuffer(), missingImages: Number(response.headers.get('x-missing-images') ?? 0) };
}
