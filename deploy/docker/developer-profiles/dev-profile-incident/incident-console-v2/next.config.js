// SPDX-License-Identifier: Apache-2.0

const path = require('node:path');

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  outputFileTracingRoot: path.resolve(__dirname),
  reactStrictMode: true,
  // The ffmpeg and ffprobe binaries stay in node_modules so lib/video/host-binaries.ts can find them at runtime.
  serverExternalPackages: ['ffmpeg-static', '@ffprobe-installer/ffprobe'],
  // The listing moved to /library; old links keep working, with their query string.
  async redirects() {
    return [{ source: '/reports', destination: '/library', permanent: true }];
  },
};

module.exports = nextConfig;
