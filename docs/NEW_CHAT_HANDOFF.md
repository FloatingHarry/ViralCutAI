# ViralCutAI New Chat Handoff

Last updated: 2026-06-03

This file is the clean handoff for opening a new Codex conversation in `D:\Desktop\viralcutai`. It intentionally ignores old reverted plans unless they matter as warnings.

## 1. Current Baseline

- Project root: `D:\Desktop\viralcutai`.
- Frontend: Next.js App Router + React + TypeScript in `apps/web`.
- Backend: FastAPI + Python in `apps/api`.
- Workflow runtime: LangGraph Python in `apps/api/app/services/agent_workflows.py`.
- Database: PostgreSQL via Docker Compose service `viralcutai-postgres`.
- Current Docker service check: Postgres is healthy on port `5432`.
- Current API check: `GET http://127.0.0.1:8000/health` returns `200`.
- Current web check: `GET http://localhost:3000/studio` returns `200`.
- Git status is not a normal clean tracked repo: most files show as `??` untracked. Do not assume `git restore` can recover previous versions.

Important baseline decision:

- The user manually rolled back the problematic `Segment Regeneration and Global Draft Prompt Fix Plan`.
- Do not re-apply that plan as-is.
- Do not assume old conversation state is current truth. Inspect files and API before changing anything.

## 2. Provider Truth Rules

The user strongly prefers truthful provider behavior:

- If a provider is not configured, placeholder/mock is allowed only as "not connected".
- If a real configured API is called and fails, do not generate fake replacement output.
- Show failure clearly.
- Do not mix real and fake data in a way that looks like a successful real result.
- Never print or commit API keys from `.env.local`.
- Do not paste signed Seedance/TOS video URLs into chat or docs; redact them.

Current `/health` provider status:

- `text_provider`: configured
- `image_understanding_provider`: configured
- `video_frame_understanding_provider`: configured
- `image_plan_provider`: configured
- `image_generation_provider`: missing_config
- `video_provider`: configured
- `experiment_provider`: configured

Interpretation:

- Volcengine text/multimodal endpoint is configured and used for strategy, script, image prompt planning, asset understanding, and experiment analysis.
- Seedance video provider is configured.
- Real image generation is not configured because `VOLCENGINE_IMAGE_MODEL` is empty/missing. Image prompt planning is still text-based and configured.

## 3. How To Run

From `D:\Desktop\viralcutai`:

```powershell
docker compose up -d postgres
python -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000 --app-dir apps/api
D:\tools\npm-global\pnpm.cmd dev:web
```

Open:

- Studio: `http://localhost:3000/studio`
- API health: `http://127.0.0.1:8000/health`

Useful checks:

```powershell
python -m compileall apps\api\app
D:\tools\npm-global\pnpm.cmd --dir apps/web lint
D:\tools\npm-global\pnpm.cmd --dir apps/web build
```

## 4. Main Backend APIs

Core health:

- `GET /health`

My Assets / private asset library:

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

Viral Library / external playbook:

- `GET /viral-videos`
- `POST /viral-videos/analyze`
- `GET /viral-factors`
- `GET /creative-templates`
- `POST /creative-templates/build`

Generation:

- `POST /generation-runs`
- `GET /generation-runs`
- `GET /generation-runs/{run_id}`
- `GET /generation-runs/{run_id}/export`
- `POST /generation-runs/{run_id}/retry`
- `PATCH /generation-runs/{run_id}/storyboard/{shot_id}`
- `POST /generation-runs/{run_id}/storyboard/{shot_id}/regenerate`
- `POST /generation-runs/{run_id}/storyboard/{shot_id}/regenerate-clip`
- `POST /generation-runs/{run_id}/render-preview`
- `POST /generation-runs/{run_id}/assemble-preview`
- `GET /generation-runs/{run_id}/assembled-video`

Analytics:

- `POST /experiments/analyze`
- `GET /experiments`
- `GET /experiments/{id}`

## 5. Current Frontend Pages

Navigation in `apps/web/src/components/app-shell.tsx`:

- `/studio` - Agent Studio main generation UI.
- `/assets` - My Assets private asset collection UI.
- `/viral-library` - external viral playbook/reference/factor/template UI.
- `/agent` - Trace Console for generation and experiment traces.
- `/analytics` - A/B Experiment Lab using real manually entered metrics.

There is still an `apps/web/src/app/script-lab` folder, but the active navigation does not list Script Lab.

## 6. Current Data Snapshot

Current database snapshot from local API:

- Asset collections: `0`
- Assets: `0`
- Viral videos: `0`
- Viral factors: `0`
- Creative templates: `0`
- Experiments: `0`
- Generation runs: at least `5`

Latest runs:

- `3979fdc6-7a8d-4381-b606-f86872178bb6`: `succeeded`
- `85466c30-fcc4-4ea2-a870-a754131c405d`: `failed`
- `34e07214-be52-4d3f-9cc4-07152b11d5ac`: `failed`
- `4e8476be-132e-4688-968d-2f4385cc3e78`: `failed`
- `e6f104b1-bd4e-4a0b-9364-c9f35589f9b3`: `succeeded`

Known failure cause:

- Recent failed run `34e07214...` failed in `Script & Storyboard Agent`, substep `prompt_package`.
- `copy_draft` succeeded with Volcengine.
- `storyboard_plan` succeeded with Volcengine.
- `prompt_package` returned malformed JSON: `Expecting ',' delimiter`.
- JSON repair did not recover it, and because real provider failures should not be mocked, the run failed.

This means failures can be caused by occasional LLM structured JSON instability, not necessarily Seedance or LangGraph itself.

## 7. Current Architecture Notes

Generation flow:

- Main generation is through `GenerationRun`.
- LangGraph has three external generation Agents:
  - `Viral Strategy Agent`
  - `Script & Storyboard Agent`
  - `Render & Review Agent`
- There is also an experiment graph with `Attribution & Experiment Agent`.
- The generation graph has internal provider substeps, including strategy brief, factor packaging, copy draft, storyboard plan, prompt package, render/review media artifacts.

Video behavior:

- Studio duration defaults to `12s`.
- Seedance 1.5 is treated as supporting `4-12s` in this app.
- Current preferred creative interpretation: Generate one AI video draft, then later refine/edit. Be careful: previous experiments around "three independent clips" caused confusion.

Asset behavior:

- My Assets is the private user asset library.
- Viral Library is the external public playbook/methodology library.
- Private user assets and Studio outputs should not automatically enter Viral Library.

Analytics behavior:

- Analytics should not use simulated experiment tables.
- It should compare 2-4 succeeded generation runs.
- User must manually enter real metrics before running Attribution Agent.

## 8. Known Pain Points / Do Not Repeat

Do not reintroduce the old `Segment Regeneration and Global Draft Prompt Fix Plan` as one large patch.

Why it was rejected:

- It mixed several concerns: segment status, global prompt UI, backend state machine, replacement clip failure semantics.
- The user could not tell what changed or why.
- It made debugging harder.

If segment regeneration is revisited, do it in smaller steps:

1. Observe and display current segment/replacement state without changing backend semantics.
2. Add explicit UI feedback after clicking `Regenerate segment`.
3. Only then adjust backend state, with a separate narrow patch.

Do not silently convert real provider failures into mock outputs.

Do not change `prompt_package` into local packaging unless the user explicitly approves it. The user paused that idea because they wanted to understand why the failure occurred first.

## 9. Recommended Next Steps

Recommended first step in a new chat:

1. Read this file.
2. Inspect current code/API briefly.
3. Create a safe baseline before further code changes, because the repo is largely untracked.

Recommended next product work:

- First stabilize baseline and version control.
- Then improve observability around structured LLM failures:
  - show which Agent substep failed,
  - show provider message,
  - show retry guidance,
  - avoid exposing raw secrets or signed URLs.
- Then decide how to make `prompt_package` more stable:
  - Option A: keep it as LLM JSON, but split per shot and add stronger repair/retry.
  - Option B: make it local deterministic packaging from the already real script/storyboard.
  - Option C: run LLM prompt polish as optional enhancement after a successful base draft.

Recommended feature direction after stability:

- My Assets: add real sample/upload flow and test image/video multimodal understanding.
- Viral Library: later connect FastMoss/Kalodata API after user obtains access.
- Creation module: clarify editing model before deep implementation. The likely desired meaning is: generate an AI draft video first, then provide a workbench to refine/replace segments and assemble final MP4.

## 10. Instructions For The Next Assistant

- Do not trust memory from the old conversation.
- Treat this file plus live repo/API inspection as source of truth.
- Do not mutate files before explaining the exact narrow change.
- Use `rg` for search.
- Use `apply_patch` for edits.
- Avoid printing `.env.local` or any secret values.
- Redact provider video URLs and signed URLs.
- Before doing large feature work, strongly recommend creating a Git baseline or backup.
