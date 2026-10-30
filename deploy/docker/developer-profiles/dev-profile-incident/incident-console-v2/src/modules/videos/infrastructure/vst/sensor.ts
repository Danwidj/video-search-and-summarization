// SPDX-License-Identifier: Apache-2.0

// Removes a video's camera (sensor) from VST, which keeps one per upload and holds at most 100.

import type { ServiceConfiguration } from '@/lib/env';

const TIMEOUT_MS = 30_000;

export interface VstSensorTarget {
  /** The real file name (videos.id). */
  videoId: string;
  /** The VST sensor id the upload returned (videos.source); null for a row that never stored it. */
  sensorId: string | null;
}

/** The name VST gives the sensor of an uploaded file: the file name without its extension. */
export const vstSensorName = (videoId: string): string => videoId.replace(/\.[^./]+$/, '');

async function vstFetch(url: string, method: 'GET' | 'DELETE'): Promise<Response> {
  return fetch(url, { method, cache: 'no-store', signal: AbortSignal.timeout(TIMEOUT_MS) });
}

/** The id of the one sensor named exactly `name`; null when there is none, an error when several share it. */
async function resolveSensorId(base: string, name: string): Promise<string | null> {
  const response = await vstFetch(`${base}/vst/api/v1/sensor/list`, 'GET');
  if (!response.ok) throw new Error(`VST sensor list returned HTTP ${response.status}`);
  const sensors = (await response.json()) as Array<{ sensorId?: unknown; name?: unknown }>;
  const matches = sensors.filter((sensor) => sensor.name === name && typeof sensor.sensorId === 'string');
  if (matches.length > 1) throw new Error(`VST has ${matches.length} sensors named ${name}; refusing to guess which to delete`);
  return (matches[0]?.sensorId as string | undefined) ?? null;
}

/**
 * Deletes exactly one sensor: the stored sensor id, or for a row without one the single sensor whose
 * name equals the video's name. A sensor VST no longer has (404) counts as removed, so a repeated
 * delete finishes. Any other answer throws.
 */
export async function removeVstSensor(config: ServiceConfiguration, target: VstSensorTarget): Promise<void> {
  const base = (config.vstUrl ?? config.agentUrl)?.replace(/\/$/, '');
  if (!base) throw new Error('INCIDENT_VST_BASE_URL is not configured');
  const sensorId = target.sensorId ?? (await resolveSensorId(base, vstSensorName(target.videoId)));
  if (!sensorId) return;
  const response = await vstFetch(`${base}/vst/api/v1/sensor/${encodeURIComponent(sensorId)}`, 'DELETE');
  if (response.ok || response.status === 404) return;
  throw new Error(`VST sensor delete returned HTTP ${response.status}: ${(await response.text()).slice(0, 200)}`);
}
