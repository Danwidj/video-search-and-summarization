# MVP2 Task Specification: Hexagonal Architecture for `incident-console-v2`

## 1. Overview & Objectives

This workstream restructures `incident-console-v2` using hexagonal architecture (ports and adapters) to cleanly decouple the Next.js frontend UI from database access and transport details.

### Context
Currently, Next.js API route handlers in `incident-console-v2/app/api/*` directly instantiate `PostgrestClient` (from `lib/postgrest/client.ts`), construct raw PostgREST queries (e.g. `select(...)`, `order(...)`, `eq(...)`), and map table schemas directly within HTTP route handlers. This couples the presentation layer directly to Supabase PostgREST transport and database schema specifics.

### Objectives
1. **Decouple UI from Database Transport:** Define clean domain ports (`lib/ports/`) representing the business capabilities required by the console (incidents, dashboard analytics, video management, search, and health).
2. **Implement Supabase PostgREST Adapters:** Implement secondary adapters (`lib/adapters/supabase/`) that encapsulate `PostgrestClient`, query parameter construction, error handling, and data mapping.
3. **Refactor Route Handlers:** Update `app/api/*` route handlers to interact exclusively with domain ports via an adapter factory / dependency injection provider.
4. **Prepare Extension Points for MVP2:** Define port interfaces and adapter stubs for MVP2 features (`evidence_crops`, `query_results`), enabling the database workstream to plug in seamlessly.

---

## 2. Architecture & Directory Layout

```
incident-console-v2/
  lib/
    ports/                        # Core application domain interfaces (UI depends on these)
      incidents.ts                # IncidentRepository (reports, reviews, edits, deletes)
      dashboard.ts                # DashboardRepository (metrics, heatmaps, trends)
      videos.ts                   # VideoRepository (video listings, official selections)
      search.ts                   # EvidenceSearchRepository (MVP2 search, crops, feedback)
      health.ts                   # HealthRepository (database liveness)
      index.ts                    # Barrel exports
    adapters/                     # Secondary adapters (infrastructure implementations)
      supabase/                   # Supabase PostgREST adapter implementation
        incidents.ts              # SupabaseIncidentAdapter implements IncidentRepository
        dashboard.ts              # SupabaseDashboardAdapter implements DashboardRepository
        videos.ts                 # SupabaseVideoAdapter implements VideoRepository
        search.ts                 # SupabaseEvidenceSearchAdapter implements EvidenceSearchRepository
        health.ts                 # SupabaseHealthAdapter implements HealthRepository
        client.ts                 # PostgrestClient wrapper and service-role configuration
        index.ts                  # Factory functions (e.g. getDbAdapters())
```

---

## 3. Concrete Port & Adapter Specifications

### 3.1 Domain Ports (`lib/ports/`)

#### `lib/ports/incidents.ts`
```typescript
import type { IncidentReportV3 } from '@/lib/contract/types';

export interface IncidentListItem {
  incidentId: string;
  videoId: string;
  title: string;
  incidentType: string;
  severityLevel: number;
  reviewed: boolean;
  createdAt: string;
}

export interface IncidentRepository {
  listIncidents(params?: { limit?: number; offset?: number }): Promise<IncidentListItem[]>;
  getIncident(incidentId: string): Promise<IncidentReportV3 | null>;
  updateReviewStatus(incidentId: string, reviewed: boolean): Promise<void>;
  editReport(incidentId: string, patch: Partial<IncidentReportV3>): Promise<void>;
  deleteIncident(incidentId: string): Promise<void>;
}
```

#### `lib/ports/dashboard.ts`
```typescript
export interface DashboardMetrics {
  totalIncidents: number;
  reviewedCount: number;
  pendingCount: number;
  severityDistribution: Record<number, number>;
  incidentTypesDistribution: Record<string, number>;
}

export interface DashboardRepository {
  getMetrics(): Promise<DashboardMetrics>;
}
```

#### `lib/ports/videos.ts`
```typescript
export interface VideoItem {
  videoId: string;
  filename: string;
  uploadedAt: string;
  selectedModelRunId: string | null;
  durationSeconds?: number;
}

export interface VideoRepository {
  listVideos(): Promise<VideoItem[]>;
  getVideo(videoId: string): Promise<VideoItem | null>;
  setSelectedModelRun(videoId: string, modelRunId: string): Promise<void>;
  recordUploadedVideo(video: { videoId: string; filename: string; durationSeconds?: number }): Promise<void>;
}
```

#### `lib/ports/search.ts` (MVP2 Extension Port)
```typescript
export interface EvidenceCropItem {
  incidentId: string;
  modelRunId: string;
  itemType: 'entity' | 'instrument' | 'asset';
  itemId: string;
  itemName: string;
  description: string;
  threatLevel: number | null;
  holderEntityId: string | null;
  timestampSeconds: number;
  boundingBox: [number, number, number, number];
  image: string;
  similarityScore?: number;
}

export interface SearchEvidenceParams {
  queryEmbedding: number[];
  queryText?: string;
  topK?: number;
  minSimilarity?: number;
  alpha?: number;
  itemTypes?: Array<'entity' | 'instrument' | 'asset'>;
  incidentTypes?: string[];
  minSeverity?: number;
  maxSeverity?: number;
}

export interface EvidenceSearchRepository {
  searchEvidenceItems(params: SearchEvidenceParams): Promise<EvidenceCropItem[]>;
  getEvidenceCrops(incidentId: string, modelRunId: string): Promise<EvidenceCropItem[]>;
  saveFeedback(params: { resultId: string; queryId: string; feedback: string; notes?: string }): Promise<void>;
  getQueryHistory(params?: { limit?: number }): Promise<Array<Record<string, unknown>>>;
}
```

#### `lib/ports/health.ts`
```typescript
export interface HealthStatus {
  status: 'ok' | 'degraded' | 'error';
  latencyMs: number;
  database: boolean;
}

export interface HealthRepository {
  checkHealth(): Promise<HealthStatus>;
}
```

---

## 4. What Moves Out of UI / Route Code

1. **`PostgrestClient` Instantiation:**
   Direct instantiation (`new PostgrestClient(...)` or importing `getPostgrestClient`) is removed from `app/api/*`.
2. **Raw PostgREST Query Construction:**
   Constructing query strings (`client.from('incidents').select(...)`, `.eq(...)`, `.order(...)`) is encapsulated inside `lib/adapters/supabase/`.
3. **Schema Mapping & Normalization:**
   Database row mapping to contract models (e.g. converting snake_case columns to camelCase domain models) moves into adapters.
4. **Adapter Factory Pattern:**
   Route handlers obtain dependencies via `getDbAdapters()`:
   ```typescript
   // Example refactored route handler in app/api/reports/route.ts
   import { NextResponse } from 'next/server';
   import { getDbAdapters } from '@/lib/adapters/supabase';

   export async function GET() {
     const { incidents } = getDbAdapters();
     const reports = await incidents.listIncidents();
     return NextResponse.json(reports);
   }
   ```

---

## 5. Workstream Task Checklist

- [ ] **Define Domain Ports (`lib/ports/`):**
  - [ ] Create `lib/ports/incidents.ts` (`IncidentRepository`).
  - [ ] Create `lib/ports/dashboard.ts` (`DashboardRepository`).
  - [ ] Create `lib/ports/videos.ts` (`VideoRepository`).
  - [ ] Create `lib/ports/search.ts` (`EvidenceSearchRepository`).
  - [ ] Create `lib/ports/health.ts` (`HealthRepository`).
  - [ ] Create `lib/ports/index.ts` exporting all port interfaces.
- [ ] **Implement Supabase PostgREST Adapters (`lib/adapters/supabase/`):**
  - [ ] Create `lib/adapters/supabase/client.ts` encapsulating service-role client configuration.
  - [ ] Create `lib/adapters/supabase/incidents.ts` implementing `IncidentRepository`.
  - [ ] Create `lib/adapters/supabase/dashboard.ts` implementing `DashboardRepository`.
  - [ ] Create `lib/adapters/supabase/videos.ts` implementing `VideoRepository`.
  - [ ] Create `lib/adapters/supabase/search.ts` implementing `EvidenceSearchRepository` (ready for MVP2 tables).
  - [ ] Create `lib/adapters/supabase/health.ts` implementing `HealthRepository`.
  - [ ] Create `lib/adapters/supabase/index.ts` providing `getDbAdapters()`.
- [ ] **Refactor API Routes (`app/api/*`):**
  - [ ] Refactor `app/api/health/route.ts`.
  - [ ] Refactor `app/api/dashboard/route.ts`.
  - [ ] Refactor `app/api/videos/route.ts` and `app/api/videos/[videoId]/official/route.ts`.
  - [ ] Refactor `app/api/reports/route.ts` and `app/api/reports/[videoId]/*`.
- [ ] **Testing & Quality Assurance:**
  - [ ] Add unit tests verifying adapters fulfill port contracts.
  - [ ] Verify existing test suite passes: `npm run test`.
  - [ ] Verify production Next.js build passes cleanly: `npm run build`.

---

## 6. Definition of Done

- Domain ports created under `incident-console-v2/lib/ports/`.
- Supabase adapters implemented under `incident-console-v2/lib/adapters/supabase/`.
- All `app/api/*` route handlers refactored to consume data exclusively via domain ports.
- Direct `PostgrestClient` references eliminated from route handlers.
- `npm run test` and `npm run build` pass without errors.
