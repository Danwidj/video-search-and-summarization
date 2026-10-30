// SPDX-License-Identifier: Apache-2.0

// Small pure rules of the library screen's cards and Matches tab, kept apart from the components so tests can import them.

/** A card's title, led by the official version it shows so the card and the page it opens agree on which version that is. */
export function cardTitle(item: { title: string; isOfficial: boolean; revisionNo: number | null }, fallback: string): string {
  const title = item.title || fallback;
  return item.isOfficial && item.revisionNo !== null ? `Official v${item.revisionNo} · ${title}` : title;
}

/** The Matches tab's sort note; with nothing pending there is nothing to sort. */
export function matchesSortNote(pending: number): string | null {
  return pending > 0 ? `${pending} pending · highest score first` : null;
}
