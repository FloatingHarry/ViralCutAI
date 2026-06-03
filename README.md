# ViralCutAI

Agent-based AIGC commerce video workspace for the AI full-stack challenge.

## Stack

- Frontend: Next.js App Router, React, TypeScript, Tailwind CSS
- Backend: FastAPI, Python, SQLAlchemy 2.0
- Agent runtime: LangGraph generation graph and experiment analysis graph
- Data: PostgreSQL ORM tables for assets, viral factors, generation runs, artifacts, traces, and experiments
- Providers: automatic Volcengine text/image and Seedance video calls, with local placeholders only for capabilities that are not connected

## Quick Start

```powershell
docker compose up -d postgres
pnpm install
python -m pip install -r apps/api/requirements.txt

pnpm dev:api
pnpm dev:web
```

Open:

- Web: http://localhost:3000
- API docs: http://localhost:8000/docs

## Product Flow

1. Create a private Asset Collection in My Assets, then upload product images or videos. Images are analyzed through the Volcengine multimodal endpoint; videos are keyframe-sampled with FFmpeg and analyzed through the same endpoint.
2. Analyze external reference URLs in Viral Library. The system stores source metadata, structured playbook analysis, factor boards, and creative templates without copying source media.
3. Cluster two to five external references into n:1 creative templates when a reusable pattern appears.
4. Open Studio, choose Viral Rewrite, Template Fusion, or Auto Mix, then select private assets plus external reference analysis, templates, and factors.
5. The Generation Graph runs Viral Strategy Agent, Script & Storyboard Agent, and Render & Review Agent.
6. Studio shows factor board, storyboard, cover image status, video artifacts, voice/subtitle/BGM plans, preview, export manifest, and compliance.
7. Analytics selects two to four succeeded generation runs, accepts real manually entered metrics, and runs the Attribution & Experiment Agent.
8. Trace Console shows both Generation Graph and Experiment Analysis Graph traces.

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
- `GET /viral-factors`
- `GET /creative-templates`
- `POST /creative-templates/build`
- `POST /generation-runs`
- `GET /generation-runs`
- `GET /generation-runs/{run_id}`
- `GET /generation-runs/{run_id}/export`
- `POST /generation-runs/{run_id}/retry`
- `PATCH /generation-runs/{run_id}/storyboard/{shot_id}`
- `POST /generation-runs/{run_id}/storyboard/{shot_id}/regenerate`
- `POST /generation-runs/{run_id}/render-preview`
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
| Viral video analysis | Dynamic reference analysis through `/viral-videos/analyze` |
| Viral factors and templates | Global Viral Library is generated only from external reference analysis; Studio run factors stay on the run |
| Script generation and storyboard | LangGraph Script & Storyboard Agent with internal copy/storyboard/prompt substeps |
| One-click video generation | One Studio action creates provider-tracked preview artifacts, one real cover image when configured, and real Seedance video when configured |
| Task progress | `RunEvent` stages and Agent traces |
| Preview / export | Real video URL when available, plus JSON export manifest |
| TTS / subtitles / BGM | Provider-pending planning artifacts |
| Generation trace | `AgentStep` plus Trace Console |
| A/B comparison and attribution | Experiment Analysis Graph over real manually entered metrics |
| Compliance flow | Render & Review Agent with conditional rewrite |
| Shot-level intervention | Patch/regenerate/render-preview interfaces and lightweight UI |
| CI/CD | GitHub Actions compile, lint, and build |

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
API_CORS_ORIGINS=http://localhost:3000
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

PROVIDER_REQUEST_TIMEOUT_SECONDS=120
SEEDANCE_POLL_SECONDS=90
SEEDANCE_POLL_INTERVAL_SECONDS=5

UPLOAD_DIR=storage/uploads
```

Use `.env.example` as the public template and put real local secrets in `.env.local`. The local secret file is ignored by Git. Uploaded assets are stored under `storage/`, which is also gitignored.

Provider roles are intentionally separated: `VOLCENGINE_ENDPOINT_ID` / `VOLCENGINE_TEXT_MODEL` power text generation and image prompt planning, `VOLCENGINE_IMAGE_MODEL` powers real cover image generation, and `SEEDANCE_ENDPOINT_ID` / `SEEDANCE_MODEL` powers video generation. If the image model is missing, the cover image is reported as not generated and the API does not call the image endpoint.

Seedance 1.5 currently works in the 4-12 second range in this app. Studio defaults to 12 seconds and the backend validates generation runs with a maximum duration of 12 seconds.

Analytics requires real metrics for every selected variant: views, watch completion rate, average watch seconds, CTR, CVR, orders, and revenue. `/experiments/analyze` returns `400` if those metrics are missing.

Volcengine `RateLimitExceeded.EndpointTPMExceeded` means the endpoint exceeded its tokens-per-minute quota. The app retries with a longer TPM-aware delay, then marks the provider step `real_failed` if the configured endpoint still cannot serve the request.

More provider details are in `docs/provider-integration.md`.
