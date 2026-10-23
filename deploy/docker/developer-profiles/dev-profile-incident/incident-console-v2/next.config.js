// SPDX-License-Identifier: Apache-2.0

const path = require('path');

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  outputFileTracingRoot: path.resolve(__dirname),
  reactStrictMode: true,
  // The listing moved to /library; old links keep working, with their query string.
  async redirects() {
    return [{ source: '/reports', destination: '/library', permanent: true }];
  },
};

module.exports = nextConfig;
