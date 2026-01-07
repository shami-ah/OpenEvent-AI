---
name: oe-release-readiness
description: "Pre-merge/release readiness checklist for OpenEvent-AI. Use when preparing a PR for production: run the fastest validation lanes first (compile/import, smoke suite, deterministic site-visit trace), then escalate to full suites or integration checks as needed."
---

# oe-release-readiness

## Fast gates (run in this order)

1. Compile/import check:
   - `python3 -c "from main import app; print('OK')"`

2. Fast backend smoke suite:
   - `pytest tests/smoke -v`

3. Regression tests (product flow, catering):
   - `pytest tests/regression -v`

4. Detection tests (workflow routing):
   - `pytest tests/detection -v -q`

## Full gates (only if the change touches workflow logic)

- Full test suite:
  - `pytest tests -v`

## Hygiene gates (quick checks that prevent "LLM-ish" regressions)

- No new debug prints in runtime code:
  - `rg -n "print\\(" --glob "*.py" -g "!tests/*" -g "!scripts/*" | head -20`

---

## Deployment to Production (main branch)

**⚠️ CRITICAL: Backend-only deployment!**

See full guide: `docs/plans/completed/DEPLOYMENT_UPDATE_PLAN.md`

### Pre-deployment checklist

1. **Check for frontend files** (MUST be empty):
   ```bash
   git diff --name-only origin/main..HEAD | grep -E "^atelier"
   ```

2. **If frontend files found**, exclude them:
   ```bash
   git checkout main
   git merge development-branch --no-commit
   git rm -r atelier-ai-frontend/
   git commit -m "Merge: backend only"
   ```

3. **If frontend accidentally pushed**, remove it:
   ```bash
   git checkout main
   git rm -r atelier-ai-frontend/
   git commit -m "chore: remove frontend from main"
   git push origin main
   ```

### Deployment steps

```bash
# 1. Stash local changes
git stash push -m "temp"

# 2. Checkout and update main
git checkout main && git pull origin main

# 3. Merge (verify no frontend first!)
git merge development-branch

# 4. Verify no frontend
git ls-tree --name-only HEAD | grep atelier || echo "✅ Clean"

# 5. Push
git push origin main

# 6. Return to dev
git checkout development-branch && git stash pop
```

### Branch structure

| Branch | Purpose | Frontend? |
|--------|---------|-----------|
| `main` | Production (Vercel) | **NO** |
| `development-branch` | Development | Yes |

---

## Claude Code shortcut

- Keep `.claude/commands/validate.md` up to date and run `/validate` for a full-stack lane.
