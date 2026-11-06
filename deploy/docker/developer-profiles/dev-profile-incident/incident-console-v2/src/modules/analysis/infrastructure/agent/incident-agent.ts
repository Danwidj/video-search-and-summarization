// SPDX-License-Identifier: Apache-2.0

// IncidentAgent over HTTP: POST /api/v1/incidents/{videoId}/analyze on the
// native vss-agent. Only a network failure or a timeout is thrown (as
// AgentRequestError); every HTTP answer is returned for the caller to judge.

import http from 'node:http';
import https from 'node:https';

import {
  AgentRequestError,
  type AgentAnalyzeRequest,
  type AgentHttpResponse,
  type IncidentAgent,
} from '@/modules/analysis/domain/IncidentAgent';

/** The agent accepts only a finite length above zero; anything else is left for it to read itself. */
function isUsableDuration(seconds: number | null): seconds is number {
  return typeof seconds === 'number' && Number.isFinite(seconds) && seconds > 0;
}

export class HttpIncidentAgent implements IncidentAgent {
  private readonly baseUrl: string;

  constructor(baseUrl: string) {
    this.baseUrl = baseUrl.replace(/\/$/, '');
  }

  async analyze(request: AgentAnalyzeRequest, signal: AbortSignal): Promise<AgentHttpResponse> {
    return this.post(
      `${this.baseUrl}/api/v1/incidents/${request.videoId}/analyze`,
      {
        video_url: request.videoUrl,
        video_key: request.videoKey,
        model_run_id: request.modelRunId,
        model: request.model,
        skip_rp1: true,
        ...(request.additionalInstruction ? { reviewer_prompt: request.additionalInstruction } : {}),
        ...(isUsableDuration(request.videoDurationSeconds) ? { video_duration_seconds: request.videoDurationSeconds } : {}),
      },
      signal,
    );
  }

  /**
   * node:http, not fetch: Node's fetch (undici) gives up on a response that sends no headers for 300 s, whatever the
   * AbortSignal says, and the agent sends nothing until it has saved the report. node:http has no such limit, so
   * the signal (the analysis limit) is the only clock.
   */
  private post(endpoint: string, body: Record<string, unknown>, signal: AbortSignal): Promise<AgentHttpResponse> {
    const payload = Buffer.from(JSON.stringify(body));
    const send = endpoint.startsWith('https:') ? https.request : http.request;
    return new Promise((resolve, reject) => {
      const fail = (error: unknown) => {
        const reason: unknown = signal.aborted ? signal.reason : error;
        const isTimeout = reason instanceof Error && reason.name === 'TimeoutError';
        const message = reason instanceof Error ? reason.message : String(reason);
        reject(new AgentRequestError(isTimeout ? 'AGENT_TIMEOUT' : 'AGENT_FETCH_FAILED', message));
      };
      const req = send(
        endpoint,
        { method: 'POST', headers: { 'Content-Type': 'application/json', 'Content-Length': payload.length }, signal },
        (res) => {
          let text = '';
          res.setEncoding('utf8');
          res.on('data', (chunk: string) => {
            text += chunk;
          });
          res.on('error', fail);
          res.on('end', () => {
            const status = res.statusCode ?? 0;
            resolve({
              status,
              ok: status >= 200 && status < 300,
              statusText: res.statusMessage ?? '',
              text,
            });
          });
        },
      );
      req.on('error', fail);
      req.end(payload);
    });
  }
}
