// SPDX-License-Identifier: Apache-2.0

// ffmpeg-static ships no type declarations. Its default export is the bundled ffmpeg path, or null when npm has no binary for this platform.
declare module 'ffmpeg-static' {
  const ffmpegPath: string | null;
  export default ffmpegPath;
}
