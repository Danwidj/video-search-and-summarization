// SPDX-License-Identifier: Apache-2.0

const path = require('path');

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: 'standalone',
  outputFileTracingRoot: path.resolve(__dirname),
  reactStrictMode: true,
};

module.exports = nextConfig;
