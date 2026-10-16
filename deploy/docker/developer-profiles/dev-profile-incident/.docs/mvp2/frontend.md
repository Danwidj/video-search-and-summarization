# MVP2 Workstream Task: Frontend Console Search UI & Interactive Intelligence

## Goal
Implement the MVP2 frontend user interface in `incident-console-v2` (Phase 5 of the MVP2 plan), expanding it into an end-to-end evidence search, verification, and interactive incident exploration workstation.

Reviewers and operators will:
1. Search surveillance evidence across official incident reports using natural language.
2. Filter by item type, incident taxonomy, and severity.
3. Inspect object crops with critic verification status, rationales, and parent incident context.
4. Interactively jump to the exact moment in video clips via scrubber timestamp anchors.
5. Explore an evidence timeline and crop gallery on the incident report page.
6. Submit relevance feedback on search hits saved back to `query_results`.
7. Review previous searches and saved queries via an audit trail drawer.
8. Ask conversational questions across incidents and evidence with a working chat interface.
9. Theme the console dynamically using an external style guide / design token source.

All development occurs on a zero-GPU local workstation, building against server-side Next.js route handlers, mocked backends, and strict schema contracts until native backend and VM services land.

---

## Tasks Checklist
- [ ] **Search Route & Navigation:**
  - [ ] Add `/search` page and primary header nav link in `incident-console-v2` (`components/app-header.tsx`, `app/search/page.tsx`).
- [ ] **Natural-Language Search & Filtering:**
  - [ ] Natural-language search input with filter chips (item type: entity/instrument/asset, incident taxonomy: road accident/burglary/explosion/assault/animal attack, severity range 1-5).
  - [ ] Search state management, loading skeletons, and empty state feedback.
- [ ] **Search Hit Cards & Evidence Inspection:**
  - [ ] Search hit cards rendering crop image (`crop_image_url`), item name, description, threat level badge, parent incident details (incident type, severity, video title), and critic verification badge (confirmed/rejected/unverified) with rationale text.
  - [ ] Support expandable audit drawer or toggle for inspecting rejected candidate hits.
- [ ] **Interactive Jump-to-Clip:**
  - [ ] Clicking a hit opens the video player and seeks to the item's `timestamp_seconds`.
- [ ] **Relevance Feedback on Search Hits:**
  - [ ] Provide user feedback controls (thumbs up / thumbs down / rating) on search hit cards.
  - [ ] Persist relevance feedback to `query_results` using the typed functions from `incident-console-v2/lib/db/`.
- [ ] **Evidence Timeline & Scrubber Anchors on Incident Page:**
  - [ ] Render timeline markers on the video scrubber at each item's `timestamp_seconds`.
  - [ ] Crop gallery drawer/strip linking each visual crop directly to its scrubber timestamp anchor.
- [ ] **Search History & Saved Searches:**
  - [ ] Saved queries drawer / recent searches list fetching recent user queries from the `queries` / `query_results` audit trail using `incident-console-v2/lib/db/` functions.
  - [ ] One-click re-execution of historical or bookmarked queries.
- [ ] **Themeable UI via External Style Guide:**
  - [ ] Implement design-token theme loader supporting external JSON design token definitions (file-based or remote URL).
  - [ ] Map external tokens to CSS custom variables controlling brand palette, typography, radii, and shadows across all console screens.
- [ ] **Working Conversational Q&A (Incident & Evidence Chat):**
  - [ ] Multi-turn conversational Q&A panel over incidents and retrieved evidence items.
  - [ ] Frontend chat client and contract proxy adhering to the chat contract specification, functioning against a local mock until the backend endpoint lands.
- [ ] **Mock Backend Alignment:**
  - [ ] Build and verify all features against local mock backend endpoints (`mock-backend/base_profile_mock` :7777 / `search_profile_mock` :7778) and contract fixtures before backend integration.

---

## Ownership Boundaries & Non-Goals

### Ownership Boundary
- **Frontend Engineer Owns:**
  - `incident-console-v2/` page routes (`app/`), visual components (`components/`), and theme styling.
  - Interaction with the new MVP2 tables (`evidence_crops`, `query_results`) is done **strictly through typed functions** in `incident-console-v2/lib/db/` (provided by the Database Engineer).
  - Search and chat execution come from `vss-agent` via the shared contracts (`contracts/search-contract-v1` and chat contract).
- **Database Engineer Owns:**
  - `supabase/` migrations, RLS policies, PostgreSQL search RPC functions, and the `incident-console-v2/lib/db/` module.
- **Existing Codebase Rule:**
  - Existing API routes (`app/api/*/route.ts`) already create their own server-side PostgREST client with `SUPABASE_SERVICE_ROLE_KEY`, so the browser never queries Supabase directly. There is no need for new intermediate server-side data routes for RLS compliance, and existing API routes must **not** be refactored.
- **Scope Boundaries (What This Must NOT Touch):**
  - **Do not edit contract files directly:** The Captain owns `contracts/search-contract-v1/` and `contracts/incident-contract-v3`. Build against their schemas; do not change repository contracts.
  - **Do not touch database migrations or Supabase DDL:** Database schema changes (`evidence_crops`, `query_results`, pgvector RPCs) are owned by the database migration workstream.
  - **Do not implement database queries directly:** Use the typed helpers provided in `incident-console-v2/lib/db/`.
  - **Do not edit backend routes or Python services:** Native `vss-agent` routes (`/api/v1/incidents/search`), cropping service, and Brev Switchyard critic calls are owned by the Captain.
  - **Do not touch eval benchmark suites:** Standalone benchmark scripts in `eval/` are owned by the eval workstream.
  - **Do not touch retired `incident-console/`:** All frontend feature work belongs exclusively in `incident-console-v2/`.
  - **Ignore E2E test suites:** Do not build or run end-to-end browser automation suites (e.g. Playwright / Cypress). Unit and typecheck tests (`npm run typecheck`, `npm test`) remain standard.

---

## Technical Specifications & Interfaces

### 1. Data Access & Contracts
- **Search & Chat Execution:** Calls `vss-agent` search and chat endpoints directly or via mock backend according to `contracts/search-contract-v1` and the chat contract specification.
- **MVP2 Tables Data Access:** Reads and writes to `query_results` and `evidence_crops` use typed helper functions imported from `incident-console-v2/lib/db/` (e.g., `saveFeedback()`, `getQueryHistory()`, `getEvidenceCrops()`), ensuring clear boundary separation between frontend and database code.

### 2. Search API Contract (`contracts/search-contract-v1`)

#### Request Schema (`SearchRequest`):
```json
{
  "query": "sharp weapon",
  "top_k": 10,
  "min_similarity": 0.2,
  "item_types": ["entity", "instrument", "asset"],
  "filters": {
    "incident_types": ["assault", "burglary"],
    "min_severity": 1,
    "max_severity": 5
  }
}
```

#### Response Schema (`SearchResponse`):
```json
{
  "query_id": "qr_abc123",
  "query": "sharp weapon",
  "total_hits": 1,
  "execution_time_ms": 142.5,
  "hits": [
    {
      "result_id": "res_001",
      "rank": 1,
      "similarity_score": 0.88,
      "item": {
        "item_type": "instrument",
        "item_id": "I1",
        "name": "Machete",
        "description": "Large curved metal blade held in subject's right hand",
        "threat_level": 4,
        "holder_entity_id": "E1",
        "crop_image_url": "https://<presigned-r2-url>/evidence/Assault007/MR001/instruments/I1.jpg",
        "timestamp_seconds": 14,
        "bounding_box": [320, 450, 410, 520]
      },
      "incident": {
        "incident_id": "Assault007",
        "model_run_id": "MR001",
        "incident_type": "assault",
        "severity_level": 4,
        "description": "Physical assault with weapon in vestibule",
        "playback_url": "https://<presigned-r2-url>/videos/Assault007.mp4",
        "incident_window": [10.0, 25.0]
      },
      "critic": {
        "verdict": "confirmed",
        "rationale": "The cropped screenshot clearly shows a machete with a curved metal blade held in the subject's right hand."
      }
    }
  ]
}
```

### 3. Evidence Timeline & Scrubber Anchors on Incident Report Page
- On the incident report screen (`components/incident-report.tsx` and `app/reports/[videoId]/page.tsx`):
  - Enhance video player with an interactive timeline scrubber.
  - Overlay colored milestone dots/anchors at `item.timestamp_seconds`:
    - Entity: Blue / Teal marker.
    - Instrument: Red / Amber marker.
    - Asset: Gray / Slate marker.
  - Hovering an anchor previews the crop thumbnail and label.
  - Clicking an anchor seeks playback directly to that second.
  - Display an evidence crop gallery grid below or adjacent to the player displaying all cropped items for that incident.

### 4. Search History & Saved Searches
- Drawer or sidebar panel listing:
  - Recent queries executed in the current session (cached locally or fetched from `queries` audit log).
  - Saved/pinned searches bookmarked by the user.
- Selecting a search item repopulates filters and triggers immediate execution.

### 5. Themeable UI & External Style Guide Integration
To allow operators and partner teams to customize appearance without code changes, the console must load design tokens from an external configuration (e.g. `public/theme.json` or remote URL specified via environment variable `NEXT_PUBLIC_THEME_URL`):

#### Token Schema Specification (`theme-tokens.json`):
```json
{
  "name": "NVIDIA Metro Dark",
  "colors": {
    "primary": "#76b900",
    "primaryHover": "#5c9200",
    "background": "#0b0f0e",
    "surface": "#131b17",
    "surfaceBorder": "#1f2d26",
    "text": "#e0e8e3",
    "textMuted": "#85998f",
    "danger": "#e5484d",
    "warning": "#f5a623",
    "success": "#30a46c"
  },
  "typography": {
    "fontFamilySans": "Arial, Helvetica, sans-serif",
    "fontFamilyMono": "SFMono-Regular, Consolas, monospace"
  },
  "radii": {
    "card": "0.75rem",
    "button": "9999px",
    "badge": "0.375rem"
  }
}
```
- **Implementation Mechanism:**
  - A theme provider (`components/theme-provider.tsx`) loads the JSON token definition on application mount.
  - Injects CSS custom properties into `:root` (e.g., `--theme-primary`, `--theme-bg`, `--theme-surface`, etc.).
  - Tailwind configuration (`tailwind.config.js`) maps utility classes (`bg-canvas`, `text-ink`, `bg-signal`) to CSS variables with fallbacks to defaults.

### 6. Working Conversational Q&A (Incident & Evidence Chat)
The console currently has a rudimentary report chat route (`app/api/chat/route.ts`). MVP2 requires a full conversational Q&A capability over incidents and retrieved search evidence.

#### Required Chat Backend Contract (`POST /api/v1/incidents/chat`):
```json
// Request
{
  "session_id": "session_xyz",
  "messages": [
    { "role": "user", "content": "What weapons were found across all assault incidents?" }
  ],
  "context": {
    "scope": "global", // or "incident"
    "incident_id": "Assault007", // optional, when scoped to single incident
    "evidence_crop_ids": ["I1", "I2"] // optional, for grounded evidence visual QA
  }
}

// Response
{
  "session_id": "session_xyz",
  "message": {
    "role": "assistant",
    "content": "Across the recorded assault incidents, two primary weapons were identified: a machete (I1) in Assault007, and a blunt wooden club in Assault011.",
    "citations": [
      {
        "incident_id": "Assault007",
        "item_id": "I1",
        "item_type": "instrument",
        "timestamp_seconds": 14,
        "crop_image_url": "https://<presigned-r2-url>/evidence/.../I1.jpg"
      }
    ]
  }
}
```
- **Frontend Chat Requirements:**
  - Expand `app/api/chat/route.ts` to support multi-turn dialogue with evidence citations.
  - Build chat UI drawer/panel accessible from both the search view and the incident view.
  - Render assistant responses with clickable evidence citation cards that open crop screenshots and trigger jump-to-clip.
  - The frontend builds against mock chat responses until the native `vss-agent` chat endpoint is deployed.

---

## Open Questions & Dependencies
1. **Search & Chat Contracts:** The Captain owns backend route definitions and contract landing. The frontend builds against the JSON schemas provided in this document using local mock handlers.
2. **Relevance Feedback Persistence:** Needs the `query_results` table created in Supabase (owned by DB workstream) or handled gracefully via mock storage during local testing.
3. **External Style Guide Source:** Team to determine default URL/path for theme token configuration (inferred fallback: local `public/theme.json` with env override).

---

## Definition of Done
1. **Search & Exploration:** `/search` page is functional with query input, filter chips, loading states, and hit cards rendering crops, parent incident metadata, and critic verification status.
2. **Jump-to-Clip & Scrubber:** Clicking hits seeks player to `timestamp_seconds`; timeline markers display on incident video scrubbers with crop gallery linkage.
3. **Data Access & Boundaries:** Reads and writes to MVP2 tables are isolated strictly through `incident-console-v2/lib/db/` functions, leaving existing API routes unrefactored.
4. **Relevance Feedback:** Users can submit relevance feedback on search hits with persistence to `query_results` via `lib/db/`.
5. **Search History:** Query history and saved searches are visible and re-executable via `lib/db/`.
6. **Theming Engine:** Style guide JSON tokens dynamically load and apply across console components.
7. **Conversational Q&A:** Chat panel functions with streaming/multi-turn responses and clickable evidence citations.
8. **Code Quality:** All TypeScript checks (`npm run typecheck`) and component tests (`npm test`) pass cleanly in `incident-console-v2`.
