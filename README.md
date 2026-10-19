# SM IPTV Playlists & Multi-Stream Sync

> **Automated IPTV pipeline running every 30 minutes via GitHub Actions.**  
> Fetches raw channel feeds, refines channels into canonical IDs with multiple backup stream servers, and synchronizes directly to Supabase.

---

## 🚀 Refined Multi-Stream Playlists (`output/`)

In the refined playlists, multiple streams and qualities (HD, FHD, 4K, SD) for the same channel are grouped under a single canonical `tvg-id` with clear server labels (`Server 1 (HD)`, `Server 2 (FHD)`). This enables IPTV players (TiviMate, OTT Navigator) to switch seamlessly between backup servers.

| Playlist | Channels | Servers | Direct Raw Link |
|---|---|---|---|
| **All Channels (Refined Master)** | **283** | **292** | [`output/all.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/all.m3u) |
| **Bangla** | 65 | 65 | [`output/bangla.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/bangla.m3u) |
| **Sports** | 24 | 24 | [`output/sports.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/sports.m3u) |
| **Indian Bangla** | 9 | 11 | [`output/indian_bangla.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/indian_bangla.m3u) |
| **Hindi** | 36 | 40 | [`output/hindi.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/hindi.m3u) |
| **Documentary** | 6 | 8 | [`output/documentory.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/documentory.m3u) |
| **Kids** | 11 | 12 | [`output/kids.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/kids.m3u) |
| **Music** | 13 | 13 | [`output/music.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/music.m3u) |
| **Islamic** | 6 | 6 | [`output/islamic.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/islamic.m3u) |
| **Live Sports Events** | 113 | 113 | [`output/live_sports.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/live_sports.m3u) |

### Structured Data for Database Ingestion
* **JSON Catalog:** [`output/channels.json`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/output/channels.json)

---

## 📺 Raw Categorized Playlists (`playlists/`)

Direct, unmodified stream lists per category as retrieved from the SM IPTV upstream API.

| Category | Streams | Raw Link |
|---|---|---|
| **All Channels & Events (Raw)** | 293 | [`playlists/all.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/all.m3u) |
| **Bangla** | 65 | [`playlists/bangla.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/bangla.m3u) |
| **Sports** | 24 | [`playlists/sports.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/sports.m3u) |
| **Indian Bangla** | 11 | [`playlists/indian_bangla.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/indian_bangla.m3u) |
| **Hindi** | 40 | [`playlists/hindi.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/hindi.m3u) |
| **Documentary** | 8 | [`playlists/documentory.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/documentory.m3u) |
| **Kids** | 13 | [`playlists/kids.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/kids.m3u) |
| **Music** | 13 | [`playlists/music.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/music.m3u) |
| **Islamic** | 6 | [`playlists/islamic.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/islamic.m3u) |
| **Live Sports Events** | 113 | [`playlists/live_sports.m3u`](https://raw.githubusercontent.com/nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync/main/playlists/live_sports.m3u) |

---

## 🛠️ Pipeline Architecture

1. **`scripts/generate_category_playlists.py`**:
   Connects to SM IPTV Cloudflare Worker API using dynamic bootstrap discovery and bearer token authentication, generating raw `.m3u` files in `playlists/`.
2. **`scripts/refine_playlists.py`**:
   Parses `playlists/`, extracts channel metadata, strips quality suffixes, generates clean canonical channel slugs, groups backup servers, and outputs refined `.m3u` files and `output/channels.json` into `output/`.
3. **`scripts/sync_output_to_supabase.py`**:
   Reads `output/channels.json` and updates Supabase (`public.channels` and `public.stream_servers`) using a clean Reconcile/Mirror strategy for linear TV channels.
