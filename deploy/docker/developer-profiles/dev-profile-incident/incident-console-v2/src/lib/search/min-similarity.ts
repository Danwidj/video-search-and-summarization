// SPDX-License-Identifier: Apache-2.0

// The lowest similarity score an evidence hit may have to be shown (.docs/archive/decisions.md, 5 Nov). One named setting: the route
// passes it to the agent search as min_similarity, and a search that nothing passes shows "No evidence found".

/** The floor for a search with a query. A listing with no query has no score and is not cut. */
export const MIN_SIMILARITY = 0.35;

/**
 * The floor for the Find incidents text search over saved report revisions. Those scores compare the query with a report's
 * title and description, not item text, so this is a separate setting. 0.25 comes from 18 real searches over the 13 searchable
 * versions after the re-embed: unrelated queries top out at 0.17, the weakest true match scores 0.28 (.docs/archive/decisions.md, 6 Nov).
 */
export const REVISION_MIN_SIMILARITY = 0.25;
