// SPDX-License-Identifier: Apache-2.0

// Picks the ffmpeg and ffprobe the console runs, in this order: FFMPEG_PATH or FFPROBE_PATH when set, the copy npm
// bundles (ffmpeg-static, @ffprobe-installer/ffprobe) when that file exists, else the bare name so PATH still works.
// The sources are a parameter so tests can pass fakes; the defaults read the real packages and process.env.

import { existsSync } from 'node:fs';

import ffmpegStatic from 'ffmpeg-static';
import ffprobeInstaller from '@ffprobe-installer/ffprobe';

export type HostBinary = 'ffmpeg' | 'ffprobe';

const OVERRIDE_ENV: Record<HostBinary, string> = { ffmpeg: 'FFMPEG_PATH', ffprobe: 'FFPROBE_PATH' };

export interface BinarySources {
  env: Record<string, string | undefined>;
  /** The npm-bundled path per binary; null when the package has none for this platform. */
  bundled: Record<HostBinary, string | null>;
  exists: (path: string) => boolean;
}

const defaultSources = (): BinarySources => ({
  env: process.env,
  bundled: { ffmpeg: ffmpegStatic, ffprobe: ffprobeInstaller.path },
  exists: existsSync,
});

export function resolveHostBinary(binary: HostBinary, sources: BinarySources = defaultSources()): string {
  const override = sources.env[OVERRIDE_ENV[binary]];
  if (override) return override;
  const bundled = sources.bundled[binary];
  if (bundled && sources.exists(bundled)) return bundled;
  return binary;
}
