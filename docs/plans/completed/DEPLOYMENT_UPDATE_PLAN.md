# Plan: Deploy Backend to Production (Vercel/Main)

**Objective:** Deploy backend changes from `development-branch` to `main` for Vercel production deployment.

## CRITICAL: Backend-Only Deployment

**⚠️ NEVER push frontend files (`atelier-ai-frontend/`) to main!**

- Frontend is deployed separately via Lovable
- Main branch should contain ONLY backend code
- Always verify no frontend files are included before pushing

---

## Prerequisites

1. All changes committed and pushed to `development-branch`
2. Tests pass on development-branch
3. Workspace is clean (stash local dev files if needed)

---

## Step-by-Step Deployment Process

### Step 1: Verify No Conflicts

```bash
# Fetch latest
git fetch origin main

# Check commits ahead (should show your changes)
git log --oneline origin/main..HEAD

# Check if main has new commits (should be empty if synced)
git log --oneline HEAD..origin/main

# Verify clean merge possible
git merge --no-commit --no-ff origin/main
git merge --abort  # Cancel test merge
```

### Step 2: Check for Frontend Files

**CRITICAL - Run before every merge:**

```bash
# List any frontend files that would be merged
git diff --name-only origin/main..HEAD | grep -E "^atelier" | head -20

# If files found, you need to exclude them!
```

### Step 3: Merge to Main (Backend Only)

**Option A: If NO frontend files in diff (clean merge)**

```bash
git stash push -m "temp: local dev files"
git checkout main
git pull origin main
git merge development-branch -m "Merge: backend fixes from development-branch"
git push origin main
git checkout development-branch
git stash pop
```

**Option B: If frontend files exist (selective merge)**

```bash
git stash push -m "temp: local dev files"
git checkout main
git pull origin main

# Merge but don't commit yet
git merge development-branch --no-commit

# Remove frontend files from staging
git reset HEAD atelier-ai-frontend/
git checkout -- atelier-ai-frontend/

# Or if they were added:
git rm -r --cached atelier-ai-frontend/

# Commit backend-only changes
git commit -m "Merge: backend fixes from development-branch (frontend excluded)"
git push origin main
git checkout development-branch
git stash pop
```

**Option C: If frontend already pushed by mistake**

```bash
git checkout main
git rm -r atelier-ai-frontend/
git commit -m "chore: remove frontend from main (backend-only deployment)"
git push origin main
```

### Step 4: Verify Deployment

```bash
# Confirm no frontend on main
git ls-tree --name-only origin/main | grep -E "^atelier" || echo "✅ No frontend"

# Verify backend files are there
git ls-tree --name-only origin/main | grep -E "^(api|workflows|services|main.py)" | head -10
```

---

## Post-Deployment Verification

1. Check Vercel deployment status
2. Test health endpoint: `curl https://your-vercel-url/api/workflow/health`
3. Verify no build errors in Vercel dashboard

---

## Branch Structure

| Branch | Purpose | Contains |
|--------|---------|----------|
| `main` | Production (Vercel) | Backend only |
| `development-branch` | Development | Backend + Frontend |
| `integration/hostinger-backend` | Legacy (deprecated) | Old nested structure |

---

## Checklist

Before every push to main:

- [ ] All tests pass on development-branch
- [ ] No frontend files (`atelier-ai-frontend/`) in merge
- [ ] Syntax check: `python3 -c "from main import app; print('OK')"`
- [ ] Commit message describes what was merged
- [ ] Vercel deployment succeeds

---

## Related Files

- Skill: `.claude/skills/oe-release-readiness/SKILL.md`
- Deploy docs: `deploy/README.md`
- CI workflow: `.github/workflows/workflow-tests.yml`
