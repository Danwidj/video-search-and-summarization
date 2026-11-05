// SPDX-License-Identifier: Apache-2.0

// The lowest similarity score an evidence hit may have to be shown (decisions.md, 5 Nov). One named setting: the route
// passes it to the agent search as min_similarity, and a search that nothing passes shows "No evidence found".

/** The floor for a search with a query. A listing with no query has no score and is not cut. */
export const MIN_SIMILARITY = 0.35;
