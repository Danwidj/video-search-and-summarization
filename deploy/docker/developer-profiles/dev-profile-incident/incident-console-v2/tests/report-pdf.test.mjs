// SPDX-License-Identifier: Apache-2.0

// The report PDF: the Markdown builder (content, options, SGT times, escaping), the request parser, and the client that
// posts the Markdown to the agent. The signed image URLs appear in the Markdown only: nothing here logs them.

import assert from 'node:assert/strict';
import test from 'node:test';

const { buildReportMarkdown, clockText, sgtText, parseReportPdfRequest, DEFAULT_REPORT_PDF_OPTIONS } = await import(
  '../src/lib/reports/report-pdf-markdown.ts'
);
const { requestReportPdf, ReportPdfError } = await import('../src/modules/reports/infrastructure/agent/report-pdf.ts');

const SIGNED = 'https://signed.r2.test/evidence/v1/E1.jpg?X-Amz-Signature=secret';

function view() {
  return {
    videoId: 'Assault050',
    revisionId: 148,
    revision: { revisionNo: 4, kind: 'human', createdBy: 'reviewer', createdAt: '2026-11-06 22:34:52', generatedAt: null },
    official: { isOfficial: true, officialRevisionId: 148 },
    structured: {
      incident: {
        type: 'assault',
        title: 'Physical confrontation',
        startSeconds: 2,
        endSeconds: 20,
        duration: 18,
        description: 'A person enters | then falls.',
        severityLevel: 4,
        severityReason: 'The fall causes harm.',
        confidenceScore: 0.8,
      },
      entities: [
        {
          entityId: 'P1',
          label: 'person in light shirt',
          type: 'person',
          description: 'light shirt',
          timestampSeconds: 1,
          firstSeenSeconds: 0,
          lastSeenSeconds: 19,
          evidence: { imageUrl: SIGNED },
        },
      ],
      instruments: [
        {
          instrumentId: 'I1',
          entityId: 'P1',
          name: 'Metal pipe',
          description: 'held low',
          timestampSeconds: 8,
          threatLevel: 4,
          evidence: null,
        },
      ],
      assets: [{ assetId: 'A1', name: 'Cardboard box', description: 'no holder', timestampSeconds: 20, evidence: null }],
    },
  };
}

test('the title is the H1 and the overview table comes first, in the captain order', () => {
  const { markdown } = buildReportMarkdown(view());
  assert.match(markdown, /^# Physical confrontation/);
  const order = ['## Overview', '## Summary', '## Severity rationale', '## Evidence', '## Timeline'].map((h) => markdown.indexOf(h));
  assert.ok(order.every((index, i) => index >= 0 && (i === 0 || index > order[i - 1])), order.join(','));
  assert.match(markdown, /\| \*\*Version\*\* \| v4, Official \|/);
  assert.match(markdown, /\| \*\*Severity\*\* \| 4\/5 \|/);
});

test('evidence is numbered across People, Instruments and Assets, with holders and what they hold', () => {
  const { markdown } = buildReportMarkdown(view());
  assert.match(markdown, /\*\*E1\*\* · person in light shirt/);
  assert.match(markdown, /\*\*E2\*\* · Metal pipe/);
  assert.match(markdown, /\*\*E3\*\* · Cardboard box/);
  assert.match(markdown, /Holds Metal pipe/);
  assert.match(markdown, /Held by person in light shirt/);
});

test('an image is a Markdown link on its item, and is left out when the option is off', () => {
  const on = buildReportMarkdown(view());
  assert.ok(on.markdown.includes(`![E1 person in light shirt, snapshot at 0:01](${SIGNED})`));
  assert.deepEqual(on.images, [{ alt: 'E1 person in light shirt, snapshot at 0:01', url: SIGNED }]);
  const off = buildReportMarkdown(view(), { ...DEFAULT_REPORT_PDF_OPTIONS, includeImages: false });
  assert.doesNotMatch(off.markdown, /!\[/);
  assert.deepEqual(off.images, []);
});

test('the timeline lists the items in time order and is on by default', () => {
  const { markdown } = buildReportMarkdown(view());
  const rows = markdown.split('\n').filter((line) => /^\| 0:\d\d \||^\| \d+:\d\d/.test(line));
  assert.match(rows[0], /^\| 0:01 \| E1/);
  assert.match(rows[rows.length - 1], /^\| 0:20 \| E3/);
  const off = buildReportMarkdown(view(), { ...DEFAULT_REPORT_PDF_OPTIONS, includeTimeline: false });
  assert.doesNotMatch(off.markdown, /## Timeline/);
});

test('the version history is off by default and shows dates in SGT when on', () => {
  const history = [{ revisionNo: 4, kind: 'human', note: 'severity', createdAt: '2026-11-06 22:34:52' }];
  assert.doesNotMatch(buildReportMarkdown(view(), DEFAULT_REPORT_PDF_OPTIONS, history).markdown, /## Version history/);
  const on = buildReportMarkdown(view(), { ...DEFAULT_REPORT_PDF_OPTIONS, includeHistory: true }, history);
  assert.match(on.markdown, /\| v4 \| Human \| 7 Nov 2026, 06:34 SGT \| severity \|/);
});

test('the running header and the footer carry the title, the version and the generated time in SGT', () => {
  const built = buildReportMarkdown(view(), DEFAULT_REPORT_PDF_OPTIONS, [], '2026-11-08T00:00:00Z');
  assert.equal(built.runningHeader, 'Incident report · Physical confrontation');
  assert.equal(built.footer, 'v4 · Official · generated 8 Nov 2026, 08:00 SGT');
});

test('a pipe in the summary is escaped so it stays in its table cell', () => {
  const built = buildReportMarkdown(view());
  assert.match(built.markdown, /A person enters \\\| then falls\./);
});

test('clock and SGT text read a missing value as not recorded', () => {
  assert.equal(clockText(0), '0:00');
  assert.equal(clockText(3725), '1:02:05');
  assert.equal(clockText(null), 'Not recorded');
  assert.equal(sgtText(null), 'Not recorded');
  assert.equal(sgtText('2026-11-06T22:34:52Z'), '7 Nov 2026, 06:34 SGT');
});

test('the request defaults to a PDF with the default options and refuses a bad format or version', () => {
  assert.deepEqual(parseReportPdfRequest({}), {
    format: 'pdf',
    revisionId: null,
    options: DEFAULT_REPORT_PDF_OPTIONS,
  });
  assert.deepEqual(parseReportPdfRequest({ format: 'markdown', revisionId: 3, options: { includeHistory: true } }), {
    format: 'markdown',
    revisionId: 3,
    options: { ...DEFAULT_REPORT_PDF_OPTIONS, includeHistory: true },
  });
  assert.ok('error' in parseReportPdfRequest({ format: 'docx' }));
  assert.ok('error' in parseReportPdfRequest({ revisionId: 0 }));
  assert.ok('error' in parseReportPdfRequest(null));
});

test('the agent client posts the Markdown and returns the PDF with its missing-image count', async () => {
  const calls = [];
  const fakeFetch = async (url, init) => {
    calls.push({ url, body: JSON.parse(init.body) });
    return new Response(new Uint8Array([37, 80, 68, 70]), { status: 200, headers: { 'x-missing-images': '2' } });
  };
  const original = globalThis.fetch;
  globalThis.fetch = fakeFetch;
  try {
    const result = await requestReportPdf('http://agent.test/', { markdown: '# x', runningHeader: 'h', footer: 'f' }, AbortSignal.timeout(5000));
    assert.equal(result.missingImages, 2);
    assert.equal(calls[0].url, 'http://agent.test/api/v1/incidents/report-pdf');
    assert.deepEqual(calls[0].body, { markdown: '# x', runningHeader: 'h', footer: 'f' });
  } finally {
    globalThis.fetch = original;
  }
});

test('an agent failure carries its reason, and an unreachable agent says so without the address', async () => {
  const original = globalThis.fetch;
  try {
    globalThis.fetch = async () =>
      new Response(JSON.stringify({ detail: 'the PDF renderer reported 1 error(s)' }), { status: 502, headers: { 'content-type': 'application/json' } });
    await assert.rejects(requestReportPdf('http://agent.test', { markdown: '#', runningHeader: '', footer: '' }, AbortSignal.timeout(5000)), (error) => {
      assert.ok(error instanceof ReportPdfError);
      assert.equal(error.reason, 'the PDF renderer reported 1 error(s)');
      return true;
    });
    globalThis.fetch = async () => {
      throw new TypeError(`fetch failed for ${SIGNED}`);
    };
    await assert.rejects(requestReportPdf('http://agent.test', { markdown: '#', runningHeader: '', footer: '' }, AbortSignal.timeout(5000)), (error) => {
      assert.equal(error.status, 503);
      assert.doesNotMatch(error.message, /secret|signed\.r2/);
      return true;
    });
  } finally {
    globalThis.fetch = original;
  }
});
