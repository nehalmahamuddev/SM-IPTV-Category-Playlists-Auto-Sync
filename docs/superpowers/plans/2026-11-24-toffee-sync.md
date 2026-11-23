# Toffee Category Auto-Sync Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create a dedicated sync script and GitHub Actions workflow to fetch Toffee TV data, sync it to Supabase under the `toffee` category every 15 minutes, and update local playlist and JSON artifacts.

**Architecture:** A standalone Python script `scripts/sync_toffee.py` ingests remote JSON, formats player M3U and JSON outputs, and uses Supabase PostgREST API to upsert `channels` and `stream_servers` while deactivating missing channels. A GitHub Actions workflow `.github/workflows/toffee_sync.yml` runs on `workflow_dispatch` to be triggered by external schedulers (cron-job.org).

**Tech Stack:** Python 3.12, `requests`, Supabase PostgREST API, GitHub Actions.

**Spec:** `docs/superpowers/specs/2026-11-24-toffee-sync-design.md`

## Global Constraints
* Channel IDs must be prefixed with `toffee_` (e.g. `toffee_somoy_tv`).
* Target category in Supabase is strictly `toffee`.
* Do not delete missing channels; mark them `is_live=False` and server `active=False`.
* Workflow trigger must be `workflow_dispatch` only.
* Git commits must use `[skip ci]`.

## Review Focus
1. Malformed or empty JSON response from upstream URL: Gracefully abort without corrupting local files or deactivating all channels.
2. Channel name deduplication: If two channels generate identical slugs, disambiguate with an incremental suffix.
3. Network timeout or Supabase 5xx: Fail-fast with clear stderr logging so the action fails and alerts cron-job.org.
4. Player M3U headers: Ensure `#EXTVLCOPT` and `#EXTHTTP` are properly emitted for player compatibility.
5. Missing stream URLs in source: Skip channel entries without valid `link`.

---

### Task 1: Create Unit Tests for Toffee Normalization & Parser
**Files:**
- Create: `tests/test_sync_toffee.py`
- Test: `tests/test_sync_toffee.py`

**Interfaces:**
- Produces: `normalize_channel(raw_ch: dict) -> dict`, `slugify_channel_name(name: str) -> str`

- [ ] **Step 1: Write unit tests for channel parsing and slug generation**
- [ ] **Step 2: Run pytest to verify test failure (function missing)**
- [ ] **Step 3: Implement helper parsing functions**
- [ ] **Step 4: Verify test passes**

---

### Task 2: Implement Complete `scripts/sync_toffee.py`
**Files:**
- Create: `scripts/sync_toffee.py`
- Consumes: Parsing logic from Task 1, Supabase PostgREST API
- Produces: `playlists/toffee.m3u`, `output/toffee.json`, Supabase database updates

- [ ] **Step 1: Implement CLI flags (`--dry-run`, `--output-dir`, `--playlists-dir`) and data fetching**
- [ ] **Step 2: Implement local M3U & JSON file generation**
- [ ] **Step 3: Implement Supabase reconcile logic (upsert active, deactivate missing)**
- [ ] **Step 4: Run script with `--dry-run` to verify against live remote source**

---

### Task 3: Create GitHub Actions Workflow `.github/workflows/toffee_sync.yml`
**Files:**
- Create: `.github/workflows/toffee_sync.yml`

- [ ] **Step 1: Create workflow with `workflow_dispatch:` trigger**
- [ ] **Step 2: Add Python setup, dependency install, script execution, and git commit/push**
- [ ] **Step 3: Validate workflow YAML syntax**

---

### Task 4: Execute Initial Live Sync & Verification
- [ ] **Step 1: Run `scripts/sync_toffee.py` live to populate Supabase and local files**
- [ ] **Step 2: Verify rows in Supabase `channels` and `stream_servers`**
- [ ] **Step 3: Verify contents of `playlists/toffee.m3u` and `output/toffee.json`**
