// SPDX-License-Identifier: Apache-2.0

// IncidentVideoRepository: the videos that belong to an incident (mvp3: one incident, many
// videos), keyed by the real file name. It creates, reads, lists, removes and moves videos; the
// official report, revisions and analyses live in their own modules. R2 objects are never touched
// here: removals hand back the keys the caller must delete.

/** One row of the videos table. */
export interface IncidentVideo {
  /** The real file name after sanitising (videos.id). */
  videoId: string;
  incidentId: number;
  /** Logical R2 key, without the R2_KEY_PREFIX. */
  storageKey: string | null;
  /** When the file says it was recorded (ISO 8601 UTC); only ever a soft hint. */
  recordedAt: string | null;
  uploadedAt: string | null;
  durationSeconds: number | null;
  source: string | null;
}

export interface NewIncidentVideo {
  videoId: string;
  /** The incident to join; null starts a new incident holding just this video. */
  incidentId: number | null;
  storageKey: string | null;
  recordedAt?: string | null;
  durationSeconds?: number | null;
  source?: string | null;
}

export interface VideoRemoval {
  videoId: string;
  /** The incident the video was in. */
  incidentId: number;
  /** True when it was the incident's last video, so the incident went with it. */
  incidentDeleted: boolean;
  /** The video's logical R2 key, for the caller to delete. */
  storageKey: string | null;
  /** Image keys of the evidence crops that went with it, for the caller to delete. */
  cropImages: string[];
}

export interface VideoMove {
  videoId: string;
  /** The incident it left. */
  incidentId: number;
  newIncidentId: number;
}

export interface IncidentVideoRepository {
  /**
   * Adds a video. Throws StoreRejection: 'not-found' for an incident that does not exist,
   * 'invalid' for a video name that is already taken.
   */
  createVideo(video: NewIncidentVideo): Promise<IncidentVideo>;
  getVideo(videoId: string): Promise<IncidentVideo | null>;
  /** The incident's videos by recording time (unknown last), then name. */
  listVideos(incidentId: number): Promise<IncidentVideo[]>;
  /**
   * Deletes the video with its analyses and crops, and its run records that no revision uses; the incident's revisions stay as history. The
   * incident's last video takes the incident with it. Throws StoreRejection: 'not-found'.
   */
  removeVideo(videoId: string): Promise<VideoRemoval>;
  /**
   * Deletes an incident that holds no videos, with whatever hangs off it (revisions, suggestions).
   * Throws StoreRejection: 'not-found' for an incident that does not exist, 'invalid' for one that
   * still has videos (delete those with removeVideo).
   */
  deleteEmptyIncident(incidentId: number): Promise<void>;
  /**
   * Moves the video to a new incident of its own, analyses and crops following it. Throws
   * StoreRejection: 'not-found', or 'invalid' for the incident's last video (delete it instead).
   */
  moveVideoToNewIncident(videoId: string): Promise<VideoMove>;
}
