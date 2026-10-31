// SPDX-License-Identifier: Apache-2.0

// Get report: one revision's view for the report page, with its video and
// evidence images (the whole frame and the crop) and person tracks signed for the browser.

import type { IncidentRepository } from '@/modules/reports/domain/IncidentRepository';
import type { ReportView } from '@/modules/reports/domain/report-view';
import { toReportView } from '@/modules/reports/application/report-view';
import type { SignStorageKey } from '@/modules/reports/application/types';

/** Signs each item's frame, image and track so the browser can show them; one that cannot be signed is shown as missing. */
async function withImageUrls(view: ReportView, sign: SignStorageKey): Promise<ReportView> {
  const signed = new Map<string, string | null>();
  const urlOf = async (image: string | null | undefined) => {
    if (!image) return null;
    if (!signed.has(image)) signed.set(image, await sign(image).catch(() => null));
    return signed.get(image) ?? null;
  };
  const items = [...view.structured.entities, ...view.structured.instruments, ...view.structured.assets];
  await Promise.all(
    items.map(async (item) => {
      if (item.evidence) {
        const [imageUrl, frameUrl, trackUrl] = await Promise.all([
          urlOf(item.evidence.image),
          urlOf(item.evidence.frame),
          urlOf(item.evidence.track),
        ]);
        item.evidence = { ...item.evidence, imageUrl, frameUrl, trackUrl };
      }
    }),
  );
  return view;
}

/** One revision's report view (revisionId null: the official revision, else the newest); null when the video or revision is missing. */
export async function getReport(
  incidents: IncidentRepository,
  videoId: string,
  revisionId: number | null,
  sign: SignStorageKey,
): Promise<ReportView | null> {
  const record = await incidents.getRevision(videoId, revisionId);
  if (!record) return null;
  if (!record.video.storageKey) throw new Error('The report has no linked R2 video');
  return withImageUrls(toReportView(record, await sign(record.video.storageKey)), sign);
}
