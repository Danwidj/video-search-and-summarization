// SPDX-License-Identifier: Apache-2.0

import type { IncidentSummary } from '@/modules/reports/domain/IncidentReportRepository';

/** One library card as /api/reports returns it: the incident summary plus the signed screenshot of its first video. */
export type LibraryIncident = IncidentSummary & { thumbnailUrl?: string };
