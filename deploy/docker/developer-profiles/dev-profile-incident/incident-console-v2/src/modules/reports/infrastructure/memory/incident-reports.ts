// SPDX-License-Identifier: Apache-2.0

// In-memory IncidentReportRepository for use-case tests. It implements the
// semantics the Supabase adapter owns: revisions are append-only and numbered
// per incident; a human revision takes its parent's run and coverage; an AI
// revision names its coverage and copies the covered videos' latest crops;
// getRevision with no id reads the official revision, else the newest; crops
// must name a video of the incident; setRevisionCrops accepts only the
// searchable revision; a merge moves the source's videos and deletes the source.
// The library is derived from the stored state; paging, scope, kind and
// newest/oldest order are modelled, and any other filter is refused rather
// than ignored.

import { readStoredReasons } from '@/modules/matching/domain/matching';
import { parseEnvelope } from '@/modules/reports/domain/envelope';
import type { ReportListQuery } from '@/modules/reports/domain/IncidentRepository';
import type {
  AutoJoinInput,
  AiIncidentRevisionInput,
  CreatedAiRevision,
  HumanIncidentRevisionInput,
  IncidentCrop,
  IncidentId,
  IncidentOfficialChange,
  IncidentRecord,
  IncidentReportRepository,
  IncidentRevisionRecord,
  IncidentRevisionSummary,
  IncidentSideSummary,
  IncidentSummary,
  IncidentSummaryList,
  IncidentVideo,
  MergeResult,
} from '@/modules/reports/domain/IncidentReportRepository';
import { evidenceFolder, type EvidenceEntry, type ReportPayload } from '@/modules/reports/domain/revision';
import { StoreRejection } from '@/modules/shared/domain/common';

/** Stored timestamps are naive UTC, as Postgres returns them. */
const storedNow = () => new Date().toISOString().replace('Z', '');

const UNMODELLED_FILTERS = [
  'search',
  'type',
  'severity',
  'generatedAfter',
  'generatedBefore',
  'timeFrom',
  'timeTo',
  'entities',
  'instruments',
  'assets',
  'dayOfWeek',
  'entityTypes',
] as const;

export interface StoredIncident {
  incidentId: IncidentId;
  officialRevisionId: number | null;
  officialSince: string | null;
  createdAt: string | null;
}

export interface StoredIncidentVideo extends IncidentVideo {
  incidentId: IncidentId;
}

/** One revision as stored: the version-list row (isOfficial is derived), the payload and the evidence. */
export interface StoredIncidentRevision {
  revision: Omit<IncidentRevisionSummary, 'isOfficial'>;
  payload: ReportPayload;
  evidence: EvidenceEntry[];
}

export interface StoredIncidentCrop extends IncidentCrop {
  revisionId: number;
}

export interface IncidentSeed {
  incidents?: StoredIncident[];
  videos?: StoredIncidentVideo[];
  revisions?: StoredIncidentRevision[];
  crops?: StoredIncidentCrop[];
  /** Recorded model runs, id to model name. */
  modelRuns?: Record<string, string>;
}

const refuse = (reason: 'not-found' | 'invalid', message: string): never => {
  throw new StoreRejection(reason, message);
};

export class InMemoryIncidentReportRepository implements IncidentReportRepository {
  readonly incidents: StoredIncident[];
  readonly videos: StoredIncidentVideo[];
  /** Every revision of every incident, oldest first. */
  readonly revisions: StoredIncidentRevision[];
  crops: StoredIncidentCrop[];
  readonly modelRuns: Map<string, string>;
  readonly saved: HumanIncidentRevisionInput[] = [];
  now = storedNow;
  private nextRevisionId: number;

  constructor(seed: IncidentSeed = {}) {
    this.incidents = (seed.incidents ?? []).map((incident) => ({ ...incident }));
    this.videos = (seed.videos ?? []).map((video) => ({ ...video, autoJoin: video.autoJoin ?? null }));
    this.revisions = [...(seed.revisions ?? [])];
    this.crops = (seed.crops ?? []).map((crop) => ({ ...crop }));
    this.modelRuns = new Map(Object.entries(seed.modelRuns ?? {}));
    this.nextRevisionId = Math.max(0, ...this.revisions.map((row) => row.revision.revisionId)) + 1;
  }

  private incident(incidentId: IncidentId): StoredIncident | undefined {
    return this.incidents.find((incident) => incident.incidentId === incidentId);
  }

  private incidentOrRefuse(incidentId: IncidentId): StoredIncident {
    return this.incident(incidentId) ?? refuse('not-found', `Incident not found: ${incidentId}`);
  }

  private ofIncident(incidentId: IncidentId): StoredIncidentRevision[] {
    return this.revisions.filter((row) => row.revision.incidentId === incidentId);
  }

  private videosOf(incidentId: IncidentId): StoredIncidentVideo[] {
    return this.videos.filter((video) => video.incidentId === incidentId);
  }

  /** The official revision, else the newest (searchable_revision_id). */
  private searchable(incidentId: IncidentId): number | null {
    const official = this.incident(incidentId)?.officialRevisionId ?? null;
    if (official !== null) return official;
    const all = this.ofIncident(incidentId);
    return all.length ? all.reduce((a, b) => (b.revision.revisionNo > a.revision.revisionNo ? b : a)).revision.revisionId : null;
  }

  private summary(row: StoredIncidentRevision, official: number | null): IncidentRevisionSummary {
    return { ...row.revision, videoNames: [...row.revision.videoNames], isOfficial: official === row.revision.revisionId };
  }

  private checkCrops(incidentId: IncidentId, crops: IncidentCrop[], covered?: string[]): void {
    const here = new Set(this.videosOf(incidentId).map((video) => video.videoId));
    for (const crop of crops) {
      if (!here.has(crop.video_id) || (covered && !covered.includes(crop.video_id))) {
        refuse('invalid', `Crop video is not a covered video of this incident: ${crop.video_id}`);
      }
    }
  }

  /** evidence_crops keeps one row per (revision, video, item type, item id). */
  private storeCrops(revisionId: number, crops: IncidentCrop[]): number {
    const unique = new Map<string, IncidentCrop>();
    for (const crop of crops) {
      if (crop.image.trim() && crop.item_id.trim()) unique.set(`${crop.video_id}\u0000${crop.item_type}\u0000${crop.item_id}`, crop);
    }
    for (const crop of unique.values()) this.crops.push({ ...crop, revisionId });
    return unique.size;
  }

  async listIncidents(query: ReportListQuery): Promise<IncidentSummaryList> {
    const unmodelled: string[] = UNMODELLED_FILTERS.filter((name) => query[name] !== null);
    if (query.sort !== 'newest' && query.sort !== 'oldest') unmodelled.push(`sort ${query.sort}`);
    if (unmodelled.length) throw new Error(`InMemoryIncidentReportRepository does not model: ${unmodelled.join(', ')}`);
    const cards = this.incidents
      .map((incident) => this.card(incident))
      .filter((card) => (query.scope !== 'official' || card.isOfficial) && (query.kind === null || card.kind === query.kind));
    const direction = query.sort === 'oldest' ? 1 : -1;
    cards.sort((a, b) => direction * (a.generatedAt ?? '').localeCompare(b.generatedAt ?? '') || a.incidentId - b.incidentId);
    const size = Math.min(Math.max(query.pageSize, 1), 1000);
    const start = (Math.max(query.page, 1) - 1) * size;
    return {
      items: cards.slice(start, start + size),
      totalItems: cards.length,
      incidentTypes: [...new Set(cards.map((card) => card.incidentType).filter(Boolean))].sort(),
    };
  }

  private card(incident: StoredIncident): IncidentSummary {
    const shownId = this.searchable(incident.incidentId);
    const shown = this.revisions.find((row) => row.revision.revisionId === shownId) ?? null;
    const videos = this.videosOf(incident.incidentId).sort(
      (a, b) => (a.uploadedAt ?? '').localeCompare(b.uploadedAt ?? '') || a.videoId.localeCompare(b.videoId),
    );
    const names = videos.map((video) => video.videoId);
    const coverage = shown?.revision.videoNames ?? [];
    const overview = shown ? parseEnvelope(shown.payload).overview : null;
    return {
      incidentId: incident.incidentId,
      revisionId: shown?.revision.revisionId ?? null,
      revisionNo: shown?.revision.revisionNo ?? null,
      modelRunId: shown?.revision.modelRunId ?? null,
      kind: shown?.revision.kind ?? null,
      createdBy: shown?.revision.createdBy ?? null,
      note: shown?.revision.note ?? null,
      title: overview?.title ?? '',
      incidentType: overview?.type?.toLowerCase() ?? '',
      description: overview?.description ?? '',
      severity: overview?.severity_level ?? 1,
      confidence: null,
      generatedAt: shown?.revision.createdAt ?? null,
      uploadedAt: videos[0]?.uploadedAt ?? null,
      model: shown?.revision.modelRunId ? (this.modelRuns.get(shown.revision.modelRunId) ?? '') : '',
      outcome: null,
      isOfficial: incident.officialRevisionId !== null,
      officialSince: incident.officialSince,
      versionCount: this.ofIncident(incident.incidentId).length,
      videoCount: videos.length,
      firstVideoName: videos[0]?.videoId ?? null,
      firstVideoKey: videos[0]?.storageKey ?? null,
      thumbnail: null,
      sensorId: null,
      coverage: [...coverage],
      missingVideos: names.filter((name) => !coverage.includes(name)),
      removedVideos: coverage.filter((name) => !names.includes(name)),
    };
  }

  async getIncident(incidentId: IncidentId): Promise<IncidentRecord | null> {
    const incident = this.incident(incidentId);
    if (!incident) return null;
    return {
      incidentId,
      officialRevisionId: incident.officialRevisionId,
      officialSince: incident.officialSince,
      createdAt: incident.createdAt,
      videos: this.videosOf(incidentId)
        .map(({ incidentId: _incidentId, ...video }) => video)
        .sort((a, b) => (a.uploadedAt ?? '').localeCompare(b.uploadedAt ?? '') || a.videoId.localeCompare(b.videoId)),
      revisions: this.ofIncident(incidentId)
        .sort((a, b) => b.revision.revisionNo - a.revision.revisionNo)
        .map((row) => this.summary(row, incident.officialRevisionId)),
    };
  }

  async getSideSummary(incidentId: IncidentId): Promise<IncidentSideSummary | null> {
    const incident = await this.getIncident(incidentId);
    if (!incident) return null;
    const shown = await this.getRevision(incidentId, null);
    return {
      incidentId,
      title: shown?.envelope.overview.title ?? null,
      videoNames: incident.videos.map((video) => video.videoId),
      firstVideoKey: incident.videos[0]?.storageKey ?? null,
    };
  }

  async getRevision(incidentId: IncidentId, revisionId: number | null): Promise<IncidentRevisionRecord | null> {
    const incident = this.incident(incidentId);
    if (!incident) return null;
    const wanted = revisionId ?? this.searchable(incidentId);
    const row = this.ofIncident(incidentId).find((candidate) => candidate.revision.revisionId === wanted);
    if (!row) return null;
    const runId = row.revision.modelRunId;
    const modelName = runId ? (this.modelRuns.get(runId) ?? null) : null;
    return {
      revision: this.summary(row, incident.officialRevisionId),
      payload: row.payload,
      envelope: parseEnvelope(row.payload),
      evidence: row.evidence,
      modelRun: runId && this.modelRuns.has(runId) ? { modelName, promptVersion: null, runAt: null, notes: { kind: 'none' } } : null,
    };
  }

  async setOfficialRevision(incidentId: IncidentId, revisionId: number | null): Promise<IncidentOfficialChange> {
    const incident = this.incidentOrRefuse(incidentId);
    if (revisionId !== null && !this.ofIncident(incidentId).some((row) => row.revision.revisionId === revisionId)) {
      refuse('not-found', `Revision not found for this incident: ${revisionId}`);
    }
    if (revisionId === null) incident.officialSince = null;
    else if (incident.officialRevisionId !== revisionId || incident.officialSince === null) incident.officialSince = this.now();
    incident.officialRevisionId = revisionId;
    return { incidentId, officialRevisionId: revisionId, officialSince: incident.officialSince };
  }

  async saveHumanRevision(input: HumanIncidentRevisionInput): Promise<IncidentRevisionSummary> {
    this.incidentOrRefuse(input.incidentId);
    const parent =
      this.ofIncident(input.incidentId).find((row) => row.revision.revisionId === input.parentId) ??
      refuse('not-found', `Revision not found for this incident: ${input.parentId}`);
    const by = input.createdBy.trim();
    if (!by || by.length > 256) refuse('invalid', 'A reviewer name of 1 to 256 characters is required');
    const payload = input.payload as Record<string, unknown>;
    if (typeof payload.overview !== 'object' || payload.overview === null || !Array.isArray(payload.cameras)) {
      refuse('invalid', 'The report payload must be an object with an overview and a list of cameras');
    }
    const covered = parent.revision.videoNames;
    this.checkCrops(input.incidentId, input.crops, covered);
    this.saved.push(input);
    const row: StoredIncidentRevision = {
      revision: {
        revisionId: this.nextRevisionId++,
        incidentId: input.incidentId,
        revisionNo: Math.max(0, ...this.ofIncident(input.incidentId).map((candidate) => candidate.revision.revisionNo)) + 1,
        kind: 'human',
        createdBy: by,
        createdAt: this.now(),
        note: input.note?.trim() || null,
        parentId: parent.revision.revisionId,
        modelRunId: parent.revision.modelRunId,
        model: parent.revision.model,
        videoNames: [...covered],
      },
      payload: input.payload,
      evidence: input.evidence,
    };
    this.revisions.push(row);
    this.storeCrops(row.revision.revisionId, input.crops);
    return this.summary(row, this.incident(input.incidentId)?.officialRevisionId ?? null);
  }

  async createAiRevision(input: AiIncidentRevisionInput): Promise<CreatedAiRevision> {
    this.incidentOrRefuse(input.incidentId);
    if (!input.videoNames.length) refuse('invalid', 'A revision must cover at least one video');
    const here = new Set(this.videosOf(input.incidentId).map((video) => video.videoId));
    for (const name of input.videoNames) {
      if (!name.trim() || !here.has(name)) refuse('invalid', `Video ${name} is not in incident ${input.incidentId}`);
    }
    if (!this.modelRuns.has(input.modelRunId)) refuse('not-found', `Model run not found: ${input.modelRunId}`);
    const row: StoredIncidentRevision = {
      revision: {
        revisionId: this.nextRevisionId++,
        incidentId: input.incidentId,
        revisionNo: Math.max(0, ...this.ofIncident(input.incidentId).map((candidate) => candidate.revision.revisionNo)) + 1,
        kind: 'ai',
        createdBy: null,
        createdAt: this.now(),
        note: input.note?.trim() || null,
        parentId: null,
        modelRunId: input.modelRunId,
        model: this.modelRuns.get(input.modelRunId) ?? null,
        videoNames: [...new Set(input.videoNames)],
      },
      payload: input.payload,
      evidence: input.evidence,
    };
    this.revisions.push(row);
    // The covered videos' latest crops (the highest revision that holds any) follow onto the new revision.
    let copied = 0;
    for (const video of row.revision.videoNames) {
      const mine = this.crops.filter((crop) => crop.video_id === video);
      const latest = Math.max(-1, ...mine.map((crop) => crop.revisionId));
      const rows = mine.filter((crop) => crop.revisionId === latest && latest !== row.revision.revisionId);
      copied += this.storeCrops(row.revision.revisionId, rows);
    }
    return { revisionId: row.revision.revisionId, revisionNo: row.revision.revisionNo, crops: copied };
  }

  async setRevisionCrops(incidentId: IncidentId, revisionId: number, crops: IncidentCrop[]): Promise<number> {
    this.incidentOrRefuse(incidentId);
    if (revisionId !== this.searchable(incidentId)) {
      refuse(
        'invalid',
        `Revision ${revisionId} is not the searchable revision of incident ${incidentId} (the official revision, else the newest)`,
      );
    }
    this.checkCrops(incidentId, crops);
    const here = new Set(this.videosOf(incidentId).map((video) => video.videoId));
    this.crops = this.crops.filter((crop) => !here.has(crop.video_id));
    return this.storeCrops(revisionId, crops);
  }

  async replaceVideoCrops(incidentId: IncidentId, videoId: string, revisionId: number | null, crops: IncidentCrop[]): Promise<number> {
    if (!this.videosOf(incidentId).some((video) => video.videoId === videoId))
      refuse('invalid', `Video ${videoId} is not in incident ${incidentId}`);
    if (revisionId !== null && !this.ofIncident(incidentId).some((row) => row.revision.revisionId === revisionId)) {
      refuse('invalid', `Revision ${revisionId} is not in incident ${incidentId}`);
    }
    this.crops = this.crops.filter((crop) => crop.video_id !== videoId);
    return revisionId === null
      ? 0
      : this.storeCrops(
          revisionId,
          crops.map((crop) => ({ ...crop, video_id: videoId })),
        );
  }

  async listReferencedEvidenceImages(incidentId: IncidentId, videoId: string): Promise<string[] | null> {
    const video = this.videosOf(incidentId).find((candidate) => candidate.videoId === videoId);
    if (!video) return null;
    const keys = new Set<string>();
    const folder = video.storageKey ? evidenceFolder(video.storageKey) : null;
    const collect = (value: unknown): void => {
      if (typeof value === 'string') {
        if (folder && value.startsWith(folder)) keys.add(value);
      } else if (Array.isArray(value)) value.forEach(collect);
      else if (value && typeof value === 'object') Object.values(value).forEach(collect);
    };
    for (const row of this.ofIncident(incidentId)) collect(row.evidence);
    for (const crop of this.crops) if (crop.video_id === videoId && crop.image.startsWith('evidence/')) keys.add(crop.image);
    return [...keys];
  }

  async mergeIncidents(targetIncidentId: IncidentId, sourceIncidentId: IncidentId, autoJoin?: AutoJoinInput): Promise<MergeResult> {
    if (targetIncidentId === sourceIncidentId) refuse('invalid', 'An incident cannot be merged into itself');
    this.incidentOrRefuse(targetIncidentId);
    this.incidentOrRefuse(sourceIncidentId);
    const moved = this.videosOf(sourceIncidentId);
    for (const video of moved) {
      video.incidentId = targetIncidentId;
      // As auto_merge_incidents: a moved video that already carries a record keeps it.
      if (autoJoin && !video.autoJoin) {
        const { reasons, structuredReasons } = readStoredReasons(autoJoin.reasons);
        video.autoJoin = { score: autoJoin.score, reasons, structuredReasons, joinedAt: new Date().toISOString() };
      }
    }
    const sourceRevisions = new Set(this.ofIncident(sourceIncidentId).map((row) => row.revision.revisionId));
    const orphaned = this.crops.filter((crop) => sourceRevisions.has(crop.revisionId)).map((crop) => crop.image);
    this.crops = this.crops.filter((crop) => !sourceRevisions.has(crop.revisionId));
    for (let at = this.revisions.length - 1; at >= 0; at--) {
      if (sourceRevisions.has(this.revisions[at].revision.revisionId)) this.revisions.splice(at, 1);
    }
    this.incidents.splice(
      this.incidents.findIndex((incident) => incident.incidentId === sourceIncidentId),
      1,
    );
    return {
      incidentId: targetIncidentId,
      sourceIncidentId,
      movedVideoIds: moved.map((video) => video.videoId),
      orphanedCropImages: [...new Set(orphaned)],
    };
  }
}
