# Plan: Update Hostinger Backend from Refactoring Branch

**Objective:** Update the `backend/` folder on the `integration/hostinger-backend` branch with the latest changes from `refactoring/17_12_25`, ensuring that:
1.  The new modular file structure (routes, etc.) is applied.
2.  The Hostinger-specific configuration (specifically `backend/.env`, which contains the API keys and is tracked on that branch) is **preserved**.
3.  The process is automated with minimal manual intervention.

## Prerequisites
- You are currently on the `refactoring/17_12_25` branch.
- You have committed or stashed your current changes (workspace is clean).

## Execution Steps

Run the following commands in your terminal:

```bash
# 1. Ensure your current work is saved
git add .
git commit -m "Save point: Work in progress" 

# 2. Switch to the Hostinger branch
git checkout integration/hostinger-backend

# 3. Pull the backend folder ONLY from the refactoring branch
# This updates all files in backend/ to match the refactoring branch.
# IMPORTANT: Since 'backend/.env' does not exist in the refactoring branch,
# git will NOT delete the existing 'backend/.env' on the Hostinger branch.
git checkout refactoring/17_12_25 -- backend/

# 4. Verify the critical configuration file is still there
ls -l backend/.env

# 5. Stage and Commit the changes
git add backend/
git commit -m "feat(backend): sync backend changes from refactoring branch"

# 6. Push to Hostinger
git push origin integration/hostinger-backend

# 7. Return to your working branch
git checkout refactoring/17_12_25
```

## Why this is safe
- **`main.py`**: The file will be completely replaced by the new version. This is correct because the entire architecture has changed (endpoints moved to `backend/api/routes/`). The old `main.py` is incompatible with the new folder structure.
- **`backend/.env`**: This file is tracked on `integration/hostinger-backend` but **untracked/missing** on `refactoring/17_12_25`. When you run `git checkout refactoring... -- backend/`, Git only updates files that exist in the source. It does **not** delete files in the destination that are missing in the source (unlike a full branch merge). Thus, your API keys and secrets remain safe.
- **Host/Port Config**: The new `main.py` relies on standard `uvicorn` execution. Hostinger likely runs the app via a command like `uvicorn backend.main:app --host 0.0.0.0`, which overrides any internal code settings anyway.

## Troubleshooting
If you encounter a "conflict" or if `backend/.env` is accidentally deleted (unlikely):
1.  **Restore .env**: `git checkout HEAD -- backend/.env` (brings it back from the last Hostinger commit).
2.  **Verify**: Check the file content before pushing.
