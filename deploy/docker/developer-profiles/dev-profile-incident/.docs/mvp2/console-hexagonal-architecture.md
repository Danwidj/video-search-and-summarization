# MVP2 Task Specification: Hexagonal Architecture for `incident-console-v2`

## 1. Overview & Objectives

This workstream restructures `incident-console-v2` using hexagonal architecture (ports and adapters) to cleanly decouple the Next.js frontend UI from database access and transport details.

### Context
Before this workstream, Next.js API route handlers in `incident-console-v2/app/api/*` directly instantiated `PostgrestClient` (from `lib/postgrest/client.ts`), passed raw PostgREST parameters (`select=...` with embedded resources, `eq.` / `in.(...)` / `like.` filters, `order=...`) and RPC argument names (`p_*`), and mapped table rows directly within HTTP route handlers. `PostgrestClient` is a hand-written `fetch` client (`selectOne`, `selectMany`, `selectPage`, `selectIn`, `selectContaining`, `upsert`, `insertIfAbsent`, `deleteWhere`, `rpc`, `insertIncident`); there is no supabase-js `.from()` builder and supabase-js is not a dependency. This couples the presentation layer directly to Supabase PostgREST transport and database schema specifics, and some routes return rows or RPC JSON to the browser with only a TypeScript cast, so the API does not translate data properly.

Components (`components/*`) are client code: they never touch the database. Most still call `/api/*` and consume domain types over HTTP; read pages are moving to Server Components that load through the same use cases and pass the domain types as props (§8).

### Objectives
1. **Decouple UI from Database Transport:** Define clean domain ports (`lib/ports/`) representing the business capabilities required by the console (incidents, dashboard analytics, video management, search, and health).
2. **Implement Supabase PostgREST Adapters:** Implement secondary adapters (`lib/adapters/supabase/`) that encapsulate `PostgrestClient`, query parameter construction, error translation, and data mapping (snake_case rows and RPC JSON to camelCase domain types, and back).
3. **Refactor Route Handlers:** Update `app/api/*` route handlers to interact exclusively with domain ports via the adapter factory `getDbAdapters()`. Routes that combine several steps (report detail, review status change, delete) go through thin use cases in `lib/application/`; single-call routes call a port directly.
4. **Prepare Extension Points for MVP2:** Define the search port for MVP2 evidence search. Search runs in the vss-agent (`POST /api/v1/incidents/search`, search-contract-v1) over the `evidence_crops` / `query_results` tables and the `search_evidence_items` RPC that PR 134 delivered (midterm `supabase/midterm/migrations/20261016120000_mvp2_evidence_search_and_crops.sql`; in finals, the baseline); the port mirrors that contract (§3.1).

The ports, use cases and adapters together are the console's middle layer between the frontend and Supabase (the "controller" in the 16 Oct meeting notes). It lives inside the app, under `incident-console-v2/lib/`.

---

## 2. Architecture & Directory Layout

```
incident-console-v2/
  app/api/**/route.ts             # Driving adapter: HTTP parsing/validation and status codes only
  app/**/page.tsx                 # Driving adapter too when it is a Server Component that loads data (§8)
  lib/
    ports/                        # Domain types and driven-port interfaces (route handlers depend on these)
      common.ts                   # RunKey, Page<T>, StoreRejection (domain refusal)
      incidents.ts                # IncidentRepository (run reports, reviews, structured edits, run deletes)
      dashboard.ts                # DashboardRepository (full get_incident_dashboard query and result)
      videos.ts                   # VideoRepository (video listings, official selection, whole-video delete)
      search.ts                   # EvidenceSearchRepository (MVP2 evidence search: the agent's search-contract-v1)
      health.ts                   # HealthRepository (database liveness)
      index.ts                    # Barrel exports and DbAdapters
    application/                  # Thin use cases for multi-step routes (depend on ports only)
      reports.ts                  # getReport, changeReviewStatus, deleteReport
    adapters/                     # Secondary adapters (infrastructure implementations)
      supabase/                   # Supabase PostgREST adapter implementation
        incidents.ts              # SupabaseIncidentAdapter implements IncidentRepository
        dashboard.ts              # SupabaseDashboardAdapter implements DashboardRepository
        videos.ts                 # SupabaseVideoAdapter implements VideoRepository
        health.ts                 # SupabaseHealthAdapter implements HealthRepository
        mappers/                  # row and RPC JSON <-> domain translation: report.ts (one run's rows), report-library.ts, dashboard.ts
        client.ts                 # PostgrestClient wrapper and service-role configuration
        index.ts                  # Factory functions getDbAdapters() and getDbHealth()
      memory/                     # In-memory fakes of IncidentRepository, VideoRepository and DashboardRepository, for tests
```

The adapters as a whole own the translation: only `lib/adapters/supabase/**` knows table names, column filters, RPC argument names (`p_*`) and snake_case columns. The adapters and their `mappers/` turn rows and RPC JSON into domain types field by field and domain queries into RPC arguments, and translate database refusals into `StoreRejection` (`videos.ts`, and `incidents.ts` for `set_review_status` / `save_human_report_edit`).

The search adapter calls the vss-agent rather than Supabase, so it will sit beside the Supabase adapters (`lib/adapters/agent/`) and arrives with the console search route (§7); an adapter is never shipped without a caller.

**Dependency rules** (conventions upheld in review; no test or lint tool checks them):
1. `app/api/**` and server-rendered pages (`app/**/page.tsx`) reach the database only through `@/lib/adapters/supabase` (the factory), never `@/lib/postgrest/*` or another adapter module. Client components (`'use client'`) never import the factory, an adapter, a use case or `lib/env`.
2. `lib/ports/**` holds type-only imports (apart from the `StoreRejection` class in `common.ts`), so ports stay browser-safe.
3. `lib/application/**` never imports `lib/adapters`, `lib/postgrest`, `lib/r2` or `lib/gateway`; R2 work is passed in as functions.
4. Only `lib/adapters/supabase/**` imports `lib/postgrest/client` as a value. The callers not yet migrated are listed in §7; remove an entry when its caller moves.
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
import type { Page, RunKey } from '@/lib/ports/common';
import type { StructuredEdit } from '@/lib/reports/edit-draft';
import type { StructuredAsset, StructuredEntity, StructuredIncident, StructuredInstrument } from '@/lib/reports/report-view';
import type { RunNotes } from '@/lib/reports/run-notes';
import type { ReportLibraryItem, ReviewStatus } from '@/lib/reports/storage';

export type ReportSort = 'newest' | 'oldest' | 'severity-high' | 'severity-low' | 'confidence-high' | 'confidence-low';

/** The report library's filters (list_incident_report_summaries' nineteen inputs), validated by the route; null means no filter. */
export interface ReportListQuery {
  page: number;
  pageSize: number;
  search: string | null;
  type: string | null;
  severity: string | null;         // 'low' | 'medium' | 'high' or an exact level '1'-'5'
  status: string | null;
  generatedAfter: string | null;   // stored timestamps (naive UTC)
  generatedBefore: string | null;
  timeFrom: string | null;         // time of day in `timezone`
  timeTo: string | null;
  entities: string[] | null;       // evidence text: substrings, or exact names when evidenceMatch is 'exact'
  instruments: string[] | null;
  assets: string[] | null;
  dayOfWeek: number | null;
  sort: ReportSort;
  scope: 'all' | 'official';
  entityTypes: string[] | null;
  evidenceMatch: 'contains' | 'exact';
  timezone: string;
}

/** One page of the report library; thumbnails are signed by the route (R2), not here. */
export interface ReportList extends Page<ReportLibraryItem> {
  incidentTypes: string[];
}

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
  revision: number;                // 1 for the first saved reviewer version, +1 per save
  status: ReviewStatus;            // after the save: an edit sends a verified report back to 'under review'
}

/** One atomic review transition; never changes editedBy/editedAt. */
export interface ReviewTransition {
  changed: boolean;                // false when the run already had the status
  status: ReviewStatus;
  verifiedBy: string | null;       // set only by verifying
  verifiedAt: string | null;
  humanVersionCreated: boolean;    // verifying copied the AI report into a reviewer version
}

export interface IncidentRepository {
  listReports(query: ReportListQuery): Promise<ReportList>;
  getRunReport(key: RunKey): Promise<RunReportRecord | null>;   // the effective report (reviewer version, else AI); null when the run, its video or its incident is missing
  runExists(key: RunKey): Promise<boolean>;
  getReview(key: RunKey): Promise<ReviewState | null>;
  setReviewStatus(key: RunKey, status: ReviewStatus, reviewer: string): Promise<ReviewTransition>;    // set_review_status
  applyStructuredEdit(key: RunKey, edit: StructuredEdit, editedBy: string): Promise<StructuredEditResult>; // save_human_report_edit
  deleteRun(key: RunKey): Promise<void>;                         // evidence, review and report rows cascade
}
```

Every run-scoped method takes a `RunKey`: one video has many runs, and `incidents` is keyed by `(incident_id, model_run_id)`. `ReportLibraryItem` admits `null` wherever `list_incident_report_summaries` emits one for an empty column.

#### `lib/ports/dashboard.ts`
```typescript
import type { DashboardAnalytics } from '@/lib/dashboard/types';

export type DashboardSeverity = 'low' | 'medium' | 'high';

/** get_incident_dashboard's full filter set, validated and resolved by the route. */
export interface DashboardQuery {
  periodStart: Date | null;        // null for all time; the adapter formats naive UTC
  periodEnd: Date | null;
  type: string | null;
  severity: DashboardSeverity | null;
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
export type CriticVerdict = 'confirmed' | 'rejected' | 'unverified';

export interface EvidenceSearchRequest {          // an absent field takes the agent's default
  query: string;                                  // 1-500 characters
  topK?: number;                                  // 1-50, default 10
  minSimilarity?: number;                         // 0-1, default 0 (no cutoff; the critic judges relevance)
  hideRejected?: boolean;                         // default true
  filters?: { incidentTypes?: string[]; minSeverity?: number; maxSeverity?: number; itemTypes?: EvidenceItemType[] };
}

export interface EvidenceSearchHit {
  resultId: string;                               // the hit's query_results id
  rank: number;
  similarityScore: number;
  item: {
    itemType: EvidenceItemType; itemId: string; name: string; label: string; description: string;
    threatLevel: number | null; holderEntityId: string | null;
    cropImageUrl: string;                         // signed by the agent
    timestampSeconds: number;
    boundingBox: [number, number, number, number] | null;   // detector output, normalised 0-1000
  };
  incident: {
    key: RunKey;                                  // the official report the evidence comes from
    incidentType: string; severityLevel: number; title: string | null; description: string;
    playbackUrl: string;                          // signed by the agent
    incidentWindow: [number, number];
  };
  critic: { verdict: CriticVerdict; confidence: number | null; rationale: string };
}

export interface EvidenceSearchResult {
  queryId: string;
  query: string;
  totalHits: number;
  executionTimeMs: number;
  hits: EvidenceSearchHit[];
}

export interface EvidenceSearchRepository {
  search(request: EvidenceSearchRequest): Promise<EvidenceSearchResult>;   // the backend records the query and its hits
}
```

Console search goes through the vss-agent (decided 2026-10-19). The agent embeds the query, ranks `evidence_crops` with `search_evidence_items`, runs the always-on critic and writes `queries` / `query_results`, so the console needs no embedding model and never writes those tables. The port is search-contract-v1 in camelCase (`services/agent/src/vss_agents/api/incident_search.py`, `SearchRequest` / `SearchResponse`); the planned adapter POSTs to `POST /api/v1/incidents/search` as documented in [`../vm-api-contracts.md`](../vm-api-contracts.md) and maps the snake_case. Evidence crops for one run, user feedback and query history are not part of that contract (and `query_results` has no feedback columns); they join the port when a backend serves them.

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
   Database row mapping to domain models (snake_case columns to camelCase domain types, decoding `model_runs.notes`, normalising legacy values) moves into `lib/adapters/supabase/mappers/`. RPC JSON (the report library, the dashboard, edit and official-selection results) is mapped field by field instead of being passed through with a cast; for every result the SQL can build, the mapped value equals what the routes returned before.
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
   - `npm test` runs TypeScript through Node's type stripping: adapters declare fields instead of using constructor parameter properties, type-only imports use `import type`, and barrels name types explicitly. `tests/support/alias-loader.mjs` resolves `@/...` directory imports to `index.ts`.

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
- [x] **Implement Supabase PostgREST Adapters (`lib/adapters/supabase/`):**
  - [x] Create `lib/adapters/supabase/client.ts` encapsulating service-role client configuration.
  - [x] Create `lib/adapters/supabase/incidents.ts` implementing `IncidentRepository`.
  - [x] Create `lib/adapters/supabase/dashboard.ts` implementing `DashboardRepository`.
  - [x] Create `lib/adapters/supabase/videos.ts` implementing `VideoRepository`.
  - [x] Create `lib/adapters/supabase/health.ts` implementing `HealthRepository`.
  - [x] Create `lib/adapters/supabase/index.ts` providing `getDbAdapters()` and `getDbHealth()`.
- [ ] **Search adapter:** implement `EvidenceSearchRepository` over the vss-agent's search route (`lib/adapters/agent/`), with the console search route (§7).
- [x] **Add thin use cases (`lib/application/`)** for report detail, review status change and delete.
- [ ] **Refactor API Routes (`app/api/*`):**
  - [x] Refactor `app/api/health/route.ts`.
  - [x] Refactor `app/api/dashboard/route.ts`.
  - [x] Refactor `app/api/videos/route.ts` and `app/api/videos/[videoId]/official/route.ts`.
  - [x] Refactor `app/api/reports/route.ts`.
  - [x] Refactor `app/api/reports/[videoId]/route.ts`, `review`, `edit` and `delete`.
  - [ ] `app/api/videos/[videoId]/runs`, `app/api/analysis` and `lib/analysis/*` (deferred, §7; ground truth removed).
- [x] **Testing & Quality Assurance:**
  - [x] Characterisation tests for responses no test pinned (report detail, review, the videos list, the full dashboard and report-library responses), written against the unrefactored routes.
  - [x] Contract suites that run the same cases against the in-memory fake and the Supabase adapter (over `tests/support/fake-postgrest.mjs`).
  - [x] Dependency rules recorded as conventions (§2), with the list of callers not yet migrated (§7).
  - [x] Verify existing test suite passes unmodified apart from import paths: `npm run test`.
  - [x] Verify production Next.js build passes cleanly: `npm run build`.

---

## 6. Definition of Done

For the whole workstream:
- Domain ports created under `incident-console-v2/lib/ports/`; Supabase adapters under `incident-console-v2/lib/adapters/supabase/`.
- Every `app/api/*` database access goes through `getDbAdapters()` / `getDbHealth()` and the ports, and no file outside `lib/adapters/supabase/**` imports `lib/postgrest/client` as a value (including `lib/analysis/*`).
- Every route test that existed before the refactor passes unmodified apart from import paths; characterisation tests exist for routes that had none; each port has a contract suite; §7's list of callers not yet migrated is empty.
- `npm run typecheck`, `npm test` and `npm run build` pass without errors.

This round meets these for every route not listed in §7; the callers in §7 stay listed there until they move.

---

## 7. Deferred in this round

Decided 2026-10-17; updated 2026-10-19, when the dashboard and the report library moved onto the ports:
- **Ground truth** (`app/api/reports/[videoId]/ground-truth`, its page and the `gt_*` tables): removed from console and database.
- **Analysis saving and run history** (`app/api/analysis`, `lib/analysis/*`, `app/api/videos/[videoId]/runs`): not on the ports yet; they move into the middle layer later, together with the rest of the separation of human-verified and AI-generated reports. Run history already reads each run's type and severity from `effective_incidents`.
- **Search adapter and route**: the port is defined to match the agent's search contract (§3.1); the agent-backed adapter and a console search route come in a later PR. No console-side embedding.
- **Keys built in SQL**: the report library and dashboard responses keep the snake_case keys their RPCs build (`incident_type`, `reviews.under_review`), because the components read them; renaming them means changing the mapper and the components together.

Files outside `lib/adapters/supabase/**` that still import `lib/postgrest/client` as a value (dependency rule 4), each with the reason it waits:

| File | Waits for |
|---|---|
| `app/api/videos/[videoId]/runs/route.ts` | the verified/AI report split |
| `lib/analysis/run-contract-analysis.ts` | the verified/AI report split |
| `lib/analysis/persistence.ts` | the verified/AI report split |

---

## 8. Read pages as Server Components

Next.js App Router pages can load their data on the server instead of mounting a client screen that fetches our own `/api/*` in `useEffect`. A converted page is a Server Component that builds the ports with `getDbAdapters()`, calls the use case (or a single port method), signs R2 URLs on the server and passes the domain types to the existing interactive client component as props. Pages move one per PR; write actions stay on their `/api/*` routes, and a GET route is deleted only once nothing calls it (the skills also curl several of them).

| Page | State | Loads through |
|---|---|---|
| `/reports/[videoId]?run=` | Server Component | `getReport` (`lib/application/reports.ts`), via `loadReportPage` in the route's `load-report.ts` |
| `/reports/[videoId]/compare` | client fetch of `GET /api/reports/[videoId]` per run | planned |
| `/reports` (library) | client fetch of `GET /api/reports` | planned; needs the viewer's time zone on the server |
| `/videos`, `/videos/[videoId]` | client fetch of `GET /api/videos`, `GET /api/videos/[videoId]/runs` | planned; run history waits for its port (§7) |
| `/dashboard` | client fetch of `GET /api/dashboard` | planned; needs the viewer's time zone on the server |

Conventions for a converted page (the report page is the reference, `app/reports/[videoId]/(report)/`):
- `export const dynamic = 'force-dynamic'`: review state changes between visits, so the page is never served from a cache.
- The server-side load (configuration, `getDbAdapters()`, the use case, R2 signing) lives in a `.ts` module beside the page that returns the outcome (found, not found, failed with its message); `page.tsx` only maps it to elements. Node's test runner cannot load `.tsx`, so the load is tested behaviourally over the fake PostgREST (`tests/report-page.test.mjs`).
- A route group keeps the page's `loading.tsx`, `error.tsx` and `not-found.tsx` from wrapping sibling routes (`compare/`).
- A missing record calls `notFound()`; a load failure the page expects (unconfigured store, unreachable PostgREST, unsignable video) renders its message in place, as the API route returns it; `error.tsx` catches the rest, with the message redacted in production.
- After a write through `/api/*`, the client component calls `router.refresh()`, which renders the page on the server again with the stored state.
- `router.refresh()` keeps client components mounted, so a panel that still fetches its own `/api/*` data must reload when the refreshed props change (the report page's analysis history reloads when the official run, review status or edit time changes).

