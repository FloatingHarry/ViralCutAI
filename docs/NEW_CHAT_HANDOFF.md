# ViralCutAI New Chat Handoff

Updated: 2026-06-09

## Current Goal

ViralCutAI is an ecommerce short-video AIGC workflow for:

1. submitting private product assets,
2. selecting or retrieving viral factors,
3. generating a 12-second TikTok-style draft,
4. editing/replacing segments,
5. analyzing real performance metrics.

This repo is local-only right now. Do not push to GitHub unless explicitly requested.

## Privacy / Git Safety

Keep these out of Git:

- `.env`, `.env.local`, `.env.*`
- `storage/`
- `videos/`
- `node_modules/`
- `apps/web/.next/`
- logs, caches, build output

Current `.gitignore` covers the above. API keys belong only in local env files.

## Services

Typical local services:

- API: `http://127.0.0.1:8000`
- Web: `http://localhost:3000`
- Postgres: local Docker container used by the API

Use `http://localhost:3000` for the web app in dev. Next dev can warn or break HMR when opened through `127.0.0.1:3000`.

## Current Providers

Recent health check showed:

- Volcengine text provider: configured
- image understanding provider: configured
- video frame understanding provider: configured
- image plan provider: configured
- Seedance video provider: configured
- FastMoss provider: configured
- image generation provider: missing config

TTS/BGM/subtitle providers are still planning/mock outputs.

## Important Implemented Areas

### Asset Library

- Asset library now treats assets as product asset collections, not isolated files.
- Preset Aurora Glow Bottle collection exists with two product images and structured slices.
- Assets and slices are used for Studio retrieval and prompt grounding.
- User-facing asset UI was simplified toward: product name/details + images/videos + description.

### Viral Library / FastMoss

- FastMoss imports are backend/internal, not normal user UI.
- FastMoss records start as structured-only viral candidates.
- Owner can manually attach verified MP4 later; keyframes and visual verification then enrich the viral record.
- Viral Library UI was compacted; video-verified entries have cover/detail display.
- Template selection uses UID input rather than awkward scroll selection.

### Studio Generation

- Current generation is 12 seconds with fixed 3 segments:
  - `shot-1` Hook, 4s
  - `shot-2` Proof + Use, 4s
  - `shot-3` CTA, 4s
- Recent Aurora run used private asset retrieval correctly.
- Auto viral reference matching was too loose and matched a cologne FastMoss reference for Aurora Glow Bottle. This has been fixed after that run: automatic reference now requires product-name core token matches, not only broad category matches.
- Future Aurora runs should return no automatic viral reference unless a truly strong match exists.

### Editor / Segment Editing

- Editor has a total-video preview plus independent 4-second segment previews.
- Backend route exists for segment clip preview:
  - `GET /generation-runs/{run_id}/editor-clip-video?shot_id=shot-1&source_type=draft_segment`
- Verified with ffprobe that the three latest draft segment previews are each exactly 4.0 seconds.
- Editor supports timeline clips, remove range, append/replace sources, assemble/export.
- Current UI is too complex and should be simplified into an "Editor Lite" default view.

### Segment Regeneration

- Single segment replacement uses Seedance replacement clip generation.
- Latest attempted `shot-2` replacement failed because Seedance request hit:
  - `[SSL: UNEXPECTED_EOF_WHILE_READING]`
- This was a provider/network SSL EOF before a task id was returned, not a duration/schema issue.
- Seedance create/poll now has retry handling for transient SSL/transport/429/5xx errors.
- The failed old replacement artifact remains failed; retry the segment manually in the UI to use the new retry logic.

### Analytics / Attribution

- Analytics no longer has demo metric buttons.
- It now shows validation reasons when the attribution button cannot run.
- Results now include chart-style UI:
  - overall score,
  - watch completion,
  - CTR,
  - revenue per 1k views,
  - factor impact ranking.
- Volcengine experiment JSON failures no longer fail the whole experiment. If provider narrative JSON is malformed, backend falls back to deterministic local attribution using user-entered real metrics.

## Latest Known Run Notes

Latest inspected run:

- `0bf4c0bf-08af-460c-8be2-9510179e3810`
- status: `succeeded`
- product: Aurora Glow Bottle
- asset retrieval: used Aurora asset collection and slices
- viral factors: 8 factor board entries
- old auto reference: cologne FastMoss reference was incorrectly included before the matcher fix
- `shot-2` replacement clip: failed from Seedance SSL EOF
- draft segment previews: each verified as 4 seconds

Because matching was fixed after this run, create a fresh run to verify the new no-hard-match behavior.

## Current UX Concerns / Next Work

Recommended next changes:

1. Simplify Editor default UI.
   - Show total video on top/left.
   - Show three 4-second segment cards.
   - Right inspector only: regenerate this segment, replace with asset, edit copy, assemble.
   - Move remove-range, append clip, source-type controls into Advanced.

2. Simplify Studio input.
   - Keep product name and asset collection.
   - Merge selling points, audience, material notes, creative goal, visual style into one "Campaign brief" textarea.
   - Frontend can still map the brief into existing backend fields, so schema does not need a big migration.

3. Re-run a fresh Aurora generation.
   - Confirm no unrelated cologne reference is selected.
   - Confirm private assets remain in prompt/source assets.

4. Retry single-segment regeneration.
   - Confirm new Seedance retry logic handles transient SSL/network failures.
   - If provider fails again, inspect artifact payload failure_reason.

5. Keep TTS/BGM as future work.
   - Current exported videos may use draft audio or mock planning depending on assembly path.

## Verification Recently Run

Commands recently passed:

```powershell
python -m compileall apps/api/app
pnpm --dir apps/web lint
pnpm --dir apps/web build
```

Editor clip preview check:

- `shot-1`: 4.0s
- `shot-2`: 4.0s
- `shot-3`: 4.0s

## Do Not Forget

- Do not commit or upload local videos.
- Do not expose FastMoss, Volcengine, or Seedance keys.
- Keep commits local unless the user explicitly asks to push.
