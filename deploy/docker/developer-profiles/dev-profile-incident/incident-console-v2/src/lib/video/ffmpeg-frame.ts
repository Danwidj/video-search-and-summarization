// SPDX-License-Identifier: Apache-2.0

// Decodes one frame of a video as a JPEG with the ffmpeg on PATH, optionally
// cropped to a rectangle given as fractions of the frame. ffmpeg seeks by HTTP
// range over the signed R2 URL, so the video is never downloaded whole.

import { spawn } from 'node:child_process';

import type { FrameRegion } from '@/lib/evidence/frame-geometry';
import { FrameRequestError } from '@/lib/evidence/frame-request';

const TIMEOUT_MS = 20_000;
const MAX_JPEG_BYTES = 10 * 1024 * 1024;

/** ffmpeg arguments for one JPEG on stdout. Exported for tests. */
export function ffmpegFrameArguments(inputUrl: string, seconds: number, region: FrameRegion | null): string[] {
  const crop = region
    ? ['-vf', `crop=w=trunc(iw*${region.w}):h=trunc(ih*${region.h}):x=trunc(iw*${region.x}):y=trunc(ih*${region.y})`]
    : [];
  return [
    '-v',
    'error',
    '-nostdin',
    '-protocol_whitelist',
    'https,tls,tcp,crypto',
    '-ss',
    String(seconds),
    '-i',
    inputUrl,
    '-frames:v',
    '1',
    ...crop,
    '-c:v',
    'mjpeg',
    '-pix_fmt',
    'yuvj420p',
    '-q:v',
    '2',
    '-f',
    'image2pipe',
    'pipe:1',
  ];
}

export async function extractFrameJpeg(inputUrl: string, seconds: number, region: FrameRegion | null): Promise<Buffer> {
  return new Promise((resolve, reject) => {
    const child = spawn('ffmpeg', ffmpegFrameArguments(inputUrl, seconds, region), { stdio: ['ignore', 'pipe', 'pipe'] });
    const chunks: Buffer[] = [];
    let size = 0;
    let stderr = '';
    let settled = false;
    const finish = (action: () => void) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      action();
    };
    const timer = setTimeout(() => {
      child.kill('SIGKILL');
      finish(() => reject(new FrameRequestError(502, 'Reading the frame from the video timed out')));
    }, TIMEOUT_MS);

    child.stdout.on('data', (chunk: Buffer) => {
      size += chunk.length;
      if (size > MAX_JPEG_BYTES) {
        child.kill('SIGKILL');
        finish(() => reject(new FrameRequestError(502, 'The decoded frame is unexpectedly large')));
        return;
      }
      chunks.push(chunk);
    });
    child.stderr.on('data', (chunk: Buffer) => {
      stderr = (stderr + chunk.toString()).slice(-400);
    });
    child.on('error', (error: NodeJS.ErrnoException) =>
      finish(() =>
        reject(
          error.code === 'ENOENT'
            ? new FrameRequestError(503, 'ffmpeg is not installed on the console host, so frames cannot be extracted')
            : error,
        ),
      ),
    );
    child.on('close', (code) =>
      finish(() => {
        if (code === 0 && size > 0) resolve(Buffer.concat(chunks as unknown as Uint8Array[]));
        else if (code === 0) reject(new FrameRequestError(422, 'The video has no frame at that timestamp'));
        else reject(new FrameRequestError(502, `ffmpeg could not read the video: ${stderr.trim() || `exit code ${code}`}`));
      }),
    );
  });
}
