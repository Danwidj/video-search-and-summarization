// SPDX-License-Identifier: Apache-2.0

// Runs a host binary (ffmpeg, ffprobe) found on PATH, like lib/video/ffmpeg-frame.ts
// does, and reports its exit code with its captured output. Routes take the
// runner as a parameter so tests can replace it with a fake.

import { spawn } from 'node:child_process';

export interface CommandResult {
  /** null when the process was killed (timeout). */
  code: number | null;
  stdout: string;
  stderr: string;
  timedOut: boolean;
}

export interface CommandOptions {
  timeoutMs: number;
  /** stdout beyond this is dropped; ffprobe's JSON is small and ffmpeg writes nothing to stdout. */
  maxStdoutBytes?: number;
}

export type RunCommand = (command: string, args: string[], options: CommandOptions) => Promise<CommandResult>;

/** Thrown when the binary is not on PATH (ENOENT). */
export class CommandMissingError extends Error {
  readonly command: string;
  constructor(command: string) {
    super(`${command} is not installed on the console host`);
    this.name = 'CommandMissingError';
    this.command = command;
  }
}

export const runCommand: RunCommand = (command, args, { timeoutMs, maxStdoutBytes = 1024 * 1024 }) =>
  new Promise((resolve, reject) => {
    const child = spawn(command, args, { stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, timeoutMs);
    child.stdout.on('data', (chunk: Buffer) => {
      if (stdout.length < maxStdoutBytes) stdout += chunk.toString();
    });
    child.stderr.on('data', (chunk: Buffer) => {
      // Only the tail is reported, and ffmpeg's progress lines are long.
      stderr = (stderr + chunk.toString()).slice(-2000);
    });
    child.on('error', (error: NodeJS.ErrnoException) => {
      clearTimeout(timer);
      reject(error.code === 'ENOENT' ? new CommandMissingError(command) : error);
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr, timedOut });
    });
  });
