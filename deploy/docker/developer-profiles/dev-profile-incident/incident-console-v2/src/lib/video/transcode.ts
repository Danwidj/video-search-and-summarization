// SPDX-License-Identifier: Apache-2.0

// Every stored video is an H.264 MP4 at the original resolution, because the
// video model host cannot decode phone HEVC (.MOV) or 10-bit H.264 files, and a
// transcode at the original size keeps evidence frames sharp. The upload route
// probes each file with ffprobe; an MP4 that already holds 8-bit yuv420p H.264
// is stored byte for byte, anything else is converted with ffmpeg: video only
// (no audio, ever), same width, height and frame rate, faststart so the moov
// header is at the front (lib/video/mp4-duration.ts reads it by range). Both
// binaries come from lib/video/host-binaries.ts, like the frame route's ffmpeg.

import { createWriteStream } from 'node:fs';
import { mkdtemp, rm, stat } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';

import { CommandMissingError, type RunCommand, runCommand } from '@/lib/video/command';

const PROBE_TIMEOUT_MS = 60_000;
/** A 10-minute 4K phone clip at libx264 veryfast takes a few minutes on a laptop; the route allows 30. */
export const TRANSCODE_TIMEOUT_MS = 25 * 60_000;

/** What the upload route needs to know about a file, from ffprobe. */
export interface VideoProbe {
  /** `format.tags.major_brand`: `isom`, `mp42`, ... for MP4; `qt  ` for QuickTime; null when absent. */
  majorBrand: string | null;
  codec: string | null;
  pixelFormat: string | null;
  width: number | null;
  height: number | null;
  /** ffprobe's `r_frame_rate`, e.g. `30000/1001`. */
  frameRate: string | null;
  durationSeconds: number | null;
  audioStreams: number;
}

/** A refusal the route reports as is: 422 for a file ffmpeg rejects, 503 when a binary is missing. */
export class TranscodeError extends Error {
  readonly status: 422 | 503;
  constructor(status: 422 | 503, message: string) {
    super(message);
    this.name = 'TranscodeError';
    this.status = status;
  }
}

/** ffprobe arguments for the JSON the route parses. Exported for tests. */
export function ffprobeArguments(inputPath: string): string[] {
  return [
    '-v',
    'error',
    '-show_entries',
    'format_tags=major_brand:format=duration:stream=codec_type,codec_name,pix_fmt,width,height,r_frame_rate',
    '-of',
    'json',
    inputPath,
  ];
}

interface ProbeJson {
  streams?: Array<{
    codec_type?: string;
    codec_name?: string;
    pix_fmt?: string;
    width?: number;
    height?: number;
    r_frame_rate?: string;
  }>;
  format?: { duration?: string; tags?: { major_brand?: string } };
}

/** The first video stream and the container brand from ffprobe's JSON; throws when there is no video stream. */
export function parseProbe(stdout: string): VideoProbe {
  let json: ProbeJson;
  try {
    json = JSON.parse(stdout) as ProbeJson;
  } catch {
    throw new TranscodeError(422, 'ffprobe did not describe the file as a video');
  }
  const streams = json.streams ?? [];
  const video = streams.find((stream) => stream.codec_type === 'video');
  if (!video) throw new TranscodeError(422, 'The file has no video stream');
  const duration = Number(json.format?.duration);
  return {
    majorBrand: json.format?.tags?.major_brand ?? null,
    codec: video.codec_name ?? null,
    pixelFormat: video.pix_fmt ?? null,
    width: video.width ?? null,
    height: video.height ?? null,
    frameRate: video.r_frame_rate ?? null,
    durationSeconds: Number.isFinite(duration) && duration > 0 ? duration : null,
    audioStreams: streams.filter((stream) => stream.codec_type === 'audio').length,
  };
}

/**
 * The pass-through rule: an ISO MP4 (not a QuickTime `.mov`, whose brand is
 * `qt  `) whose video is 8-bit 4:2:0 H.264 is stored untouched. Everything
 * else is converted.
 */
export function isStoredFormat(probe: VideoProbe): boolean {
  const brand = probe.majorBrand?.trim().toLowerCase() ?? '';
  return brand !== '' && !brand.startsWith('qt') && probe.codec === 'h264' && probe.pixelFormat === 'yuv420p';
}

/** ffmpeg arguments for the conversion: first video stream only, no audio, same size and rate. Exported for tests. */
export function ffmpegTranscodeArguments(inputPath: string, outputPath: string): string[] {
  return [
    '-v',
    'error',
    '-nostdin',
    '-y',
    '-i',
    inputPath,
    '-map',
    '0:v:0',
    '-an',
    '-c:v',
    'libx264',
    '-preset',
    'veryfast',
    '-crf',
    '20',
    '-pix_fmt',
    'yuv420p',
    '-movflags',
    '+faststart',
    outputPath,
  ];
}

export interface PreparedUpload {
  /** The file to store: the original, or the converted MP4. */
  path: string;
  size: number;
  converted: boolean;
  probe: VideoProbe;
  /** Removes the temporary files. Safe to call more than once. */
  cleanup: () => Promise<void>;
}

const tail = (text: string) => text.trim().split('\n').slice(-3).join(' ').slice(-400);

async function probe(run: RunCommand, inputPath: string): Promise<VideoProbe> {
  const result = await run('ffprobe', ffprobeArguments(inputPath), { timeoutMs: PROBE_TIMEOUT_MS });
  if (result.code !== 0) {
    throw new TranscodeError(422, `ffprobe could not read the video: ${tail(result.stderr) || `exit code ${result.code}`}`);
  }
  return parseProbe(result.stdout);
}

async function transcode(run: RunCommand, inputPath: string, outputPath: string): Promise<void> {
  const result = await run('ffmpeg', ffmpegTranscodeArguments(inputPath, outputPath), { timeoutMs: TRANSCODE_TIMEOUT_MS });
  if (result.timedOut) {
    throw new TranscodeError(
      422,
      `Converting the video to H.264 took longer than ${TRANSCODE_TIMEOUT_MS / 60_000} minutes and was stopped`,
    );
  }
  if (result.code !== 0) {
    throw new TranscodeError(422, `ffmpeg could not convert the video: ${tail(result.stderr) || `exit code ${result.code}`}`);
  }
}

/**
 * Writes the uploaded file to a temporary directory, probes it and converts it
 * when it is not already an H.264 MP4. The caller streams `path` to R2 and then
 * calls `cleanup`; on any failure here the directory is removed before the
 * error is rethrown.
 */
export async function prepareUpload(file: Blob, options: { run?: RunCommand; tmpRoot?: string } = {}): Promise<PreparedUpload> {
  const run = options.run ?? runCommand;
  const dir = await mkdtemp(path.join(options.tmpRoot ?? tmpdir(), 'incident-upload-'));
  const cleanup = () => rm(dir, { recursive: true, force: true });
  try {
    const inputPath = path.join(dir, 'input');
    await pipeline(Readable.fromWeb(file.stream() as Parameters<typeof Readable.fromWeb>[0]), createWriteStream(inputPath));

    const probed = await probe(run, inputPath);
    if (isStoredFormat(probed)) {
      return { path: inputPath, size: file.size, converted: false, probe: probed, cleanup };
    }

    const outputPath = path.join(dir, 'output.mp4');
    await transcode(run, inputPath, outputPath);
    const { size } = await stat(outputPath);
    if (size <= 0) throw new TranscodeError(422, 'ffmpeg produced an empty file');
    return { path: outputPath, size, converted: true, probe: probed, cleanup };
  } catch (error) {
    await cleanup();
    if (error instanceof CommandMissingError) {
      throw new TranscodeError(503, `${error.command} is not installed on the console host, so uploads cannot be converted`);
    }
    throw error;
  }
}
