// SPDX-License-Identifier: Apache-2.0

/** @type {import('tailwindcss').Config} */
module.exports = {
  content: ['./app/**/*.{ts,tsx}', './components/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        ink: '#12211b',
        canvas: '#f3f5ef',
        signal: '#76b900',
        moss: '#174f3b',
        clay: '#d9754c',
      },
      fontFamily: {
        sans: ['Arial', 'Helvetica', 'sans-serif'],
        mono: ['"SFMono-Regular"', 'Consolas', 'monospace'],
      },
      boxShadow: {
        panel: '0 24px 70px rgba(18, 33, 27, 0.10)',
      },
    },
  },
  plugins: [],
};
