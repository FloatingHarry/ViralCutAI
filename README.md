# ViralCutAI

Agent-based AIGC commerce video workspace for the AI full-stack challenge.

## Stack

- Frontend: Next.js App Router, React, TypeScript, Tailwind CSS
- Backend: FastAPI, Python, SQLAlchemy 2.0
- Agent runtime: LangGraph generation graph and experiment analysis graph
- Data: PostgreSQL ORM tables for assets, viral factors, generation runs, artifacts, traces, and experiments
- Providers: automatic Volcengine text/image, Seedance video, and FastMoss market-data calls, with local placeholders only for capabilities that are not connected

## Quick Start

Prerequisites:

- Node.js 24
- pnpm 11.4.0
- Python 3.11
- Docker Desktop for PostgreSQL
- FFmpeg available on `PATH` for video/keyframe assembly

```powershell
docker compose up -d postgres
pnpm install
python -m pip install -r apps/api/requirements.txt

Copy-Item .env.example .env.local
# Fill .env.local with the judge's Volcengine / Seedance / FastMoss credentials.

pnpm dev:api
pnpm dev:web
```

Open:

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs

## Product Flow

1. Create a private Asset Collection in My Assets, then upload product images or videos. Images are analyzed through the Volcengine multimodal endpoint; videos are keyframe-sampled with FFmpeg and analyzed through the same endpoint.
2. Import public TikTok ecommerce signals from FastMoss as owner-curated viral candidates. The system stores structured market data first, then selected candidates can be manually upgraded with an attached MP4 for keyframe verification.
3. Cluster two to five external references into n:1 creative templates when a reusable pattern appears.
4. Open Studio, select an Asset Collection and platform, choose reference-video mode (auto/manual), choose template mode (auto/none/manual), then run agents.
5. The Generation Graph runs Viral Strategy Agent, Script & Storyboard Agent, and Render & Review Agent.
6. Studio shows factor board, storyboard, provider artifacts, preview, export manifest, and compliance in a simplified generation view.
7. Open Editor, preview the full draft, inspect the three fixed shots, regenerate one shot, and assemble an exportable MP4.
8. Analytics selects two to four succeeded generation runs, accepts real manually entered metrics, and runs the Attribution & Experiment Agent.
9. Trace views show both Generation Graph and Experiment Analysis Graph execution details.

## Public API

- `GET /health`
- `POST /asset-collections`
- `GET /asset-collections`
- `GET /asset-collections/{id}`
- `PATCH /asset-collections/{id}`
- `POST /asset-collections/{id}/assets`
- `POST /assets`
- `GET /assets`
- `GET /assets/search`
- `GET /assets/{id}`
- `GET /assets/{id}/file`
- `PATCH /assets/{id}`
- `POST /assets/{id}/analyze`
- `PATCH /asset-slices/{id}`
- `GET /viral-videos`
- `POST /viral-videos/analyze`
- `POST /viral-videos/import-fastmoss`
- `POST /viral-videos/{id}/attach-source-video`
- `GET /viral-factors`
- `GET /creative-templates`
- `POST /creative-templates/build`
- `POST /generation-runs`
- `GET /generation-runs`
- `GET /generation-runs/{run_id}`
- `GET /generation-runs/{run_id}/export`
- `GET /generation-runs/{run_id}/editor-timeline`
- `PATCH /generation-runs/{run_id}/editor-timeline`
- `POST /generation-runs/{run_id}/retry`
- `PATCH /generation-runs/{run_id}/storyboard/{shot_id}`
- `POST /generation-runs/{run_id}/storyboard/{shot_id}/regenerate`
- `POST /generation-runs/{run_id}/storyboard/{shot_id}/regenerate-clip`
- `POST /generation-runs/{run_id}/render-preview`
- `POST /generation-runs/{run_id}/assemble-preview`
- `GET /generation-runs/{run_id}/assembled-video`
- `GET /generation-runs/{run_id}/editor-clip-video`
- `POST /experiments/analyze`
- `GET /experiments`
- `GET /experiments/{experiment_id}`

## Agent Graphs

```mermaid
flowchart LR
  A["My Assets + external Viral Library + product input"] --> B["Viral Strategy Agent"]
  B --> C{"Factor coverage OK?"}
  C -- no --> B
  C -- yes --> D["Script & Storyboard Agent"]
  D --> E["Render & Review Agent"]
  E --> F{"Compliance passed?"}
  F -- no --> D
  F -- yes --> G["Preview + export + artifacts"]
```

```mermaid
flowchart LR
  A["2-4 Generation Runs"] --> B["Attribution & Experiment Agent"]
  B --> C["Variant metrics"]
  B --> D["Factor attribution"]
  B --> E["Next iteration recommendation"]
```

## Data Model

```mermaid
erDiagram
  ASSET_COLLECTION ||--o{ ASSET : groups
  ASSET ||--o{ ASSET_SLICE : has
  ASSET ||--o{ ASSET_TAG : has
  ASSET ||--o| ASSET_EMBEDDING : has
  GENERATION_RUN ||--o{ SOURCE_ASSET : uses
  GENERATION_RUN ||--o{ RUN_EVENT : records
  GENERATION_RUN ||--o{ AGENT_STEP : traces
  GENERATION_RUN ||--o{ MEDIA_ARTIFACT : outputs
  EXPERIMENT_ANALYSIS ||--o{ EXPERIMENT_VARIANT : compares
  EXPERIMENT_ANALYSIS ||--o{ FACTOR_ATTRIBUTION : explains
```

## Requirement Coverage

| Requirement | Status |
|---|---|
| Product asset upload | Supported through private Asset Collections, batch image/video upload, and Studio temporary upload |
| Asset slicing / tags / embedding retrieval | Volcengine multimodal image understanding, FFmpeg video keyframes, callable slices, tags, pseudo embeddings, and search |
| Viral video analysis | Internal FastMoss Video Search import through `/viral-videos/import-fastmoss`, plus manual MP4 verification through `/viral-videos/{id}/attach-source-video` |
| Viral factors and templates | Global Viral Library is generated only from external reference analysis; Studio run factors stay on the run |
| Script generation and storyboard | LangGraph Script & Storyboard Agent with internal copy/storyboard/prompt substeps |
| One-click video generation | One Studio action creates provider-tracked preview artifacts, one real cover image when configured, and real Seedance video when configured |
| Task progress | `RunEvent` stages and Agent traces |
| Preview / export | Real video URL when available, plus JSON export manifest |
| TTS / subtitles / BGM | Provider-pending planning artifacts; assembled local MP4 can include generated placeholder/editor-timeline audio until dedicated providers are connected |
| Generation trace | `AgentStep` plus Trace Console |
| A/B comparison and attribution | Experiment Analysis Graph over real manually entered metrics |
| Compliance flow | Render & Review Agent with conditional rewrite |
| Shot-level intervention | Editor timeline, per-shot preview, real Seedance replacement clip generation, and FFmpeg assembly |
| CI/CD | GitHub Actions CI compile, lint, and build |

## Provider Truth Boundary

The API, database writes, LangGraph execution, traces, and UI interactions are real. Placeholders only represent missing or not-yet-connected provider capabilities:

- `MockLLMProvider`
- `MockImageProvider`
- `Mock asset understanding provider`
- `MockCoverImageProvider`
- `MockVideoProvider`
- `MockTTSProvider`
- `MockSubtitleProvider`
- `MockBGMProvider`

Real Volcengine text/multimodal understanding, Volcengine image generation, Seedance, and publishing metrics can replace these providers without changing the product flow. If a configured real provider is called and fails, the run records `real_failed` or `Provider failed` and does not replace that output with placeholder data. Analytics does not generate simulated performance metrics; users must enter real variant metrics before attribution can run.

## Environment

```env
DATABASE_URL=postgresql+psycopg://viralcutai:viralcutai@localhost:5432/viralcutai
API_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Copy this file to .env.local and fill provider credentials locally.
# Do not commit .env.local or real provider keys.
VOLCENGINE_API_KEY=
VOLCENGINE_BASE_URL=
# Text / chat endpoint for strategy, script, image prompt planning, experiments,
# and My Assets image/video-frame multimodal understanding.
VOLCENGINE_ENDPOINT_ID=
VOLCENGINE_TEXT_MODEL=
# Seedream image generation model or image-capable endpoint for /images/generations.
# Do not reuse the text endpoint here.
VOLCENGINE_IMAGE_MODEL=

SEEDANCE_API_KEY=
SEEDANCE_BASE_URL=
SEEDANCE_ENDPOINT_ID=
SEEDANCE_MODEL=

FASTMOSS_API_KEY=
FASTMOSS_CLIENT_ID=
FASTMOSS_CLIENT_SECRET=
FASTMOSS_BASE_URL=https://openapi.fastmoss.com

PROVIDER_REQUEST_TIMEOUT_SECONDS=120
SEEDANCE_POLL_SECONDS=90
SEEDANCE_POLL_INTERVAL_SECONDS=5

UPLOAD_DIR=storage/uploads
```

Use `.env.example` as the public template and put real local secrets in `.env.local`. The local secret file is ignored by Git. Uploaded assets are stored under `storage/`, which is also gitignored.

The repository includes public demo seed data under `apps/api/app/static`: the Aurora Glow product assets plus 17 owner-curated viral-library references, 136 factors, and local cover thumbnails. After the API starts, reviewers can seed everything with `POST /demo-data/seed`; this creates the demo product collection and viral library in their local database without needing any of the author's private `storage/` files.

Provider roles are intentionally separated: `VOLCENGINE_ENDPOINT_ID` / `VOLCENGINE_TEXT_MODEL` power text generation and image prompt planning, `VOLCENGINE_IMAGE_MODEL` powers real cover image generation, `SEEDANCE_ENDPOINT_ID` / `SEEDANCE_MODEL` powers video generation, and `FASTMOSS_API_KEY` or `FASTMOSS_CLIENT_ID` / `FASTMOSS_CLIENT_SECRET` power Viral Library market-data import. If the image model is missing, the cover image is reported as not generated and the API does not call the image endpoint.

FastMoss import calls `POST /video/v1/search` with ecommerce-video filtering and then uses Volcengine to extract a structured-only 8-factor board. These records are marked `fastmoss_structured_only` and `visual_verified=false`. Selected references can be upgraded by manually attaching a source MP4; the backend stores the file under `storage/`, runs FFmpeg keyframe analysis, and regenerates factors with `owner_viral_verified` evidence. Source footage is not copied into generated videos.

Seedance 1.5 currently works in the 4-12 second range in this app. Studio defaults to 12 seconds and the backend validates generation runs with a maximum duration of 12 seconds.

Analytics requires real metrics for every selected variant: views, watch completion rate, average watch seconds, CTR, CVR, orders, and revenue. `/experiments/analyze` returns `400` if those metrics are missing.

Volcengine `RateLimitExceeded.EndpointTPMExceeded` means the endpoint exceeded its tokens-per-minute quota. The app retries with a longer TPM-aware delay, then marks the provider step `real_failed` if the configured endpoint still cannot serve the request.

More provider details are in `docs/provider-integration.md`.

## Submission / GitHub Safety

This repository is safe to publish when only tracked files are committed. Real provider keys, uploaded assets, generated videos, logs, and local caches are excluded by `.gitignore`.

Before uploading:

```powershell
git status --short
git grep -n -E "(AKLT[A-Za-z0-9]{10,}|Bearer [A-Za-z0-9._-]{20,}|sk-[A-Za-z0-9_-]{20,}|VOLCENGINE_API_KEY=.+|SEEDANCE_API_KEY=.+|FASTMOSS_(API_KEY|CLIENT_SECRET)=.+)" -- . ':!README.md' ':!docs/submission-checklist.md' ':!pnpm-lock.yaml' ':!apps/web/pnpm-lock.yaml'
pnpm verify
```

Expected local demo path for reviewers:

1. Copy `.env.example` to `.env.local`.
2. Fill their own Volcengine / Seedance / FastMoss credentials.
3. Run `docker compose up -d postgres`.
4. Run `python -m pip install -r apps/api/requirements.txt`.
5. Run `pnpm install`.
6. Start `pnpm dev:api` and `pnpm dev:web`.
7. Seed the public demo assets and viral library:

   ```powershell
   Invoke-RestMethod -Method Post http://127.0.0.1:8000/demo-data/seed
   ```

8. Open `http://localhost:3000`.
