# MVP2 Task Specification: Hexagonal Architecture for `incident-console-v2`

## 1. Overview & Objectives

This workstream restructures `incident-console-v2` using hexagonal architecture (ports and adapters) to cleanly decouple the Next.js frontend UI from database access and transport details.

### Context
Before this workstream, Next.js API route handlers in `incident-console-v2/app/api/*` directly instantiated `PostgrestClient` (from `lib/postgrest/client.ts`), passed raw PostgREST parameters (`select=...` with embedded resources, `eq.` / `in.(...)` / `like.` filters, `order=...`) and RPC argument names (`p_*`), and mapped table rows directly within HTTP route handlers. `PostgrestClient` is a hand-written `fetch` client (`selectOne`, `selectMany`, `selectPage`, `selectIn`, `selectContaining`, `upsert`, `insertIfAbsent`, `deleteWhere`, `rpc`, `insertIncident`); there is no supabase-js `.from()` builder and supabase-js is not a dependency. This couples the presentation layer directly to Supabase PostgREST transport and database schema specifics, and some routes return rows or RPC JSON to the browser with only a TypeScript cast, so the API does not translate data properly.

Components (`components/*`) are client code that only call `/api/*`; they never touch the database and keep consuming domain types over HTTP.

### Objectives
1. **Decouple UI from Database Transport:** Define clean domain ports (`lib/ports/`) representing the business capabilities required by the console (incidents, dashboard analytics, video management, search, and health).
2. **Implement Supabase PostgREST Adapters:** Implement secondary adapters (`lib/adapters/supabase/`) that encapsulate `PostgrestClient`, query parameter construction, error translation, and data mapping (snake_case rows and RPC JSON to camelCase domain types, and back).
3. **Refactor Route Handlers:** Update `app/api/*` route handlers to interact exclusively with domain ports via the adapter factory `getDbAdapters()`. Routes that combine several steps (report detail, review status change, delete) go through thin use cases in `lib/application/`; single-call routes call a port directly.
4. **Prepare Extension Points for MVP2:** Define the search port for MVP2 features (`evidence_crops`, `query_results`, created by https://github.com/Danwidj/video-search-and-summarization/pull/126), enabling the database workstream to plug in seamlessly. Search is keyword-first (§3.1).

The ports, use cases and adapters together are the console's middle layer between the frontend and Supabase (the "controller" in the 16 Oct meeting notes). It lives inside the app, under `incident-console-v2/lib/`.

---

## 2. Architecture & Directory Layout

```
incident-console-v2/
  app/api/**/route.ts             # Driving adapter: HTTP parsing/validation and status codes only
  lib/
    ports/                        # Domain types and driven-port interfaces (route handlers depend on these)
      common.ts                   # RunKey, Page<T>, StoreRejection (domain refusal)
      incidents.ts                # IncidentRepository (run reports, reviews, structured edits, run deletes)
      dashboard.ts                # DashboardRepository (full get_incident_dashboard query and result)
      videos.ts                   # VideoRepository (video listings, official selection, whole-video delete)
      search.ts                   # EvidenceSearchRepository (MVP2 keyword search, crops, feedback, history)
      health.ts                   # HealthRepository (database liveness)
      index.ts                    # Barrel exports and DbAdapters
    application/                  # Thin use cases for multi-step routes (depend on ports only)
      reports.ts                  # getReport, changeReviewStatus, deleteReport
    adapters/                     # Secondary adapters (infrastructure implementations)
      supabase/                   # Supabase PostgREST adapter implementation
        incidents.ts              # SupabaseIncidentAdapter implements IncidentRepository
        videos.ts                 # SupabaseVideoAdapter implements VideoRepository
        health.ts                 # SupabaseHealthAdapter implements HealthRepository
        mappers/                  # row <-> domain and RPC JSON -> domain translation (only place with column names)
        client.ts                 # PostgrestClient wrapper and service-role configuration
        index.ts                  # Factory functions getDbAdapters() and getDbHealth()
      memory/                     # In-memory fakes of each port, for use-case tests
```

`SupabaseDashboardAdapter` and `SupabaseEvidenceSearchAdapter` are added with the routes that use them (§7); an adapter is never shipped without a caller.

**Dependency rules** (checked by `tests/architecture.test.mjs`):
1. `app/api/**` reaches the database only through `@/lib/adapters/supabase` (the factory), never `@/lib/postgrest/*` or another adapter module.
2. `lib/ports/**` holds type-only imports (apart from the `StoreRejection` class in `common.ts`), so ports stay browser-safe.
3. `lib/application/**` never imports `lib/adapters`, `lib/postgrest`, `lib/r2` or `lib/gateway`; R2 work is passed in as functions.
4. Only `lib/adapters/supabase/**` imports `lib/postgrest/client` as a value. Callers not yet migrated are listed in the test's allow-list (§7).
5. incident-contract-v3 shapes (`lib/contract/types.ts`, `StructuredEdit`) keep their snake_case keys: they mirror the JSON Schema shared with eval and the agent. Translation applies to database shapes, not to that contract.

---

## 3. Concrete Port & Adapter Specifications

### 3.1 Domain Ports (`lib/ports/`)

Existing browser-safe domain types are reused rather than duplicated: `ReportView` (`lib/reports/report-view.ts`), `ReportLibraryItem` and `ReviewStatus` (`lib/reports/storage.ts`), `DashboardAnalytics` (`lib/dashboard/types.ts`), `StructuredEdit` (`lib/reports/edit-draft.ts`) and `RunNotes` (`lib/reports/run-notes.ts`).

#### `lib/ports/common.ts`
```typescript
/** One analysis of one video: incidents, evidence, review_status and reports all key on this pair. */
export interface RunKey {
  videoId: string;      // videos.id, which equals incidents.incident_id (1 video = 1 incident)
  modelRunId: string;
}

export interface Page<T> {
  items: T[];
  totalItems: number;
}

/** A domain refusal by the store; adapters translate transport errors into this. */
export class StoreRejection extends Error {
  reason: 'not-found' | 'invalid';
}
```

#### `lib/ports/incidents.ts`
```typescript
import type { RunKey } from '@/lib/ports/common';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import type { StructuredAsset, StructuredEntity, StructuredIncident, StructuredInstrument } from '@/lib/reports/report-view';
import type { RunNotes } from '@/lib/reports/run-notes';
import type { ReviewStatus } from '@/lib/reports/storage';

/** One review_status row: three statuses plus who verified and edited the report, and when. */
export interface ReviewState {
  status: ReviewStatus;            // 'unreviewed' | 'under review' | 'verified'
  verifiedBy: string | null;
  verifiedAt: string | null;
  editedBy: string | null;
  editedAt: string | null;
}

/** Everything stored for one run, already translated; the use case builds the ReportView from it. */
export interface RunReportRecord {
  key: RunKey;
  video: { storageKey: string | null; filename: string; official: { officialRunId: string | null; selectedBy: string | null; selectedAt: string | null } };
  modelRun: { modelName: string | null; promptVersion: string | null; runAt: string | null; notes: RunNotes };
  incident: StructuredIncident;
  entities: StructuredEntity[];
  instruments: StructuredInstrument[];
  assets: StructuredAsset[];
  review: ReviewState | null;
  report: { reportId: string | null; generatedAt: string | null } | null;
}

export interface StructuredEditResult {
  incidentId: string;
  modelRunId: string;
  editedBy: string;
  editedAt: string;
  duration: number;
}

export interface IncidentRepository {
  getRunReport(key: RunKey): Promise<RunReportRecord | null>;   // null when the run, its video or its incident is missing
  runExists(key: RunKey): Promise<boolean>;
  getReview(key: RunKey): Promise<ReviewState | null>;
  saveReview(key: RunKey, review: ReviewState): Promise<void>;
  applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult>;
  deleteRun(key: RunKey): Promise<void>;                         // evidence, review and report rows cascade
}
```

Every run-scoped method takes a `RunKey`: one video has many runs, and `incidents` is keyed by `(incident_id, model_run_id)`. Report-library listing (`list_incident_report_summaries`) joins this port when `app/api/reports/route.ts` moves (§7).

#### `lib/ports/dashboard.ts`
```typescript
import type { DashboardAnalytics } from '@/lib/dashboard/types';

/** get_incident_dashboard's full filter set, validated and resolved by the route. */
export interface DashboardQuery {
  periodStart: Date | null;        // null for all time; the adapter formats naive UTC
  periodEnd: Date | null;
  type: string | null;
  severity: 'low' | 'medium' | 'high' | null;
  dayOfWeek: number | null;
  hour: number | null;
  timezone: string;
}

export interface DashboardRepository {
  /** Everything the dashboard shows today: totals, video counts, previous period, severity and review funnels,
   *  per-type details, trend, heatmap, confidence buckets, rankings, threat levels and model coverage. */
  getDashboard(query: DashboardQuery): Promise<DashboardAnalytics>;
}
```

#### `lib/ports/videos.ts`
```typescript
import type { Page } from '@/lib/ports/common';

export type VideoListFilter = 'all' | 'without-report' | 'awaiting-selection';

export interface VideoListItem {
  videoId: string;
  filename: string;
  uploadedAt: string | null;
  source: string | null;
  analysesWithReport: number;
  officialRunId: string | null;
}

export interface VideoRecord {
  videoId: string;
  storageKey: string | null;       // videos.filepath as stored (an R2 key for uploads; validate with isValidR2Key)
  uploadedAt: string | null;
  source: string | null;
  officialRunId: string | null;
}

export interface OfficialSelection { videoId: string; officialRunId: string; selectedBy: string; selectedAt: string }
export interface OfficialClearance { videoId: string; officialRunId: null; clearedBy: string }

export interface VideoRepository {
  listVideos(filter: VideoListFilter, page: number, pageSize: number): Promise<Page<VideoListItem>>;
  getVideo(videoId: string): Promise<VideoRecord | null>;
  /** Throws StoreRejection: 'not-found' for an unknown video, 'invalid' for a run that cannot be official. */
  selectOfficialRun(videoId: string, modelRunId: string, selectedBy: string): Promise<OfficialSelection>;
  clearOfficialRun(videoId: string, clearedBy: string): Promise<OfficialClearance>;
  /** Deletes the video row (incidents, evidence, reviews, reports and gt_* cascade), then the run records that name only this video. Never touches R2. */
  deleteVideo(videoId: string): Promise<void>;
}
```

Official selection is explicit and needs a reviewer name (`select_official_report` / `clear_official_report`); analysis never sets it.

#### `lib/ports/search.ts` (MVP2 Extension Port)
```typescript
import type { RunKey } from '@/lib/ports/common';

export type EvidenceItemType = 'entity' | 'instrument' | 'asset';

export interface EvidenceCropItem {
  incidentId: string;              // incidents.incident_id == videos.id (VARCHAR(20), not a UUID)
  modelRunId: string;
  itemType: EvidenceItemType;
  itemId: string;
  itemName: string;
  description: string;
  threatLevel: number | null;
  holderEntityId: string | null;
  timestampSeconds: number;
  boundingBox: [number, number, number, number] | null;   // detector output; may be absent (search-contract-v1)
  imageKey: string;                // R2 key of the crop; signed server-side, never sent raw to the browser
  similarityScore?: number;        // relevance score on search hits (text rank in keyword mode)
}

export interface SearchEvidenceParams {
  queryText: string;               // required: keyword (full-text) search and the audit record use it
  queryEmbedding?: number[];       // optional: absent in keyword mode
  topK?: number;
  minSimilarity?: number;
  alpha?: number;
  itemTypes?: EvidenceItemType[];
  incidentTypes?: string[];
  minSeverity?: number;
  maxSeverity?: number;
}

export interface SearchQueryRecord {
  queryId: string;
  queryText: string;
  submittedAt: string;
  results: Array<{ resultId: string; rank: number; similarityScore: number; item: EvidenceCropItem; feedback: 'helpful' | 'unhelpful' | null }>;
}

export interface EvidenceSearchRepository {
  searchEvidenceItems(params: SearchEvidenceParams): Promise<Array<EvidenceCropItem & { evidenceCropId: string; similarityScore: number }>>;
  getEvidenceCrops(key: RunKey): Promise<EvidenceCropItem[]>;
  recordQuery(query: { queryId: string; queryText: string; queryEmbedding?: number[]; results: Array<{ resultId: string; evidenceCropId: string; rank: number; similarityScore: number }> }): Promise<void>;
  saveFeedback(params: { resultId: string; queryId: string; feedback: 'helpful' | 'unhelpful'; notes?: string }): Promise<void>;
  getQueryHistory(params?: { limit?: number }): Promise<SearchQueryRecord[]>;
}
```

Search goes straight to Supabase (decided 2026-10-17). It is **keyword-only for now**: Postgres full-text ranking over `item_name` and `description`, with no embedding provider, because hosted embeddings cost money. `queryEmbedding` is optional so a free in-process embedding model can be added later without changing the port; when one is added it must be the same model and dimension that embedded `evidence_crops.embedding`. This needs `search_evidence_items` (PR 126) to accept a null embedding and rank by text alone. Under this design the console is the only writer of `queries` / `query_results`; writes are insert-only with caller-generated ids, and feedback updates only the feedback columns of a row matched by result and query id.

#### `lib/ports/health.ts`
```typescript
/** Database liveness only; /api/health still checks the agent, the gateway and R2 itself and returns booleans only. */
export interface DatabaseHealth {
  configured: boolean;
  reachable: boolean;
}

export interface HealthRepository {
  checkHealth(): Promise<DatabaseHealth>;
}
```

---

## 4. What Moves Out of UI / Route Code

1. **`PostgrestClient` Instantiation:**
   Direct instantiation (`new PostgrestClient(...)`) is removed from `app/api/*`.
2. **Raw PostgREST Query Construction:**
   Table names, filters (`eq.`, `in.(...)`, `like.`), embedded selects, ordering and RPC argument names (`p_*`) are encapsulated inside `lib/adapters/supabase/`.
3. **Schema Mapping & Normalization:**
   Database row mapping to domain models (snake_case columns to camelCase domain types, decoding `model_runs.notes`, normalising legacy values) moves into `lib/adapters/supabase/mappers/`. RPC JSON is mapped field by field instead of passed through with a cast.
4. **Error Translation:**
   Database refusals become `StoreRejection` in the adapter (e.g. a failed run chosen as the official report), so routes no longer parse PostgREST error text.
5. **Adapter Factory Pattern:**
   Route handlers obtain dependencies via `getDbAdapters()`; multi-step routes hand the ports to a use case:
   ```typescript
   // Refactored route handler in app/api/reports/[videoId]/route.ts
   import { NextResponse } from 'next/server';
   import { getDbAdapters } from '@/lib/adapters/supabase';
   import { getReport } from '@/lib/application/reports';
   import { getServiceConfiguration } from '@/lib/env';
   import { createR2PlaybackUrl } from '@/lib/r2/config';

   export async function GET(request: Request, context: { params: Promise<{ videoId: string }> }) {
     const { videoId } = await context.params;
     const modelRunId = new URL(request.url).searchParams.get('run');
     if (!modelRunId) return NextResponse.json({ error: 'A model run ID is required' }, { status: 400 });
     const config = getServiceConfiguration();
     const { incidents } = getDbAdapters(config);
     const report = await getReport(incidents, { videoId, modelRunId }, (key) => createR2PlaybackUrl(config, key));
     if (!report) return NextResponse.json({ error: 'Report not found' }, { status: 404 });
     return NextResponse.json({ report });
   }
   ```
6. **Implementation notes:**
   - `getDbAdapters()` builds adapters per call (reading configuration at request time) and throws `Supabase PostgREST is not configured` exactly where routes used to check configuration. `getDbHealth()` is separate because `/api/health` must report an unconfigured database instead of throwing.
   - `npm test` runs TypeScript through Node's type stripping: adapters declare fields instead of using constructor parameter properties, type-only imports use `import type`, and barrels name types explicitly (TypeScript 4.9 has no `export type *`). `tests/support/alias-loader.mjs` resolves `@/...` directory imports to `index.ts`.

---

## 5. Workstream Task Checklist

- [x] **Define Domain Ports (`lib/ports/`):**
  - [x] Create `lib/ports/common.ts` (`RunKey`, `Page`, `StoreRejection`).
  - [x] Create `lib/ports/incidents.ts` (`IncidentRepository`).
  - [x] Create `lib/ports/dashboard.ts` (`DashboardRepository`).
  - [x] Create `lib/ports/videos.ts` (`VideoRepository`).
  - [x] Create `lib/ports/search.ts` (`EvidenceSearchRepository`).
  - [x] Create `lib/ports/health.ts` (`HealthRepository`).
  - [x] Create `lib/ports/index.ts` exporting all port interfaces.
- [ ] **Implement Supabase PostgREST Adapters (`lib/adapters/supabase/`):**
  - [x] Create `lib/adapters/supabase/client.ts` encapsulating service-role client configuration.
  - [x] Create `lib/adapters/supabase/incidents.ts` implementing `IncidentRepository`.
  - [ ] Create `lib/adapters/supabase/dashboard.ts` implementing `DashboardRepository` (with the dashboard route, §7).
  - [x] Create `lib/adapters/supabase/videos.ts` implementing `VideoRepository`.
  - [ ] Create `lib/adapters/supabase/search.ts` implementing `EvidenceSearchRepository` (after PR 126's tables exist, §7).
  - [x] Create `lib/adapters/supabase/health.ts` implementing `HealthRepository`.
  - [x] Create `lib/adapters/supabase/index.ts` providing `getDbAdapters()` and `getDbHealth()`.
- [x] **Add thin use cases (`lib/application/`)** for report detail, review status change and delete.
- [ ] **Refactor API Routes (`app/api/*`):**
  - [x] Refactor `app/api/health/route.ts`.
  - [ ] Refactor `app/api/dashboard/route.ts` (deferred, §7).
  - [x] Refactor `app/api/videos/route.ts` and `app/api/videos/[videoId]/official/route.ts`.
  - [ ] Refactor `app/api/reports/route.ts` (deferred, §7).
  - [x] Refactor `app/api/reports/[videoId]/route.ts`, `review`, `edit` and `delete`.
  - [ ] `app/api/reports/[videoId]/ground-truth`, `app/api/videos/[videoId]/runs`, `app/api/analysis` and `lib/analysis/*` (deferred, §7).
- [x] **Testing & Quality Assurance:**
  - [x] Characterisation tests for responses no test pinned (report detail, review, the videos list), written against the unrefactored routes.
  - [x] Contract suites that run the same cases against the in-memory fake and the Supabase adapter (over `tests/support/fake-postgrest.mjs`).
  - [x] Architecture test enforcing the dependency rules, with an allow-list of callers not yet migrated.
  - [x] Verify existing test suite passes unmodified apart from import paths: `npm run test`.
  - [x] Verify production Next.js build passes cleanly: `npm run build`.

---

## 6. Definition of Done

For the whole workstream:
- Domain ports created under `incident-console-v2/lib/ports/`; Supabase adapters under `incident-console-v2/lib/adapters/supabase/`.
- Every `app/api/*` database access goes through `getDbAdapters()` / `getDbHealth()` and the ports, and no file outside `lib/adapters/supabase/**` imports `lib/postgrest/client` as a value (including `lib/analysis/*`).
- Every route test that existed before the refactor passes unmodified apart from import paths; characterisation tests exist for routes that had none; each port has a contract suite; the architecture test has an empty allow-list.
- `npm run typecheck`, `npm test` and `npm run build` pass without errors.

This round meets these for every route not listed in §7; the routes in §7 stay in the architecture test's allow-list until they move.

---

## 7. Deferred in this round

Decided 2026-10-17:
- **Dashboard and report library** (`app/api/dashboard/route.ts`, `app/api/reports/route.ts`): unchanged until a teammate's lazy-loading change (summary-only report list RPC, pagination, skeleton placeholders) lands, to avoid conflicting edits. `DashboardRepository` is defined; its adapter and the report-list method arrive with those routes. Their responses still carry snake_case keys built in SQL (`incident_type`, `reviews.under_review`) and unchecked casts; the adapters will map them.
- **Ground truth** (`app/api/reports/[videoId]/ground-truth`, its page and the `gt_*` tables): untouched; no ground-truth port. Its GET still returns raw rows.
- **Analysis saving and run history** (`app/api/analysis`, `lib/analysis/*`, `app/api/videos/[videoId]/runs`): unchanged for now; they move into the middle layer later, together with the planned separation of human-verified and AI-generated reports.
- **Search adapter and route**: the port is defined (keyword-first, §3.1); `SupabaseEvidenceSearchAdapter` and a console search route follow once PR 126's `evidence_crops`, `query_results` and `search_evidence_items` exist on `main`. No embedding provider is wired.
