// SPDX-License-Identifier: Apache-2.0

import type { IncidentId } from '@/modules/reports/domain/IncidentReportRepository';

/** A route's incident id segment as the database identity: a positive whole number written in digits only, else null. */
export function parseIncidentId(raw: string): IncidentId | null {
  if (!/^[1-9][0-9]{0,15}$/.test(raw)) return null;
  const id = Number(raw);
  return Number.isSafeInteger(id) ? id : null;
}
