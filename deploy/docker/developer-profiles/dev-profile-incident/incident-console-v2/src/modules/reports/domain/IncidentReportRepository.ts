// SPDX-License-Identifier: Apache-2.0

// IncidentReportRepository: the mvp3 port over incidents. An incident groups
// videos (real file names) and owns the append-only report revisions
// (report_revisions); a revision's payload is the envelope (see envelope.ts)
// and its coverage (videoNames) names the videos it was built from. Nothing
// here updates or deletes a revision.
//
// It sits beside IncidentRepository, which still answers the per-video
// screens; the use cases move to this port in Phase 5 and the legacy port is
// removed then.

import type { StructuredReason } from '@/modules/matching/domain/matching';
import type { ReportEnvelope } from '@/modules/reports/domain/envelope';
import type { ReportList, ReportListQuery } from '@/modules/reports/domain/IncidentRepository';
import type { EvidenceEntry, OfficialCrop, ReportPayload, RevisionKind } from '@/modules/reports/domain/revision';
import type { RunNotes } from '@/modules/reports/domain/run-notes';

/** An incident id is the database's numeric identity. */
export type IncidentId = number;

/** One card of the library: an incident's official revision, else its newest (list_incident_report_summaries). */
export interface IncidentSummary {
  incidentId: IncidentId;
  /** Null for an incident that has no revision yet. */
  revisionId: number | null;
  revisionNo: number | null;
  modelRunId: string | null;
  kind: RevisionKind | null;
  createdBy: string | null;
  note: string | null;
  title: string;
  incidentType: string;
  description: string;
  severity: number;
  /** Null when the overview carries no confidence. */
  confidence: number | null;
  /** When the shown revision was created (naive UTC, as stored). */
  generatedAt: string | null;
  uploadedAt: string | null;
  model: string;
  outcome: 'valid_first_pass' | 'valid_after_structural_repair' | 'legacy' | null;
  isOfficial: boolean;
  officialSince: string | null;
  versionCount: number;
  videoCount: number;
  firstVideoName: string | null;
  firstVideoKey: string | null;
  /** R2 key of the first video's upload-time thumbnail, as the RPC returns it (unsigned, unprefixed). */
  thumbnail: string | null;
  sensorId: string | null;
  /** The shown revision's coverage, the videos now missing from it and the covered names no longer present. */
  coverage: string[];
  missingVideos: string[];
  removedVideos: string[];
}

export type IncidentSummaryList = Omit<ReportList, 'items'> & { items: IncidentSummary[] };

/** Why a video joined its incident without a reviewer: the match score and reasons the rule acted on. */
export interface AutoJoinRecord {
  score: number;
  reasons: string[];
  /** Empty for a join recorded from text reasons only. */
  structuredReasons: StructuredReason[];
  /** Naive UTC, as stored. */
  joinedAt: string | null;
}

/** What an automatic merge records: the reasons as stored (chips when there are any, else text). */
export interface AutoJoinInput {
  score: number;
  reasons: Array<string | StructuredReason>;
}

/** One video of an incident. */
export interface IncidentVideo {
  /** The real file name. */
  videoId: string;
  /** videos.filepath: the logical R2 key (no environment prefix); null when none is recorded. */
  storageKey: string | null;
  /** Naive UTC, as stored. */
  uploadedAt: string | null;
  /** Recording time from the file's metadata (ISO 8601 with offset); a soft hint only. */
  recordedAt: string | null;
  durationSeconds: number | null;
  source: string | null;
  /** Set while the video sits in its incident because the automatic rule joined it; null otherwise. Moving it out clears it. */
  autoJoin: AutoJoinRecord | null;
}

/** One row of an incident's version list: a revision without its payload and evidence. */
export interface IncidentRevisionSummary {
  revisionId: number;
  incidentId: IncidentId;
  revisionNo: number;
  kind: RevisionKind;
  /** The reviewer of a human revision; null for an AI revision. */
  createdBy: string | null;
  createdAt: string | null;
  note: string | null;
  parentId: number | null;
  /** The run the revision derives from (a human revision inherits its parent's). */
  modelRunId: string | null;
  /** The run's model, when the run is recorded. */
  model: string | null;
  isOfficial: boolean;
  /** Coverage: the real names of the videos the revision was built from, fixed at insert. */
  videoNames: string[];
}

/** An incident with its current videos and its revisions, newest first. */
export interface IncidentRecord {
  incidentId: IncidentId;
  officialRevisionId: number | null;
  /** When the current official revision was marked (naive UTC); null with no official revision. */
  officialSince: string | null;
  createdAt: string | null;
  /** Earliest upload first, ties by name. */
  videos: IncidentVideo[];
  revisions: IncidentRevisionSummary[];
}

/** What a review card shows of an incident: its shown version's title, its video names and its first video's key. */
export interface IncidentSideSummary {
  incidentId: IncidentId;
  /** The overview title of the shown revision (official, else newest); null when it has no revision or no title. */
  title: string | null;
  /** The real file names, earliest upload first, ties by name. */
  videoNames: string[];
  /** videos.filepath of the first video (logical R2 key, no environment prefix); null when none is recorded. */
  firstVideoKey: string | null;
}

/** One stored revision in full. */
export interface IncidentRevisionRecord {
  revision: IncidentRevisionSummary;
  /** The payload as stored (the envelope, read leniently). */
  payload: ReportPayload;
  /** The payload parsed as an envelope; a payload that is not one gives no cameras. */
  envelope: ReportEnvelope;
  evidence: EvidenceEntry[];
  /** Null when the revision names no run or its run is not recorded. */
  modelRun: { modelName: string | null; promptVersion: string | null; runAt: string | null; notes: RunNotes } | null;
}

/** A searchable crop with its source video (evidence_crops is keyed by revision, video, item type and item id). */
export type IncidentCrop = OfficialCrop & { video_id: string };

/** The result of marking or clearing the official revision. */
export interface IncidentOfficialChange {
  incidentId: IncidentId;
  officialRevisionId: number | null;
  officialSince: string | null;
}

/** A human revision to append. Its coverage is its parent's. */
export interface HumanIncidentRevisionInput {
  incidentId: IncidentId;
  /** The revision the reviewer opened; it must belong to the incident. */
  parentId: number;
  /** The whole envelope, with the edited camera or overview. */
  payload: ReportPayload;
  evidence: EvidenceEntry[];
  /** Crops stored against the new revision (embedded by the caller); empty when there are none. */
  crops: IncidentCrop[];
  createdBy: string;
  note: string | null;
}

/** An AI revision to append: the envelope built from the stored analyses of exactly `videoNames`. */
export interface AiIncidentRevisionInput {
  incidentId: IncidentId;
  /** The synthesis run; its model_runs row must exist. */
  modelRunId: string;
  note: string | null;
  payload: ReportPayload;
  evidence: EvidenceEntry[];
  /** Coverage: at least one name, each currently a video of the incident. */
  videoNames: string[];
  /** The overview's search vector, or null when the embedding endpoint was unavailable. */
  embedding: number[] | null;
}

export interface CreatedAiRevision {
  revisionId: number;
  revisionNo: number;
  /** Crop rows attached from the covered videos' latest crops. */
  crops: number;
}

export interface MergeResult {
  /** The target, which is kept. */
  incidentId: IncidentId;
  sourceIncidentId: IncidentId;
  movedVideoIds: string[];
  /** R2 keys of the crops that went with the source's revisions, for the caller's sweep. */
  orphanedCropImages: string[];
}

export interface IncidentReportRepository {
  /** One filtered, sorted page of incident cards. */
  listIncidents(query: ReportListQuery): Promise<IncidentSummaryList>;
  /** The incident with its videos and revisions (with coverage names); null when it does not exist. */
  getIncident(incidentId: IncidentId): Promise<IncidentRecord | null>;
  /** The narrow read behind a review card: a few columns, no payload, evidence or run. Null when the incident does not exist. */
  getSideSummary(incidentId: IncidentId): Promise<IncidentSideSummary | null>;
  /**
   * One revision in full. With revisionId null: the official revision, else the newest. Null when the
   * incident, or that revision of it, is missing.
   */
  getRevision(incidentId: IncidentId, revisionId: number | null): Promise<IncidentRevisionRecord | null>;
  /**
   * Makes revisionId the incident's official revision (null clears it). Marking the already-official
   * revision again keeps its original officialSince. Throws StoreRejection: 'not-found' for an unknown
   * incident or a revision of another incident.
   */
  setOfficialRevision(incidentId: IncidentId, revisionId: number | null): Promise<IncidentOfficialChange>;
  /**
   * Appends a human revision with the next revision number, the given parent, the parent's run and the
   * parent's coverage. Throws StoreRejection: 'not-found' for an unknown incident or a parent that is not
   * one of its revisions, 'invalid' for content the store refuses (an empty reviewer name, a crop whose
   * video is not covered).
   */
  saveHumanRevision(input: HumanIncidentRevisionInput): Promise<IncidentRevisionSummary>;
  /**
   * Appends an AI revision whose coverage is exactly videoNames, and attaches the covered videos' latest
   * crops. Throws StoreRejection: 'not-found' for an unknown incident, 'invalid' for an empty name list or
   * a name that is not a video of the incident.
   */
  createAiRevision(input: AiIncidentRevisionInput): Promise<CreatedAiRevision>;
  /**
   * Replaces the incident's crops with `crops` against revisionId, which must be the incident's
   * searchable revision (official, else newest). Every crop names a video of the incident. Returns the
   * rows stored. Throws StoreRejection like saveHumanRevision.
   */
  setRevisionCrops(incidentId: IncidentId, revisionId: number, crops: IncidentCrop[]): Promise<number>;
  /**
   * Replaces one source video's crops (on any revision) with `crops` against revisionId; a null revisionId
   * only deletes them. The incident's other videos are untouched. Returns the rows stored.
   */
  replaceVideoCrops(incidentId: IncidentId, videoId: string, revisionId: number | null, crops: IncidentCrop[]): Promise<number>;
  /**
   * Every evidence R2 key (evidence/...) the video's stored records can still show: any string in the
   * evidence of any revision of the incident that sits in the video's evidence folder, and the image of any
   * crop whose source is the video. Null for an unknown incident or a video that is not one of its videos.
   * Throws, rather than answering with fewer keys, when a record cannot be read in full: a caller deletes
   * whatever is not listed here.
   */
  listReferencedEvidenceImages(incidentId: IncidentId, videoId: string): Promise<string[] | null>;
  /**
   * Moves the source's videos into the target and deletes the source with its revisions and crops; a
   * pending suggestion for the pair becomes accepted. The target's revisions are unchanged (its coverage
   * note will say what they lack). Throws StoreRejection: 'invalid' for the same incident twice,
   * 'not-found' for an unknown incident.
   */
  /** With `autoJoin`, the videos the merge moves also keep its score and reasons (a reviewer's merge passes none). */
  mergeIncidents(targetIncidentId: IncidentId, sourceIncidentId: IncidentId, autoJoin?: AutoJoinInput): Promise<MergeResult>;
}
