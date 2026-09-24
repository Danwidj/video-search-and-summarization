// SPDX-License-Identifier: Apache-2.0

export interface GatewayCompletionRequest {
  model: string;
  messages: Array<{ role: 'system' | 'user' | 'assistant'; content: unknown }>;
  stream: false;
  temperature?: number;
  max_tokens?: number;
}

export interface GatewayCompletionResponse {
  choices: Array<{ message: { role: string; content: string } }>;
  model?: string;
}

function networkErrorDetail(error: unknown): string {
  if (!(error instanceof Error)) return String(error);
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
      throw new Error(`Could not reach the VLM gateway: ${networkErrorDetail(error)}`);
    }

    if (!response.ok) {
      const detail = (await response.text()).slice(0, 1000);
      throw new Error(`VLM gateway returned HTTP ${response.status}${detail ? `: ${detail}` : ''}`);
    }
    return (await response.json()) as GatewayCompletionResponse;
  }
}
