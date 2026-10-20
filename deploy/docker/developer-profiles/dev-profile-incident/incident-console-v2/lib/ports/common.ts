// SPDX-License-Identifier: Apache-2.0

// Domain vocabulary shared by the console's driven ports (lib/ports/*). Port
// modules import types only, never server code, so they stay browser-safe and
// a component may import a domain type from here.

/** One analysis of one video: incidents, evidence, review_status and reports all key on this pair. */
export interface RunKey {
  /** videos.id, which equals incidents.incident_id (1 video = 1 incident). */
  videoId: string;
  modelRunId: string;
}

/** One page of a listing plus the exact total across all pages. */
export interface Page<T> {
  items: T[];
  totalItems: number;
}

/**
 * A request the store refused for a domain reason (e.g. a failed run chosen as
 * the official report). Adapters translate transport errors into this, so route
 * handlers never parse PostgREST error text.
 */
export class StoreRejection extends Error {
  reason: 'not-found' | 'invalid';

  constructor(reason: 'not-found' | 'invalid', message: string) {
    super(message);
    this.name = 'StoreRejection';
    this.reason = reason;
  }
}
