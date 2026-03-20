# Notepad
<!-- Auto-managed by OMC. Manual edits preserved in MANUAL section. -->

## Priority Context
<!-- ALWAYS loaded. Keep under 500 chars. Critical discoveries only. -->
PharmPort git setup: Create .gitignore, initialize repo, and establish version control for pharmaceutical database project with Azure PostgreSQL integration.

## Working Memory
<!-- Session notes. Auto-pruned after 7 days. -->
### 2026-03-16 13:17
PharmPort Git Setup Plan

## Phase 1: Create .gitignore
- Exclude .env (credentials: Azure conn strings, API keys)
- Exclude __pycache__/ and *.pyc (Python cache)
- Exclude .omc/ (session/state metadata)
- Exclude any other generated/transient files

## Phase 2: Initialize Repository
- git init
- Add initial commit with source code and docs
- Verify all sensitive files are properly excluded

## Phase 3: Verify Setup
- Confirm .gitignore is working
- Check git status shows only intended files
- Validate no credentials are tracked

## Files to Commit (15 total):
- *.py: sort_and_embed.py, analysis.py, common.py, embedding_service.py, match_ingredient.py, match_ingredient_v2.py
- *.txt: requirements.txt
- *.md: claude.md, methodology.md
- Directory: docs/

## Files to Exclude:
- .env (1.1K) - credentials
- __pycache__/ - Python cache
- .omc/ - metadata
- *.pyc - compiled Python


## MANUAL
<!-- User content. Never auto-pruned. -->

