// SPDX-License-Identifier: Apache-2.0

import { NextResponse } from 'next/server';

import { getDbAdapters } from '@/lib/container';
import { getServiceConfiguration } from '@/lib/env';
import { errorResponse } from '@/lib/http';
import { createR2PlaybackUrl } from '@/lib/r2/config';
import { buildReportMarkdown, parseReportPdfRequest } from '@/lib/reports/report-pdf-markdown';
import { listRevisions } from '@/modules/reports/application/list-revisions';
import { getReport } from '@/modules/reports/application/get-report';
import { ReportPdfError, requestReportPdf } from '@/modules/reports/infrastructure/agent/report-pdf';

export const dynamic = 'force-dynamic';
export const maxDuration = 120;

/**
 * The PDF (or the Markdown) of one version of the report. Nothing is stored: the report is not changed. The PDF is made by the
 * agent; without it the request fails with its reason, and nothing falls back to a browser print.
 */
export async function POST(request: Request, context: { params: Promise<{ videoId: string }> }) {
  try {
    const { videoId } = await context.params;
    const parsed = parseReportPdfRequest(await request.json().catch(() => null));
    if ('error' in parsed) return NextResponse.json({ error: parsed.error }, { status: 400 });

    const config = getServiceConfiguration();
    const { incidents } = getDbAdapters(config);
    const report = await getReport(incidents, videoId, parsed.revisionId, (storageKey) => createR2PlaybackUrl(config, storageKey));
    if (!report) return NextResponse.json({ error: 'Report not found' }, { status: 404 });
    const history = (await listRevisions(incidents, videoId)).map((revision) => ({
      revisionNo: revision.revisionNo,
      kind: revision.kind,
      note: revision.note,
      createdAt: revision.createdAt,
    }));
    const built = buildReportMarkdown(report, parsed.options, history, new Date().toISOString());
    const name = `${videoId}-v${report.revision.revisionNo}`;

    if (parsed.format === 'markdown') {
      return new NextResponse(built.markdown, {
        headers: {
          'content-type': 'text/markdown; charset=utf-8',
          'content-disposition': `attachment; filename="${name}.md"`,
          'cache-control': 'no-store',
        },
      });
    }

    if (!config.agentUrl) {
      return NextResponse.json({ error: 'The PDF needs the agent, and INCIDENT_AGENT_BASE_URL is not configured.' }, { status: 503 });
    }
    const { pdf, missingImages } = await requestReportPdf(
      config.agentUrl,
      { markdown: built.markdown, runningHeader: built.runningHeader, footer: built.footer },
      AbortSignal.timeout(110_000),
    );
    return new NextResponse(pdf, {
      headers: {
        'content-type': 'application/pdf',
        'content-disposition': `attachment; filename="${name}.pdf"`,
        'x-missing-images': String(missingImages),
        'cache-control': 'no-store',
      },
    });
  } catch (error) {
    if (error instanceof ReportPdfError) return NextResponse.json({ error: error.reason }, { status: error.status });
    return errorResponse(error, 'Could not make the report PDF');
  }
}
