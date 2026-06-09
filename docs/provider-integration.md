# Provider Integration

ViralCutAI should keep the LangGraph product flow stable and swap only the provider layer when real APIs are available.

## Secret Storage

Local secrets live in the project root:

```text
.env.local
```

This file is ignored by Git through `.gitignore` and must never be committed. Use `.env.example` as the public template only.

## Runtime Selection

The runtime uses automatic provider selection. If a provider has the required key and endpoint, ViralCutAI calls it. If configuration is missing, the same Agent step can produce a clearly labeled local placeholder and internally records `mock_missing_config`. If a configured provider fails, the run records `real_failed` and does not generate replacement data.

## Provider Responsibilities

| Provider | Target capability | Current state |
| --- | --- | --- |
| Volcengine text | strategy, factor board, script, storyboard, image prompt planning, experiment analysis | real text output when `VOLCENGINE_ENDPOINT_ID` or `VOLCENGINE_TEXT_MODEL` is configured |
| Volcengine image | one Studio cover / hero image through the image generation API | real cover image only when `VOLCENGINE_IMAGE_MODEL` is configured |
| Seedance | video generation | real video task when configured, local video plan only when missing configuration |
| FastMoss | Viral Library TikTok ecommerce video signals | real Video Search import when `FASTMOSS_API_KEY` or `FASTMOSS_CLIENT_ID` / `FASTMOSS_CLIENT_SECRET` are configured |
| Analytics metrics | experiment attribution | user-entered real metrics only; no simulated A/B metrics |

## Environment Variables

```env
DATABASE_URL=postgresql+psycopg://viralcutai:viralcutai@localhost:5432/viralcutai
API_CORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000

# Copy this file to .env.local and fill provider credentials locally.
# Do not commit .env.local or real provider keys.
VOLCENGINE_API_KEY=
VOLCENGINE_BASE_URL=
# Text / chat endpoint for strategy, script, image prompt planning, and experiments.
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

## Wiring Rule

Agents should depend on provider interfaces, not vendor SDK details:

```text
LangGraph Agent
  -> Provider interface
    -> Mock provider
    -> Volcengine provider
    -> Seedance provider
```

This keeps `/generation-runs`, traces, artifacts, analytics, and UI stable when real APIs are connected.

Generation agents stay as three external LangGraph nodes, but each node may record internal substeps in `AgentStep.output.substeps`. This keeps the product simple while reducing pressure on any single LLM JSON response.

For image generation, `VOLCENGINE_IMAGE_MODEL` is required. If it is not set, the cover image substep reports "not connected" and does not call the image generation API. `VOLCENGINE_ENDPOINT_ID` and `VOLCENGINE_TEXT_MODEL` stay reserved for text and image prompt planning.

Seedance 1.5 is treated as a 4-12 second video provider. Studio defaults to 12 seconds, and `GenerationRunCreate.duration_seconds` validates the same 4-12 second range.

FastMoss import is exposed as the internal backend endpoint `POST /viral-videos/import-fastmoss`. The backend supports direct API-key bearer auth through `FASTMOSS_API_KEY`, and also supports exchanging `client_id` / `client_secret` for an access token when those credentials are provided. It calls `POST /video/v1/search` with `filter.is_ecommerce = 1`, and stores only structured analysis, public video URL, cover URL, and metrics. These records are marked `fastmoss_structured_only` with `visual_verified=false`; they do not claim observed footage.

The public repo ships bundled demo seed data under `apps/api/app/static`: Aurora Glow product assets, 17 owner-curated viral-library references, 136 factors, and local cover thumbnails. Reviewers can load the full demo set with `POST /demo-data/seed`. Local uploaded assets, generated MP4 files, logs, and run artifacts still live in the local database or `storage/` and are intentionally not included in GitHub downloads.

Selected FastMoss references can be upgraded with `POST /viral-videos/{reference_id}/attach-source-video`. The owner manually downloads or obtains the MP4, uploads it as multipart `file`, and the backend stores it under `storage/` as an `owner_viral_reference` Asset. FFmpeg keyframes and Volcengine frame understanding are then combined with FastMoss metrics to regenerate factors marked `owner_viral_verified`. The source footage remains internal evidence only and is not copied into generated videos.

Analytics requires real user-entered metrics for each selected succeeded run. `/experiments/analyze` rejects requests without views, watch completion, average watch seconds, CTR, CVR, orders, and revenue for every variant.

For real provider failures, the app preserves the failed trace and records `real_failed`. It does not synthesize replacement strategy, script, image, video, or attribution content. Volcengine `RateLimitExceeded.EndpointTPMExceeded` is a tokens-per-minute quota error; the text provider waits on a TPM-aware retry window before marking the step failed.
