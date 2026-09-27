// SPDX-License-Identifier: Apache-2.0

export interface GatewayCompletionRequest {
  model: string;
  messages: Array<{ role: 'system' | 'user' | 'assistant'; content: unknown }>;
  stream?: false;
  temperature?: number;
  max_tokens?: number;
  // OpenAI-compatible extras forwarded verbatim by vlm-gateway (e.g.
  // response_format, media_io_kwargs, chat_template_kwargs).
  [extra: string]: unknown;
}

export interface GatewayCompletionResponse {
  choices: Array<{
    message: { role: string; content: string | null; reasoning_content?: string | null };
    finish_reason?: string | null;
  }>;
  model?: string;
  usage?: Record<string, unknown>;
}

export type GatewayFailureCode =
  | 'GATEWAY_UNREACHABLE'
  | 'GATEWAY_TIMEOUT'
  | 'GATEWAY_HTTP_ERROR'
  | 'UPSTREAM_NON_JSON'
  | 'UPSTREAM_NO_COMPLETION';

/** A call that produced no usable completion, with whatever the gateway actually returned. */
export class GatewayError extends Error {
  code: GatewayFailureCode;
  httpStatus?: number;
  errorBody?: string;

  constructor(code: GatewayFailureCode, message: string, details: { httpStatus?: number; errorBody?: string } = {}) {
    super(message);
    this.name = 'GatewayError';
    this.code = code;
    if (details.httpStatus !== undefined) this.httpStatus = details.httpStatus;
    if (details.errorBody !== undefined) this.errorBody = details.errorBody;
  }
}

function networkErrorDetail(error: unknown): string {
  if (!(error instanceof Error)) return String(error);
  if (error.name === 'TimeoutError') return 'the request timed out';
  const cause = (error as Error & { cause?: unknown }).cause;
  if (!cause) return error.message;
  if (cause instanceof Error) {
    const code = (cause as Error & { code?: string }).code;
    return `${error.message}; cause=${code ? `${code}: ` : ''}${cause.message}`;
  }
  return `${error.message}; cause=${String(cause)}`;
}

export class GatewayClient {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl;
  }

  async health(signal?: AbortSignal): Promise<boolean> {
    try {
      const response = await fetch(`${this.baseUrl.replace(/\/$/, '')}/health`, { cache: 'no-store', signal });
      return response.ok;
    } catch {
      return false;
    }
  }

  async complete(request: GatewayCompletionRequest, signal?: AbortSignal): Promise<GatewayCompletionResponse> {
    let response: Response;
    try {
      response = await fetch(`${this.baseUrl.replace(/\/$/, '')}/v1/chat/completions`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(request),
        cache: 'no-store',
        signal,
      });
    } catch (error) {
      const timedOut = error instanceof Error && error.name === 'TimeoutError';
      throw new GatewayError(timedOut ? 'GATEWAY_TIMEOUT' : 'GATEWAY_UNREACHABLE', `Could not reach the VLM gateway: ${networkErrorDetail(error)}`);
    }

    if (!response.ok) {
      const detail = (await response.text().catch(() => '')).slice(0, 1000);
      throw new GatewayError('GATEWAY_HTTP_ERROR', `VLM gateway returned HTTP ${response.status}${detail ? `: ${detail}` : ''}`, { httpStatus: response.status, errorBody: detail });
    }
    let text: string;
    try {
      text = await response.text();
    } catch (error) {
      const timedOut = error instanceof Error && error.name === 'TimeoutError';
      throw new GatewayError(timedOut ? 'GATEWAY_TIMEOUT' : 'GATEWAY_UNREACHABLE', `Reading the VLM gateway response failed: ${networkErrorDetail(error)}`, { httpStatus: response.status });
    }
    let body: unknown;
    try {
      body = JSON.parse(text);
    } catch {
      throw new GatewayError('UPSTREAM_NON_JSON', 'VLM gateway returned a non-JSON response', { httpStatus: response.status, errorBody: text.slice(0, 1000) });
    }
    // A 2xx whose body is not a completion (e.g. JSON null, seen from the gateway
    // for an unfetchable video URL) is a failed call, not an empty answer.
    if (!body || typeof body !== 'object' || !Array.isArray((body as GatewayCompletionResponse).choices) || !(body as GatewayCompletionResponse).choices.length) {
      throw new GatewayError('UPSTREAM_NO_COMPLETION', `VLM gateway returned no completion: ${JSON.stringify(body).slice(0, 500)}`, { httpStatus: response.status, errorBody: JSON.stringify(body).slice(0, 1000) });
    }
    return body as GatewayCompletionResponse;
  }
}
