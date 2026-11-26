#!/usr/bin/env python3
"""
SM IPTV Latest Supabase Edge Function Sync
Fetches linear channels directly from SM IPTV v2.5 Supabase Edge Function:
  GET https://djzgejnptardaliqlgpu.supabase.co/functions/v1/get-channels
using HMAC-SHA256 request signing with secret key 'key'.

Generates:
1. Individual category M3U files in `playlists/sm_latest/` (e.g. kids.m3u, bangla.m3u)
2. Master all-in-one M3U playlist in `playlists/sm_latest/all.m3u`
3. JSON metadata catalog in `playlists/sm_latest/categories.json`
4. Syncs channels & stream servers to remote Supabase Database (if credentials provided)
"""

import os
import re
import sys
import json
import time
import hmac
import hashlib
import unicodedata
import urllib.request
import urllib.error
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

try:
    import requests
except ImportError:
    requests = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
SUPABASE_EDGE_URL = os.environ.get(
    "SM_EDGE_CHANNELS_URL",
    "https://djzgejnptardaliqlgpu.supabase.co/functions/v1/get-channels"
)
SIGNING_SECRET = os.environ.get("SM_EDGE_SIGNING_SECRET", "key").encode("utf-8")
DEFAULT_USER_AGENT = os.environ.get(
    "SM_USER_AGENT",
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_1 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.1 Mobile/15E148 Safari/604.1"
)
OUTPUT_DIR = os.environ.get("PLAYLISTS_DIR", os.path.join("playlists", "sm_latest"))

# Remote Supabase DB credentials
REMOTE_SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://hqmhuvsjlykrdusfkmeg.supabase.co").rstrip("/")
REMOTE_SUPABASE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhxbWh1dnNqbHlrcmR1c2ZrbWVnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI4MjI3OTEsImV4cCI6MjA5ODM5ODc5MX0.sfNEW7QG0idyVVRHlDtYjITDfIbsFQQm2u9a3ffoNoA"
)
ADMIN_SECRET_TOKEN = (os.environ.get("ADMIN_SECRET_TOKEN") or "GoLiveAdminSecret2026").strip()


def generate_signature(timestamp: str, secret: bytes = SIGNING_SECRET) -> str:
    """Generates HMAC-SHA256 signature for 'get-channels:<ts>'."""
    msg = f"get-channels:{timestamp}".encode("utf-8")
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


def slugify_category(name: str) -> str:
    """
    Converts category names to clean filesystem-safe slugs.
    Handles math/stylized Unicode (e.g. bold serif 𝐌𝐮𝐬𝐢𝐜 -> music).
    """
    normalized = unicodedata.normalize("NFKD", name)
    clean = re.sub(r"[^\w\s-]", "", normalized).strip().lower()
    clean = re.sub(r"[-\s]+", "_", clean)
    return clean or "other"


def refine_channel_metadata(raw_name: str) -> Tuple[str, str, str]:
    """
    Refines raw channel name into:
    1. canonical_id: lowercase slug stripped of quality tags (e.g. 't_sports')
    2. clean_name: human-readable name stripped of quality (e.g. 'T Sports')
    3. quality: detected quality string (e.g. 'FHD', 'HD', '4K', 'SD')
    """
    name = unicodedata.normalize("NFKD", raw_name).strip()

    quality = "HD"
    q_match = re.search(r'\b(4K|UHD|FHD|1080p|720p|HD|SD|HQ)\b', name, re.IGNORECASE)
    if not q_match:
        q_match = re.search(r'(?<=[a-zA-Z0-9])(FHD|UHD|4K|HD)\b', name, re.IGNORECASE)

    if q_match:
        found_q = q_match.group(1).upper()
        if found_q in ("1080P", "FHD", "UHD"):
            quality = "FHD"
        elif found_q in ("720P", "HD"):
            quality = "HD"
        elif found_q == "4K":
            quality = "4K"
        elif found_q == "SD":
            quality = "SD"

    clean = re.sub(r'\b(4K|UHD|FHD|1080p|720p|HD|SD|HQ)\b', '', name, flags=re.IGNORECASE)
    clean = re.sub(r'(?<=[a-zA-Z0-9])(FHD|UHD|4K|HD)\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^[0-9]+[\.\-\s]+', '', clean)
    clean = re.sub(r'[\.\-\|\:\_\s]+$', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if not clean:
        clean = name

    slug = clean.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '_', slug).strip('_')
    if not slug:
        slug = "channel"

    return slug, clean, quality


def resolve_channel_metadata(category: str) -> Tuple[str, str]:
    if category in ("bangla", "sports"):
        return "BD", "bn"
    elif category in ("indian_bangla",):
        return "IN", "bn"
    elif category in ("hindi",):
        return "IN", "hi"
    elif category in ("islamic",):
        return "SA", "ar"
    else:
        return "GLOBAL", "en"


def fetch_channels_data(url: str = SUPABASE_EDGE_URL, timeout: int = 15, retries: int = 3) -> Dict[str, Any]:
    """Fetches channels payload with dynamic timestamp and HMAC signature."""
    last_err = None
    for attempt in range(retries):
        ts = str(int(time.time()))
        sig = generate_signature(ts)
        headers = {
            "User-Agent": DEFAULT_USER_AGENT,
            "x-ts": ts,
            "x-sign": sig,
            "Accept": "application/json"
        }
        req = urllib.request.Request(url, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                if resp.status != 200:
                    raise RuntimeError(f"Unexpected status code {resp.status}")
                raw_bytes = resp.read()
                return json.loads(raw_bytes.decode("utf-8"))
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, Exception) as e:
            last_err = e
            time.sleep(2 * (attempt + 1))

    raise RuntimeError(f"Failed to fetch channels from {url} after {retries} attempts: {last_err}")


def format_channel_m3u(ch: Dict[str, Any], group_title: str) -> List[str]:
    """Formats a single channel item into standard M3U Plus directives."""
    lines = []
    ch_id = ch.get("id", "")
    name = (ch.get("name") or "Unknown Channel").strip()
    logo = (ch.get("logo") or "").strip()
    stream_url = (ch.get("stream_url") or "").strip()
    if not stream_url:
        return []

    referer = ch.get("referer")
    origin = ch.get("origin")
    user_agent = ch.get("user_agent")
    cookie = ch.get("cookie")
    kid = ch.get("kid")
    key = ch.get("key")

    if origin and not referer:
        referer = origin if origin.endswith("/") else f"{origin}/"

    extinf = f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group_title}"'
    if user_agent:
        extinf += f' http-user-agent="{user_agent}"'
    if referer:
        extinf += f' http-referrer="{referer}"'
    if origin:
        extinf += f' http-origin="{origin}"'
    extinf += f',{name}'

    lines.append(extinf)
    if user_agent:
        lines.append(f'#EXTVLCOPT:http-user-agent={user_agent}')
    if referer:
        lines.append(f'#EXTVLCOPT:http-referrer={referer}')
    if origin:
        lines.append(f'#EXTVLCOPT:http-origin={origin}')
    if cookie:
        lines.append(f'#EXTVLCOPT:http-cookie={cookie}')
    if kid and key:
        lines.append('#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey')
        lines.append(f'#KODIPROP:inputstream.adaptive.license_key={kid}:{key}')

    lines.append(stream_url)
    return lines


def build_playlists(data: Dict[str, Any], output_dir: str = OUTPUT_DIR) -> Dict[str, Any]:
    """Generates category M3U files, master all.m3u, and metadata catalog."""
    os.makedirs(output_dir, exist_ok=True)
    categories = data.get("categories", [])
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    catalog = {
        "updated_at": now_utc,
        "app_name": data.get("app_name", "SM IPTV"),
        "developed_by": data.get("developed_by", "Monirul Islam"),
        "telegram_channel": data.get("telegram_channel", ""),
        "total_categories": len(categories),
        "total_channels": 0,
        "categories": []
    }

    all_master_lines = [
        '#EXTM3U name="SM IPTV Latest - All Channels"',
        f'# Generated by SM IPTV Supabase Edge Sync at {now_utc}',
        ''
    ]

    total_valid_channels = 0
    active_filenames = set()

    for cat in categories:
        raw_name = cat.get("name", "Other").strip()
        slug = slugify_category(raw_name)
        filename = f"{slug}.m3u"
        active_filenames.add(filename)

        cat_lines = [
            f'#EXTM3U name="SM IPTV Latest - {raw_name}"',
            f'# Category: {raw_name}',
            f'# Updated: {now_utc}',
            ''
        ]

        valid_in_cat = 0
        for ch in cat.get("channels", []):
            formatted = format_channel_m3u(ch, raw_name)
            if formatted:
                cat_lines.extend(formatted)
                all_master_lines.extend(formatted)
                valid_in_cat += 1

        cat_path = os.path.join(output_dir, filename)
        with open(cat_path, "w", encoding="utf-8") as f:
            f.write("\n".join(cat_lines) + "\n")

        catalog["categories"].append({
            "name": raw_name,
            "slug": slug,
            "filename": filename,
            "channel_count": valid_in_cat
        })
        total_valid_channels += valid_in_cat
        print(f"   [Category] {raw_name} -> {filename} ({valid_in_cat} channels)")

    # Master playlist
    all_filename = "all.m3u"
    active_filenames.add(all_filename)
    all_path = os.path.join(output_dir, all_filename)
    with open(all_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_master_lines) + "\n")
    print(f"   [Master] All Channels -> {all_filename} ({total_valid_channels} total channels)")

    catalog["total_channels"] = total_valid_channels

    # Metadata catalog
    catalog_path = os.path.join(output_dir, "categories.json")
    with open(catalog_path, "w", encoding="utf-8") as f:
        json.dump(catalog, f, indent=2, ensure_ascii=False)

    return catalog


# ---------------------------------------------------------------------------
# Supabase PostgREST Client for Remote DB Sync
# ---------------------------------------------------------------------------
class SupabaseDbClient:
    def __init__(self, base_url: str, key: str, admin_token: str = ""):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}"
        }
        if admin_token:
            self.headers["x-admin-token"] = admin_token

    def get_all(self, table: str, select: str = "*", filters: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        """Paginates through all rows of a table using Range header."""
        results = []
        page_size = 1000
        offset = 0

        while True:
            headers = dict(self.headers)
            headers["Range"] = f"{offset}-{offset + page_size - 1}"
            url = f"{self.base_url}/rest/v1/{table}?select={select}"
            if filters:
                for k, v in filters.items():
                    url += f"&{k}={v}"

            resp = requests.get(url, headers=headers, timeout=20)
            if not resp.ok:
                print(f"[Supabase Query Error on {table}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                resp.raise_for_status()

            data = resp.json()
            if not data:
                break
            results.extend(data)
            if len(data) < page_size:
                break
            offset += page_size

        return results

    def upsert_rows(self, table: str, rows: List[Dict[str, Any]], on_conflict: str = "id") -> int:
        """Upserts rows in batches."""
        if not rows:
            return 0
        batch_size = 100
        total = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            url = f"{self.base_url}/rest/v1/{table}?on_conflict={on_conflict}"
            headers = dict(self.headers)
            headers["Prefer"] = "resolution=merge-duplicates,return=minimal"
            resp = requests.post(url, headers=headers, json=batch, timeout=25)
            if not resp.ok:
                print(f"[Supabase Upsert Error on {table}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                resp.raise_for_status()
            total += len(batch)
        return total

    def insert_rows(self, table: str, rows: List[Dict[str, Any]]) -> int:
        """Inserts rows in batches."""
        if not rows:
            return 0
        batch_size = 100
        total = 0
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            url = f"{self.base_url}/rest/v1/{table}"
            headers = dict(self.headers)
            headers["Prefer"] = "return=minimal"
            resp = requests.post(url, headers=headers, json=batch, timeout=25)
            if not resp.ok:
                print(f"[Supabase Insert Error on {table}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                resp.raise_for_status()
            total += len(batch)
        return total


def sync_to_supabase_db(data: Dict[str, Any], dry_run: bool = False):
    """
    Syncs channels and stream servers into the remote Supabase database.
    Ensures categories exist, upserts channels, and registers stream servers.
    """
    if not requests:
        print("requests module not installed, skipping remote Supabase DB sync.", file=sys.stderr)
        return

    if not REMOTE_SUPABASE_URL or not REMOTE_SUPABASE_KEY:
        print("Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY, skipping remote DB sync.")
        return

    print("\n" + "=" * 70)
    print("Syncing latest channels & stream servers to Supabase DB...")
    print(f"Target DB: {REMOTE_SUPABASE_URL} (dry_run: {dry_run})")
    print("=" * 70)

    db = SupabaseDbClient(REMOTE_SUPABASE_URL, REMOTE_SUPABASE_KEY, ADMIN_SECRET_TOKEN)
    categories = data.get("categories", [])

    # 1. Ensure categories exist in DB
    try:
        existing_cats = {c["id"]: c for c in db.get_all("categories", select="id,name")}
    except Exception as e:
        print(f"   Warning: Could not fetch existing categories: {e}")
        existing_cats = {}

    cats_to_register = []
    category_slugs = set()
    for cat in categories:
        raw_name = cat.get("name", "Other").strip()
        slug = slugify_category(raw_name)
        category_slugs.add(slug)
        if slug not in existing_cats:
            cats_to_register.append({
                "id": slug,
                "name": raw_name,
                "sort_order": 90,
                "active": True,
                "type": "custom"
            })
            existing_cats[slug] = {"id": slug, "name": raw_name}

    if cats_to_register:
        print(f"   Registering {len(cats_to_register)} new categories in Supabase: {[c['id'] for c in cats_to_register]}")
        if not dry_run:
            db.upsert_rows("categories", cats_to_register, on_conflict="id")

    # 2. Fetch existing channels & servers to index
    try:
        cat_filter = f"({','.join(category_slugs)})"
        existing_channels_rows = db.get_all("channels", select="id,name,stream_url,category", filters={"category": f"in.{cat_filter}"})
        existing_channels = {c["id"]: c for c in existing_channels_rows}
    except Exception as e:
        print(f"   Warning: Could not fetch channels: {e}")
        existing_channels = {}

    try:
        existing_servers_rows = db.get_all("stream_servers", select="id,channel_id,stream_url,name,sort_order")
        existing_servers: Dict[str, List[Dict[str, Any]]] = {}
        for s in existing_servers_rows:
            cid = s.get("channel_id")
            if cid:
                existing_servers.setdefault(cid, []).append(s)
    except Exception as e:
        print(f"   Warning: Could not fetch stream_servers: {e}")
        existing_servers = {}

    # Track known stream URLs per channel
    known_stream_urls: Dict[str, set] = {}
    for cid, s_list in existing_servers.items():
        known_stream_urls[cid] = {s.get("stream_url") for s in s_list if s.get("stream_url")}
    for cid, ch in existing_channels.items():
        if ch.get("stream_url"):
            known_stream_urls.setdefault(cid, set()).add(ch["stream_url"])

    channels_to_upsert: Dict[str, Dict[str, Any]] = {}
    servers_to_insert: List[Dict[str, Any]] = []

    for cat in categories:
        raw_name = cat.get("name", "Other").strip()
        cat_slug = slugify_category(raw_name)

        for ch in cat.get("channels", []):
            raw_ch_name = (ch.get("name") or "").strip()
            stream_url = (ch.get("stream_url") or "").strip()
            if not stream_url:
                continue

            canonical_id, clean_name, quality = refine_channel_metadata(raw_ch_name)
            country, language = resolve_channel_metadata(cat_slug)

            # Build headers
            headers = {}
            if ch.get("user_agent"):
                headers["User-Agent"] = ch["user_agent"]
            if ch.get("referer"):
                headers["Referer"] = ch["referer"]
            if ch.get("cookie"):
                headers["Cookie"] = ch["cookie"]
            if ch.get("origin"):
                headers["Origin"] = ch["origin"]

            # DRM
            drm = None
            if ch.get("kid") and ch.get("key"):
                drm = {
                    "type": "clearkey",
                    "kid": ch["kid"],
                    "key": ch["key"]
                }

            logo = ch.get("logo") or ""

            if canonical_id not in channels_to_upsert:
                channels_to_upsert[canonical_id] = {
                    "id": canonical_id,
                    "name": clean_name,
                    "logo": logo,
                    "category": cat_slug,
                    "country": country,
                    "language": language,
                    "is_live": True,
                    "is_trending": False,
                    "quality": quality,
                    "stream_url": stream_url,
                    "headers": headers,
                    "drm": drm,
                    "proxy": False,
                    "sort_order": len(channels_to_upsert) + 1
                }
            elif headers:
                channels_to_upsert[canonical_id]["headers"].update(headers)

            # Reconcile server
            urls_for_ch = known_stream_urls.setdefault(canonical_id, set())
            if stream_url not in urls_for_ch:
                server_num = len(existing_servers.get(canonical_id, [])) + sum(1 for s in servers_to_insert if s["channel_id"] == canonical_id) + 1
                servers_to_insert.append({
                    "channel_id": canonical_id,
                    "name": f"Server {server_num} ({quality})",
                    "stream_url": stream_url,
                    "headers": headers,
                    "drm": drm,
                    "scheme": 2 if drm else 0,
                    "has_header": bool(headers),
                    "sort_order": server_num,
                    "active": True,
                    "health_status": "unknown",
                    "consecutive_failures": 0
                })
                urls_for_ch.add(stream_url)

    print(f"3. Upserting {len(channels_to_upsert)} channels into 'channels' table...")
    if not dry_run and channels_to_upsert:
        db.upsert_rows("channels", list(channels_to_upsert.values()), on_conflict="id")
        print("   Channels successfully upserted.")

    if servers_to_insert:
        print(f"4. Inserting {len(servers_to_insert)} new stream servers into 'stream_servers' table...")
        if not dry_run:
            db.insert_rows("stream_servers", servers_to_insert)
            print("   Stream servers successfully inserted.")
    else:
        print("4. All stream servers already up to date in DB.")

    print("Supabase DB sync completed successfully!")


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting SM IPTV Latest Edge Sync...")
    print(f"1. Fetching linear channels from Supabase Edge Function...")
    print(f"   Endpoint: {SUPABASE_EDGE_URL}")
    data = fetch_channels_data()
    cats = data.get("categories", [])
    print(f"   Retrieved {len(cats)} categories from upstream.")

    print(f"\n2. Generating playlists in '{OUTPUT_DIR}'...")
    catalog = build_playlists(data, OUTPUT_DIR)
    print(f"Done local M3U build! Synced {catalog['total_channels']} channels across {catalog['total_categories']} categories.")

    # Check if DB sync is enabled
    enable_db_sync = os.environ.get("ENABLE_DB_SYNC", "true").lower() in ("true", "1", "yes")
    if enable_db_sync and REMOTE_SUPABASE_URL and REMOTE_SUPABASE_KEY:
        dry_run = os.environ.get("DRY_RUN", "false").lower() in ("true", "1", "yes")
        sync_to_supabase_db(data, dry_run=dry_run)


if __name__ == "__main__":
    main()
