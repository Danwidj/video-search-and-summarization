// SPDX-License-Identifier: Apache-2.0

// ModelGateway: one chat-completions call to the VLM gateway (gateway mode).
// The request and response are the OpenAI-compatible shapes the gateway
// forwards; a call that produced no usable completion throws GatewayError with
// whatever the gateway actually returned.

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

export interface ModelGateway {
  complete(request: GatewayCompletionRequest, signal?: AbortSignal): Promise<GatewayCompletionResponse>;
}
