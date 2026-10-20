// SPDX-License-Identifier: Apache-2.0

// Row fixtures -> ReportView in one step: the Supabase report-row mapper, then
// the view builder. Import after registering ./alias-loader.mjs.

import { runReportFromRows } from '../../lib/adapters/supabase/mappers/report.ts';
import { toReportView } from '../../lib/reports/view.ts';

export const buildReportView = (rows) => toReportView(runReportFromRows(rows), rows.playbackUrl);
