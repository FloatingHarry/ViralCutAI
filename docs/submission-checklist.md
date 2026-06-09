# Submission Checklist

Use this checklist before publishing ViralCutAI to GitHub or sending it to reviewers.

## Repository Safety

- Commit only source code, public docs, lockfiles, and configuration templates.
- Do not commit `.env`, `.env.local`, `.env.*`, provider keys, uploaded assets, generated videos, or logs.
- `.gitignore` excludes local secrets, `storage/`, `.logs/`, videos, audio files, build output, caches, and dependencies.
- `.env.example` is the public provider template. Reviewers should copy it to `.env.local` and fill their own API credentials.
- The bundled demo data under `apps/api/app/static` is safe to commit: Aurora Glow product assets, 17 viral-library references, 136 factors, and local cover thumbnails.
- Do not commit the whole `storage/` directory. It contains local logs, run artifacts, generated MP4 files, and temporary editor outputs.

## Verification Commands

```powershell
git status --short
git grep -n -E "(AKLT[A-Za-z0-9]{10,}|Bearer [A-Za-z0-9._-]{20,}|sk-[A-Za-z0-9_-]{20,}|VOLCENGINE_API_KEY=.+|SEEDANCE_API_KEY=.+|FASTMOSS_(API_KEY|CLIENT_SECRET)=.+)" -- . ':!README.md' ':!docs/submission-checklist.md' ':!pnpm-lock.yaml' ':!apps/web/pnpm-lock.yaml'
pnpm verify
```

The grep command may show source code references to environment variable names or `Authorization` header construction. It should not show real credential values.

## Reviewer Run Path

1. Install Node.js 24, pnpm 11.4.0, Python 3.11, Docker Desktop, and FFmpeg.
2. Run `docker compose up -d postgres`.
3. Run `pnpm install`.
4. Run `python -m pip install -r apps/api/requirements.txt`.
5. Copy `.env.example` to `.env.local`.
6. Fill Volcengine / Seedance / FastMoss credentials as available.
7. Start the API with `pnpm dev:api`.
8. Seed the public demo assets and viral library with `Invoke-RestMethod -Method Post http://127.0.0.1:8000/demo-data/seed`.
9. Start the web app with `pnpm dev:web`.
10. Open `http://localhost:3000`.

## Demo Path

1. Seed demo data with `POST /demo-data/seed`, then confirm My Assets and Viral Library have visible data.
2. Studio: select the seeded asset collection, platform, reference mode, and template mode, then run agents.
3. Editor: inspect the three-shot timeline and regenerate one shot.
4. Editor: assemble the edited timeline into an MP4.
5. Analytics: select two successful runs, enter real metrics, and run attribution.

## Provider Notes

- Volcengine text/multimodal provider powers strategy, script, storyboard, image prompt planning, asset understanding, and experiment narrative.
- `VOLCENGINE_IMAGE_MODEL` is optional. If missing, cover image generation is marked `missing_config`.
- Seedance powers the real draft video and replacement clip generation.
- TTS, subtitle, and BGM are currently provider-ready planning outputs rather than dedicated external provider integrations.
