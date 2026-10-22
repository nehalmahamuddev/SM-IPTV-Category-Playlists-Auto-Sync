#!/usr/bin/env python3
"""
SM IPTV -> Supabase Sync Pipeline
Refines raw channels from SM IPTV into canonical channel IDs,
normalizes stream qualities, upserts channels, and attaches multiple stream URLs
under the `stream_servers` table for each channel.
"""

import os
import re
import sys
import json
import time
import argparse
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

try:
    import requests
except ImportError:
    print("Error: 'requests' is required. Run 'pip install requests'.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration & Credentials
# ---------------------------------------------------------------------------
BOOTSTRAP_URL = "https://app-main-ap.sm-monirul.xyz/exp/"
DEFAULT_USER_AGENT = "okhttp/4.12.0"

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://hqmhuvsjlykrdusfkmeg.supabase.co").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhxbWh1dnNqbHlrcmR1c2ZrbWVnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI4MjI3OTEsImV4cCI6MjA5ODM5ODc5MX0.sfNEW7QG0idyVVRHlDtYjITDfIbsFQQm2u9a3ffoNoA"
)
ADMIN_SECRET_TOKEN = (os.environ.get("ADMIN_SECRET_TOKEN") or "GoLiveAdminSecret2026").strip()


# ---------------------------------------------------------------------------
# Channel & Server Refinement Helpers
# ---------------------------------------------------------------------------
def refine_channel_metadata(raw_name: str) -> Tuple[str, str, str]:
    """
    Refines raw channel name into:
    1. canonical_id: lowercase slug stripped of quality tags (e.g. 't_sports')
    2. clean_name: human-readable name stripped of quality (e.g. 'T Sports')
    3. quality: detected quality string (e.g. 'FHD', 'HD', '4K', 'SD')
    """
    # 1. Normalize unicode (compatibility decomposition)
    name = unicodedata.normalize("NFKD", raw_name).strip()

    # 2. Detect quality tag
    quality = "HD"
    q_match = re.search(r'\b(4K|UHD|FHD|1080p|720p|HD|SD|HQ)\b', name, re.IGNORECASE)
    if not q_match:
        # Check attached suffix e.g. "SPORTSFHD"
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

    # 3. Clean channel name (strip quality words, server numbers, trailing punctuation)
    clean = re.sub(r'\b(4K|UHD|FHD|1080p|720p|HD|SD|HQ)\b', '', name, flags=re.IGNORECASE)
    clean = re.sub(r'(?<=[a-zA-Z0-9])(FHD|UHD|4K|HD)\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^[0-9]+[\.\-\s]+', '', clean) # leading numbers like "1. "
    clean = re.sub(r'[\.\-\|\:\_\s]+$', '', clean) # trailing symbols e.g. " - " or "."
    clean = re.sub(r'\s+', ' ', clean).strip()
    if not clean:
        clean = name

    # 4. Generate canonical slug ID
    slug = clean.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '_', slug).strip('_')
    if not slug:
        slug = "channel"

    return slug, clean, quality


def slugify_category(name: str) -> str:
    normalized = unicodedata.normalize("NFKD", name)
    clean = re.sub(r"[^\w\s-]", "", normalized).strip().lower()
    clean = re.sub(r"[-\s]+", "_", clean)
    return clean or "other"


# ---------------------------------------------------------------------------
# SM IPTV Client
# ---------------------------------------------------------------------------
class SmIptvClient:
    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": DEFAULT_USER_AGENT})
        self.worker_url: Optional[str] = None
        self.token: Optional[str] = None
        self.token_expires_at: float = 0.0

    def get_worker_url(self, force_refresh: bool = False) -> str:
        if self.worker_url and not force_refresh:
            return self.worker_url
        resp = self.session.get(BOOTSTRAP_URL, timeout=12)
        resp.raise_for_status()
        url = resp.json().get("url", "").strip()
        if not url.startswith("https://"):
            raise ValueError(f"Invalid worker URL received: {url}")
        if not url.endswith("/"):
            url += "/"
        self.worker_url = url
        return self.worker_url

    def get_token(self, force_refresh: bool = False) -> str:
        now = time.time()
        if self.token and not force_refresh and now < (self.token_expires_at - 60):
            return self.token
        worker = self.get_worker_url(force_refresh=force_refresh)
        resp = self.session.post(f"{worker}token", timeout=12)
        resp.raise_for_status()
        data = resp.json()
        self.token = data["token"]
        self.token_expires_at = now + data.get("expires_in", 1800)
        return self.token

    def _auth_request(self, method: str, endpoint: str, retry: bool = True) -> requests.Response:
        worker = self.get_worker_url()
        token = self.get_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": DEFAULT_USER_AGENT
        }
        url = f"{worker}{endpoint.lstrip('/')}"
        resp = self.session.request(method, url, headers=headers, timeout=15)
        if resp.status_code == 401 and retry:
            self.get_token(force_refresh=True)
            return self._auth_request(method, endpoint, retry=False)
        resp.raise_for_status()
        return resp

    def get_channels(self) -> Dict[str, Any]:
        return self._auth_request("GET", "channels").json()

    def get_sports(self) -> Dict[str, Any]:
        return self._auth_request("GET", "sports").json()


# ---------------------------------------------------------------------------
# Supabase PostgREST Client
# ---------------------------------------------------------------------------
class SupabaseDbClient:
    def __init__(self, base_url: str, key: str, admin_token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Content-Type": "application/json",
            "apikey": key,
            "Authorization": f"Bearer {key}",
            "Prefer": "return=representation"
        }
        if admin_token:
            self.headers["x-admin-token"] = admin_token

    def get_all(self, table: str, select: str = "*", params: Optional[Dict] = None) -> List[Dict]:
        url = f"{self.base_url}/rest/v1/{table}?select={select}"
        headers = dict(self.headers)
        headers["Range"] = "0-9999"
        resp = requests.get(url, headers=headers, params=params, timeout=15)
        resp.raise_for_status()
        return resp.json()

    def upsert_rows(self, table: str, rows: List[Dict], on_conflict: Optional[str] = None) -> int:
        if not rows:
            return 0
        url = f"{self.base_url}/rest/v1/{table}"
        if on_conflict:
            url += f"?on_conflict={on_conflict}"
        headers = dict(self.headers)
        headers["Prefer"] = "resolution=merge-duplicates"

        total = 0
        batch_size = 100
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            resp = requests.post(url, headers=headers, json=batch, timeout=20)
            if not resp.ok:
                print(f"[Supabase Error on {table}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                resp.raise_for_status()
            total += len(batch)
        return total

    def insert_rows(self, table: str, rows: List[Dict]) -> int:
        if not rows:
            return 0
        url = f"{self.base_url}/rest/v1/{table}"
        headers = dict(self.headers)
        headers["Prefer"] = "return=minimal"

        total = 0
        batch_size = 100
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            resp = requests.post(url, headers=headers, json=batch, timeout=20)
            if not resp.ok:
                print(f"[Supabase Error on {table}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                resp.raise_for_status()
            total += len(batch)
        return total


# ---------------------------------------------------------------------------
# Main Sync Logic
# ---------------------------------------------------------------------------
def sync_pipeline(dry_run: bool = False):
    print("==================================================================")
    print("SM IPTV -> Supabase Channels & Multi-Stream Servers Sync")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Dry-Run: {dry_run}")
    print("==================================================================")

    # 1. Connect to SM IPTV API
    print("1. Connecting to SM IPTV backend API...")
    sm_client = SmIptvClient()
    worker = sm_client.get_worker_url()
    token = sm_client.get_token()
    print(f"   Active Gateway: {worker}")
    print(f"   Session Token: {token[:20]}... (expires in 30m)")

    # 2. Fetch Channels & Sports
    print("2. Fetching channels catalog and live sports feeds...")
    channel_catalog = sm_client.get_channels()
    categories = channel_catalog.get("categories", [])
    print(f"   Fetched {len(categories)} categories.")

    sports_catalog = sm_client.get_sports()
    matches = sports_catalog.get("matches", [])
    print(f"   Fetched {len(matches)} live sports matches.")

    # 3. Setup Supabase Client
    auth_key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    if not auth_key:
        raise ValueError("Missing SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY")

    db = SupabaseDbClient(SUPABASE_URL, auth_key, ADMIN_SECRET_TOKEN)

    # 4. Fetch existing channels and stream_servers to build index
    print("3. Querying existing channels and stream_servers from Supabase...")
    try:
        existing_channels_rows = db.get_all("channels", select="id,name,stream_url,category")
        existing_channels = {c["id"]: c for c in existing_channels_rows}
        print(f"   Existing channels in DB: {len(existing_channels)}")
    except Exception as e:
        print(f"   Warning: Could not fetch channels: {e}")
        existing_channels = {}

    try:
        existing_servers_rows = db.get_all("stream_servers", select="id,channel_id,stream_url,name,sort_order")
        # Map: channel_id -> list of existing servers
        existing_servers: Dict[str, List[Dict]] = {}
        for s in existing_servers_rows:
            cid = s.get("channel_id")
            if cid:
                existing_servers.setdefault(cid, []).append(s)
        print(f"   Existing stream_servers in DB: {len(existing_servers_rows)}")
    except Exception as e:
        print(f"   Warning: Could not fetch stream_servers: {e}")
        existing_servers = {}

    # 5. Process raw channels into canonical structures
    channels_to_upsert: Dict[str, Dict] = {} # Keyed by canonical_id
    servers_to_insert: List[Dict] = []
    
    # Track stream URLs already registered per channel (to avoid duplicates)
    channel_stream_urls: Dict[str, set] = {}
    for cid, s_list in existing_servers.items():
        channel_stream_urls[cid] = {s.get("stream_url") for s in s_list if s.get("stream_url")}
    for cid, ch in existing_channels.items():
        if ch.get("stream_url"):
            channel_stream_urls.setdefault(cid, set()).add(ch["stream_url"])

    print("\n4. Refining channels and preparing multi-stream server mapping...")

    # Process Linear Channels
    for cat in categories:
        cat_name = cat.get("name", "Other")
        cat_slug = slugify_category(cat_name)

        for ch in cat.get("channels", []):
            raw_name = ch.get("name", "")
            stream_url = (ch.get("stream_url") or "").strip()
            if not stream_url:
                continue

            canonical_id, clean_name, quality = refine_channel_metadata(raw_name)

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

            # Build DRM
            drm = None
            if ch.get("kid") and ch.get("key"):
                drm = {
                    "type": "clearkey",
                    "kid": ch["kid"],
                    "key": ch["key"]
                }

            logo = ch.get("logo") or ""

            # Always record channel metadata (and fresh headers) in channels_to_upsert
            if canonical_id not in channels_to_upsert:
                channels_to_upsert[canonical_id] = {
                    "id": canonical_id,
                    "name": clean_name,
                    "logo": logo,
                    "category": cat_slug,
                    "country": "BD" if cat_slug in ("bangla", "sports") else "",
                    "language": "bn" if cat_slug in ("bangla", "indian_bangla") else ("hi" if cat_slug == "hindi" else "en"),
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

            if canonical_id not in existing_channels and canonical_id not in channel_stream_urls:
                # Also add as Server 1 in stream_servers if brand new channel
                server_name = f"Server 1 ({quality})"
                servers_to_insert.append({
                    "channel_id": canonical_id,
                    "name": server_name,
                    "stream_url": stream_url,
                    "headers": headers,
                    "drm": drm,
                    "scheme": 2 if drm else 0,
                    "has_header": bool(headers),
                    "sort_order": 1,
                    "active": True
                })
                channel_stream_urls.setdefault(canonical_id, set()).add(stream_url)
            else:
                # Channel already exists: Check if this stream_url is already present
                known_urls = channel_stream_urls.get(canonical_id, set())
                if stream_url not in known_urls:
                    # Calculate next server number
                    existing_count = len(existing_servers.get(canonical_id, []))
                    # Pending servers for this channel
                    pending_count = sum(1 for s in servers_to_insert if s["channel_id"] == canonical_id)
                    server_num = existing_count + pending_count + 1
                    server_name = f"Server {server_num} ({quality})"

                    servers_to_insert.append({
                        "channel_id": canonical_id,
                        "name": server_name,
                        "stream_url": stream_url,
                        "headers": headers,
                        "drm": drm,
                        "scheme": 2 if drm else 0,
                        "has_header": bool(headers),
                        "sort_order": server_num,
                        "active": True
                    })
                    known_urls.add(stream_url)

    print(f"   Channels to insert/update: {len(channels_to_upsert)}")
    print(f"   Stream servers to attach: {len(servers_to_insert)}")

    # 6. Apply to Database or Dry Run
    if dry_run:
        print("\n[DRY RUN] Previewing first 5 channels:")
        for cid, ch in list(channels_to_upsert.items())[:5]:
            print(f"   Channel: ID='{cid}', Name='{ch['name']}', Category='{ch['category']}', Quality='{ch['quality']}'")
        print("\n[DRY RUN] Previewing first 5 stream servers:")
        for s in servers_to_insert[:5]:
            print(f"   Server: ChannelID='{s['channel_id']}', Name='{s['name']}', URL='{s['stream_url'][:50]}...'")
        print("\n[DRY RUN] Completed without modifying Supabase.")
        return

    # 7. Execute Real Upsert
    print("\n5. Applying updates to Supabase...")
    if channels_to_upsert:
        rows = list(channels_to_upsert.values())
        print(f"   Upserting {len(rows)} channels into 'public.channels'...")
        cnt = db.upsert_rows("channels", rows, on_conflict="id")
        print(f"   Successfully upserted {cnt} channels.")

    if servers_to_insert:
        print(f"   Inserting {len(servers_to_insert)} stream servers into 'public.stream_servers'...")
        cnt = db.insert_rows("stream_servers", servers_to_insert)
        print(f"   Successfully inserted {cnt} stream servers.")

    print("\nSync completed successfully!")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync SM IPTV channels and stream servers to Supabase")
    parser.add_argument("--dry-run", action="store_true", help="Preview channels and servers without updating Supabase")
    args = parser.parse_args()

    sync_pipeline(dry_run=args.dry_run)
