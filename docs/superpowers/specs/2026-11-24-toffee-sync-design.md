# Toffee Category Auto-Sync Design

## 1. Intent & Why
Provide an automated, high-reliability sync pipeline for the Toffee TV category in SM-IPTV, fetching fresh streams and expiring tokens from `sm-monirulislam/Toffee-Auto-Update`, persisting them to Supabase (`public.channels` and `public.stream_servers` under category `toffee`), and generating local player playlists and JSON catalogs.

## 2. Goals & Non-Goals
* **Goals:**
  * Fetch live channel and stream data from `https://raw.githubusercontent.com/sm-monirulislam/Toffee-Auto-Update/refs/heads/main/toffee_data.json`.
  * Normalize channel names and assign non-colliding canonical IDs prefixed with `toffee_` (e.g. `toffee_somoy_tv`).
  * Mirror stream URLs and HTTP headers (`user-agent`, `Host`, etc.) into Supabase `channels` and `stream_servers`.
  * Deactivate any channels in Supabase that are missing from the source (`is_live = False`, `active = False`).
  * Generate `playlists/toffee.m3u` (with `#EXTVLCOPT` and `#EXTHTTP` player headers) and `output/toffee.json`.
  * Provide a dedicated GitHub Actions workflow triggered via `workflow_dispatch` every 15 minutes by external schedulers (e.g. cron-job.org).
* **Non-Goals:**
  * Modifying existing Bangla or Sports linear channel records in Supabase.
  * Storing or executing token generation algorithms directly (the source JSON already provides updated tokens).

## 3. Data Schema Mapping
* **Supabase `channels`**:
  * `id`: `toffee_<slug>`
  * `name`: Clean channel name
  * `logo`: Provided URL
  * `category`: `toffee`
  * `country`: `BD`
  * `language`: `bn`
  * `is_live`: `True` (or `False` if missing)
  * `quality`: `HD`
  * `stream_url`: Link from JSON
  * `headers`: Header dict from JSON
  * `sort_order`: Sequential index (1, 2, 3...)
* **Supabase `stream_servers`**:
  * `channel_id`: `toffee_<slug>`
  * `name`: `Server 1 (Toffee Live)`
  * `stream_url`: Link from JSON
  * `headers`: Header dict from JSON
  * `scheme`: `0`
  * `has_header`: `True`
  * `sort_order`: `1`
  * `active`: `True` (or `False` if missing)

## 4. Automation & Triggers
* Dedicated workflow `.github/workflows/toffee_sync.yml`.
* Trigger: `on: workflow_dispatch:`
* Commits updated `playlists/toffee.m3u` and `output/toffee.json` using `github-actions[bot]` with `[skip ci]`.
