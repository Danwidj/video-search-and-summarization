// SPDX-License-Identifier: Apache-2.0

// Row fixtures (a run's AI rows, without a reviewer version) -> RunReportRecord
// or ReportView in one step: the effective_* view rows, the Supabase report-row
// mapper, then the view builder. Import after registering ./alias-loader.mjs.

import { runReportFromRows } from '../../lib/adapters/supabase/mappers/report.ts';
import { toReportView } from '../../lib/reports/view.ts';
import { effectiveRowsOfAiRun } from './finals-database.mjs';

export const aiRunReport = (rows) => runReportFromRows(effectiveRowsOfAiRun(rows));
export const buildReportView = (rows) => toReportView(aiRunReport(rows), rows.playbackUrl);
