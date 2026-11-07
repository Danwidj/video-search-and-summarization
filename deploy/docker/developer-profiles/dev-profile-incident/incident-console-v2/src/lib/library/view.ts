// SPDX-License-Identifier: Apache-2.0

// Small pure rules of the library screen's cards, kept apart from the components so tests can import them.

/** A card's title: the report's own title, or the fallback when it has none. The Official pill carries the status, so the title does not. */
export function cardTitle(item: { title: string }, fallback: string): string {
  return item.title || fallback;
}
