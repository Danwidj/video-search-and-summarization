// SPDX-License-Identifier: Apache-2.0

// Report view types and browser-safe helpers. Built server-side by
// lib/reports/view.ts (which reads notes and validates the contract); this
// module must not import server-only code.
//
// The report view: three sources, never merged into one another.
// - Class A (structured): the relational projection (incidents, entities,
//   instruments, assets). This is the current, reviewer-editable state.
// - Class B (modelOutput): read-only fields from the immutable original model
//   report in model_runs.notes (title, severity rationale, location, timeline,
//   uncertainties), plus the model's original structured values so edits can
//   be shown against them.
// - Class C (run): run and provenance metadata.

import type { ReviewStatus } from '@/lib/reports/storage';
import type { ContractRunRequest, ContractRunResponse } from '@/lib/reports/run-notes';

export interface StructuredIncident {
  type: string | null;
  startSeconds: number | null;
  endSeconds: number | null;
  duration: number | null;
  description: string | null;
  severityLevel: number | null;
  confidenceScore: number | null;
}

export interface StructuredEntity { entityId: string; type: string; description: string }
export interface StructuredInstrument { instrumentId: string; entityId: string | null; name: string; description: string; threatLevel: number | null }
export interface StructuredAsset { assetId: string; name: string; description: string }

export interface TimelineEvent { startSeconds: number; endSeconds: number | null; description: string }

export interface ModelOutput {
  source: 'contract' | 'legacy';
  title: string | null;
  location: string | null;
  severityReason: string | null;
  timeline: TimelineEvent[];
  uncertainties: string[];
  /** The model's own structured values, for comparison with the (possibly edited) projection. */
  original: { type: string | null; severityLevel: number | null; startSeconds: number | null; endSeconds: number | null; description: string | null };
}

export interface RunDetails {
  videoId: string;
  modelRunId: string;
  reportId: string;
  filename: string;
  playbackUrl: string;
  model: string;
  promptVersion: string | null;
  generatedAt: string;
  notesKind: 'contract' | 'failed-attempt' | 'invalid-contract' | 'legacy' | 'none';
  /** Contract runs only: how the stored report was obtained. */
  status?: 'valid_first_pass' | 'valid_after_structural_repair' | 'contract_failed' | 'request_failed';
  statusInferred?: boolean;
  firstPassViolations?: Array<{ code: string; path: string; message: string }>;
  repair?: Record<string, unknown> | null;
  notesError?: string;
  request?: ContractRunRequest;
  response?: ContractRunResponse;
  rawModelOutput?: string;
  originalReport?: unknown;
  legacyReviewerEdits?: Record<string, unknown>;
}

export interface ReportView {
  videoId: string;
  modelRunId: string;
  structured: { incident: StructuredIncident; entities: StructuredEntity[]; instruments: StructuredInstrument[]; assets: StructuredAsset[] };
  modelOutput: ModelOutput | null;
  run: RunDetails;
  review: { status: ReviewStatus; verifiedBy?: string; verifiedAt?: string; editedBy?: string; editedAt?: string };
  /** Where the current structured values differ from the model's original ones. */
  differences: { type?: { model: string; current: string }; severity?: { model: number; current: number }; fields: string[] };
}

/** Heading: the model's title when it gave one, else "<Type> report". */
export function reportHeading(view: ReportView): string {
  return view.modelOutput?.title || `${view.structured.incident.type ? view.structured.incident.type[0].toUpperCase() + view.structured.incident.type.slice(1) : 'Incident'} report`;
}
