// SPDX-License-Identifier: Apache-2.0

import { incidentAnalysisSchema, type IncidentAnalysis } from '@/lib/analysis/schema';

function findJsonObject(content: string): string {
  const unfenced = content.replace(/^```(?:json)?\s*/i, '').replace(/\s*```$/i, '').trim();
  const start = unfenced.indexOf('{');
  const end = unfenced.lastIndexOf('}');
  if (start < 0 || end <= start) throw new Error('The VLM response did not contain a JSON object');
  return unfenced.slice(start, end + 1);
}

export function parseIncidentAnalysis(content: string): IncidentAnalysis {
  let value: unknown;
  try {
    value = JSON.parse(findJsonObject(content));
  } catch (error) {
    throw new Error(`The VLM returned invalid JSON: ${error instanceof Error ? error.message : String(error)}`);
  }
  const result = incidentAnalysisSchema.safeParse(value);
  if (!result.success) throw new Error(`The VLM report did not match the required structure: ${result.error.message}`);
  return withTimelineDuration(result.data);
}

function withTimelineDuration(analysis: IncidentAnalysis): IncidentAnalysis {
  if ((analysis.duration_seconds !== null && analysis.duration_seconds !== 0) || analysis.timeline.length === 0) return analysis;
  const minStart = Math.min(...analysis.timeline.map((e) => e.start_seconds));
  const maxEnd = Math.max(...analysis.timeline.map((e) => e.end_seconds ?? e.start_seconds));
  const span = maxEnd - minStart;
  return span > 0 ? { ...analysis, duration_seconds: Math.round(span) } : analysis;
}
