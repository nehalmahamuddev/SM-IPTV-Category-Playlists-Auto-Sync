#!/usr/bin/env python3
"""
Toffee Auto-Sync Pipeline
Fetches latest Toffee channels & expiring stream tokens from Toffee-Auto-Update,
generates local playlists/toffee.m3u and output/toffee.json, and synchronizes
the 'toffee' category in Supabase ('public.channels' & 'public.stream_servers').
"""

import os
import re
import sys
import json
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
# Default Configuration
# ---------------------------------------------------------------------------
DEFAULT_TOFFEE_SOURCE_URL = (
    "https://raw.githubusercontent.com/sm-monirulislam/Toffee-Auto-Update/refs/heads/main/toffee_data.json"
)
DEFAULT_PLAYLISTS_DIR = os.environ.get("PLAYLISTS_DIR", "playlists")
DEFAULT_OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://hqmhuvsjlykrdusfkmeg.supabase.co").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhxbWh1dnNqbHlrcmR1c2ZrbWVnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI4MjI3OTEsImV4cCI6MjA5ODM5ODc5MX0.sfNEW7QG0idyVVRHlDtYjITDfIbsFQQm2u9a3ffoNoA"
)
ADMIN_SECRET_TOKEN = (os.environ.get("ADMIN_SECRET_TOKEN") or "GoLiveAdminSecret2026").strip()


# ---------------------------------------------------------------------------
# Channel Normalization & Parsing Helpers
# ---------------------------------------------------------------------------
def slugify_channel_name(name: str) -> str:
    """
    Generates a safe canonical channel ID prefixed with 'toffee_'
    e.g. 'Toffee TV' -> 'toffee_toffee_tv', 'Somoy TV' -> 'toffee_somoy_tv'.
    """
    clean = unicodedata.normalize("NFKD", name or "").strip().lower()
    clean = re.sub(r'[\(\)\[\]\{\}\.\-\+&/\\:]', ' ', clean)
    clean = re.sub(r'[^a-z0-9\s_]', '', clean)
    slug = re.sub(r'[\s_]+', '_', clean).strip('_')
    if not slug:
        slug = "channel"
    return f"toffee_{slug}"


def normalize_toffee_channel(raw_ch: Dict[str, Any], sort_order: int = 1) -> Dict[str, Any]:
    """
    Normalizes a single channel entry from toffee_data.json into standard format.
    """
    name = (raw_ch.get("name") or "Toffee Channel").strip()
    slug_id = slugify_channel_name(name)
    link = (raw_ch.get("link") or "").strip()
    headers = raw_ch.get("headers") or {}
    logo = (raw_ch.get("logo") or "").strip()

    # Detect quality if present in name, default HD
    quality = "HD"
    q_match = re.search(r'\b(4K|UHD|FHD|1080p|720p|HD|SD)\b', name, re.IGNORECASE)
    if q_match:
        found = q_match.group(1).upper()
        if found in ("FHD", "1080P", "UHD"):
            quality = "FHD"
        elif found in ("HD", "720P"):
            quality = "HD"
        elif found == "4K":
            quality = "4K"
        elif found == "SD":
            quality = "SD"

    servers = [
        {
            "name": "Server 1 (Toffee Live)",
            "stream_url": link,
            "quality": quality,
            "headers": headers,
            "drm": None,
            "scheme": 0,
            "has_header": bool(headers),
            "has_vpn_detection": False,
            "sort_order": 1,
            "active": True
        }
    ]

    return {
        "id": slug_id,
        "name": name,
        "logo": logo,
        "category": "toffee",
        "country": "BD",
        "language": "bn",
        "is_live": True,
        "is_trending": False,
        "quality": quality,
        "stream_url": link,
        "headers": headers,
        "drm": None,
        "proxy": False,
        "sort_order": sort_order,
        "servers": servers
    }


def deduplicate_channels(channels: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Ensures every channel in the list has a strictly unique id.
    If collisions exist, appends _2, _3, etc.
    """
    seen: Dict[str, int] = {}
    deduped = []
    for ch in channels:
        base_id = ch["id"]
        if base_id not in seen:
            seen[base_id] = 1
            deduped.append(ch)
        else:
            seen[base_id] += 1
            new_id = f"{base_id}_{seen[base_id]}"
            ch_copy = dict(ch)
            ch_copy["id"] = new_id
            for s in ch_copy.get("servers", []):
                s["channel_id"] = new_id
            deduped.append(ch_copy)
    return deduped


def format_m3u_entry(channel: Dict[str, Any]) -> str:
    """
    Formats a single channel into M3U extended format with player tags.
    """
    name = channel.get("name", "")
    ch_id = channel.get("id", "")
    logo = channel.get("logo", "")
    stream_url = channel.get("stream_url", "")
    headers = channel.get("headers") or {}

    lines = [
        f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="Toffee",{name}'
    ]

    # Add VLC and Kodi header instructions if available
    ua = headers.get("user-agent") or headers.get("User-Agent")
    if ua:
        lines.append(f'#EXTVLCOPT:http-user-agent={ua}')

    if headers:
        lines.append(f'#EXTHTTP:{json.dumps(headers, separators=(",", ":"))}')

    lines.append(stream_url)
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# File Generators (M3U & JSON)
# ---------------------------------------------------------------------------
def generate_m3u_playlist(channels: List[Dict[str, Any]], output_path: str):
    """Writes the channels list to an M3U playlist file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    utc_now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    content = [
        '#EXTM3U name="Toffee Live TV"',
        '# Category: Toffee',
        f'# Updated: {utc_now}',
        f'# Total Channels: {len(channels)}',
        ''
    ]

    for ch in channels:
        if ch.get("stream_url"):
            content.append(format_m3u_entry(ch))

    with open(output_path, "w", encoding="utf-8") as f:
        f.write("\n".join(content) + "\n")
    print(f"   [File Saved] M3U Playlist: {output_path} ({len(channels)} channels)")


def generate_json_catalog(channels: List[Dict[str, Any]], output_path: str):
    """Writes the channels list to a structured JSON catalog file."""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    data = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_channels": len(channels),
        "category": "toffee",
        "channels": channels
    }
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"   [File Saved] JSON Catalog: {output_path} ({len(channels)} channels)")


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

    def get_all(self, table: str, select: str = "*", filters: Optional[Dict[str, str]] = None) -> List[Dict[str, Any]]:
        url = f"{self.base_url}/rest/v1/{table}?select={select}"
        headers = dict(self.headers)
        headers["Range-Unit"] = "items"

        rows = []
        offset = 0
        limit = 1000
        while True:
            headers["Range"] = f"{offset}-{offset + limit - 1}"
            resp = requests.get(url, headers=headers, params=filters, timeout=20)
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            rows.extend(batch)
            if len(batch) < limit:
                break
            offset += limit
        return rows

    def upsert_rows(self, table: str, rows: List[Dict[str, Any]], on_conflict: Optional[str] = None) -> int:
        if not rows:
            return 0

        # In-memory deduplication by on_conflict key to prevent batch collisions
        if on_conflict:
            deduped = {}
            for r in rows:
                k = r.get(on_conflict)
                if k is not None:
                    deduped[k] = r
                else:
                    deduped[id(r)] = r
            rows = list(deduped.values())

        url = f"{self.base_url}/rest/v1/{table}"
        if on_conflict:
            url += f"?on_conflict={on_conflict}"
        headers = dict(self.headers)
        headers["Prefer"] = "resolution=merge-duplicates"

        total = 0
        batch_size = 100
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            try:
                resp = requests.post(url, headers=headers, json=batch, timeout=25)
                if not resp.ok:
                    raise requests.HTTPError(f"Status {resp.status_code}: {resp.text}", response=resp)
                total += len(batch)
            except Exception as e:
                print(f"[Supabase Upsert Warning on {table}] Batch upsert failed: {e}. Retrying row-by-row fallback...", file=sys.stderr)
                for item in batch:
                    try:
                        r_resp = requests.post(url, headers=headers, json=[item], timeout=15)
                        if r_resp.ok:
                            total += 1
                        else:
                            print(f"   [Row Upsert Failed] {table} ID={item.get('id', 'unknown')}: {r_resp.status_code} {r_resp.text}", file=sys.stderr)
                    except Exception as row_err:
                        print(f"   [Row Upsert Error] {table} ID={item.get('id', 'unknown')}: {row_err}", file=sys.stderr)
        return total

    def insert_rows(self, table: str, rows: List[Dict[str, Any]]) -> int:
        if not rows:
            return 0
        url = f"{self.base_url}/rest/v1/{table}"
        headers = dict(self.headers)
        headers["Prefer"] = "return=minimal"

        total = 0
        batch_size = 100
        for i in range(0, len(rows), batch_size):
            batch = rows[i:i + batch_size]
            resp = requests.post(url, headers=headers, json=batch, timeout=25)
            if not resp.ok:
                print(f"[Supabase Insert Error on {table}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                resp.raise_for_status()
            total += len(batch)
        return total

    def update_row(self, table: str, row_id: str, patch_data: Dict[str, Any]) -> bool:
        url = f"{self.base_url}/rest/v1/{table}?id=eq.{row_id}"
        headers = dict(self.headers)
        headers["Prefer"] = "return=minimal"
        resp = requests.patch(url, headers=headers, json=patch_data, timeout=15)
        if not resp.ok:
            print(f"[Supabase Update Error on {table} {row_id}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
            resp.raise_for_status()
        return True


# ---------------------------------------------------------------------------
# Core Synchronization Logic
# ---------------------------------------------------------------------------
def sync_toffee_pipeline(
    source_url: str = DEFAULT_TOFFEE_SOURCE_URL,
    playlists_dir: str = DEFAULT_PLAYLISTS_DIR,
    output_dir: str = DEFAULT_OUTPUT_DIR,
    dry_run: bool = False,
    skip_db: bool = False,
    skip_files: bool = False
):
    print("=" * 72)
    print("Toffee TV Auto-Sync Pipeline")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Dry-Run: {dry_run}")
    print("=" * 72)

    # 1. Fetch source data
    print(f"\n1. Fetching Toffee data from: {source_url}...")
    resp = requests.get(source_url, timeout=20)
    resp.raise_for_status()
    raw_data = resp.json()

    raw_channels = raw_data.get("response", [])
    if not isinstance(raw_channels, list) or len(raw_channels) == 0:
        raise ValueError("Invalid source payload: 'response' is empty or not a list.")

    print(f"   Received {len(raw_channels)} channels from Toffee source.")

    # 2. Normalize and Deduplicate
    normalized = []
    for idx, raw_ch in enumerate(raw_channels, start=1):
        # Skip channels without stream link
        if not (raw_ch.get("link") or "").strip():
            continue
        normalized.append(normalize_toffee_channel(raw_ch, sort_order=idx))

    channels = deduplicate_channels(normalized)
    print(f"   Normalized {len(channels)} valid stream channels.")

    # 3. Generate Local Files (M3U & JSON)
    if not skip_files:
        print("\n2. Writing local artifacts...")
        m3u_path = os.path.join(playlists_dir, "toffee.m3u")
        json_path = os.path.join(output_dir, "toffee.json")

        if not dry_run:
            generate_m3u_playlist(channels, m3u_path)
            generate_json_catalog(channels, json_path)
        else:
            print(f"   [Dry-Run] Would write {len(channels)} channels to {m3u_path} & {json_path}")

    # 4. Synchronize Supabase
    if not skip_db:
        print("\n3. Synchronizing Supabase ('toffee' category)...")
        auth_key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
        if not auth_key:
            print("   Warning: No Supabase API key available. Skipping DB sync.", file=sys.stderr)
            return

        db = SupabaseDbClient(SUPABASE_URL, auth_key, ADMIN_SECRET_TOKEN)

        # A. Fetch existing channels under category 'toffee'
        existing_channels_rows = db.get_all(
            "channels",
            select="id,name,category,stream_url,is_live,sort_order",
            filters={"category": "eq.toffee"}
        )
        existing_channels = {c["id"]: c for c in existing_channels_rows}
        print(f"   Existing channels in Supabase under 'toffee': {len(existing_channels)}")

        # B. Fetch existing stream_servers for toffee channels
        existing_servers: Dict[str, List[Dict[str, Any]]] = {}
        target_ids = list({c["id"] for c in channels}.union(set(existing_channels.keys())))
        if target_ids:
            batch_size = 80
            for i in range(0, len(target_ids), batch_size):
                chunk = target_ids[i:i + batch_size]
                id_in = f"({','.join(chunk)})"
                server_rows = db.get_all(
                    "stream_servers",
                    select="id,channel_id,name,stream_url,active,sort_order,headers",
                    filters={"channel_id": f"in.{id_in}"}
                )
                for s in server_rows:
                    cid = s["channel_id"]
                    existing_servers.setdefault(cid, []).append(s)

        # C. Prepare upserts for active channels
        channels_to_upsert = []
        servers_to_insert = []
        servers_to_update = []
        new_channel_ids = set()

        for ch in channels:
            ch_id = ch["id"]
            new_channel_ids.add(ch_id)

            channels_to_upsert.append({
                "id": ch_id,
                "name": ch["name"],
                "logo": ch["logo"],
                "category": "toffee",
                "country": "BD",
                "language": "bn",
                "is_live": True,
                "is_trending": False,
                "quality": ch["quality"],
                "stream_url": ch["stream_url"],
                "headers": ch["headers"],
                "drm": None,
                "proxy": False,
                "sort_order": ch["sort_order"],
                "has_vpn_detection": False
            })

            # Reconcile stream_servers
            c_servers = existing_servers.get(ch_id, [])
            server_spec = ch["servers"][0]

            if not c_servers:
                # No server exists, insert new
                servers_to_insert.append({
                    "channel_id": ch_id,
                    "name": server_spec["name"],
                    "stream_url": server_spec["stream_url"],
                    "headers": server_spec["headers"],
                    "drm": None,
                    "scheme": 0,
                    "has_header": bool(server_spec["headers"]),
                    "has_vpn_detection": False,
                    "sort_order": 1,
                    "active": True,
                    "health_status": "unknown",
                    "consecutive_failures": 0
                })
            else:
                # Update first server with new stream URL and headers
                primary_s = c_servers[0]
                patch = {}
                if primary_s.get("stream_url") != server_spec["stream_url"]:
                    patch["stream_url"] = server_spec["stream_url"]
                if primary_s.get("headers") != server_spec["headers"]:
                    patch["headers"] = server_spec["headers"]
                    patch["has_header"] = bool(server_spec["headers"])
                if not primary_s.get("active"):
                    patch["active"] = True

                if patch:
                    servers_to_update.append((primary_s["id"], patch))

        # D. Identify missing channels to deactivate
        channels_to_deactivate = []
        servers_to_deactivate = []
        for old_id, old_ch in existing_channels.items():
            if old_id not in new_channel_ids and old_ch.get("is_live"):
                channels_to_deactivate.append(old_id)
                for s in existing_servers.get(old_id, []):
                    if s.get("active"):
                        servers_to_deactivate.append(s["id"])

        print(f"   * Channels to upsert (active): {len(channels_to_upsert)}")
        print(f"   * Stream servers to insert: {len(servers_to_insert)}")
        print(f"   * Stream servers to update: {len(servers_to_update)}")
        print(f"   * Missing channels to deactivate: {len(channels_to_deactivate)}")

        # E. Execute DB writes if not dry-run
        if not dry_run:
            # Pre-flight category verification to prevent foreign key errors (channels_category_fkey)
            try:
                cat_resp = requests.get(f"{SUPABASE_URL}/rest/v1/categories?id=eq.toffee&select=id", headers=db.headers, timeout=10)
                if cat_resp.ok and not cat_resp.json():
                    print("   Registering missing 'toffee' category in Supabase...")
                    db.upsert_rows("categories", [{
                        "id": "toffee",
                        "name": "Toffee",
                        "active": True,
                        "sort_order": 20,
                        "type": "custom"
                    }], on_conflict="id")
            except Exception as e:
                print(f"   Warning: Could not pre-verify 'toffee' category in Supabase: {e}", file=sys.stderr)

            if channels_to_upsert:
                db.upsert_rows("channels", channels_to_upsert, on_conflict="id")
                print("   [DB Success] Upserted active channels.")

            if servers_to_insert:
                db.insert_rows("stream_servers", servers_to_insert)
                print("   [DB Success] Inserted new stream servers.")

            for s_id, patch in servers_to_update:
                db.update_row("stream_servers", s_id, patch)
            if servers_to_update:
                print(f"   [DB Success] Updated {len(servers_to_update)} stream servers.")

            for ch_id in channels_to_deactivate:
                db.update_row("channels", ch_id, {"is_live": False})
            for s_id in servers_to_deactivate:
                db.update_row("stream_servers", s_id, {"active": False})
            if channels_to_deactivate:
                print(f"   [DB Success] Deactivated {len(channels_to_deactivate)} obsolete channels.")
        else:
            print("   [Dry-Run] Skipped database write operations.")

    print("\n" + "=" * 72)
    print("Toffee TV Sync Completed Successfully!")
    print("=" * 72)


# ---------------------------------------------------------------------------
# CLI Entrypoint
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(description="Toffee TV Auto-Sync Engine")
    parser.add_argument("--source-url", default=DEFAULT_TOFFEE_SOURCE_URL, help="Source URL for toffee_data.json")
    parser.add_argument("--playlists-dir", default=DEFAULT_PLAYLISTS_DIR, help="Directory for generated M3U playlists")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR, help="Directory for generated JSON catalogs")
    parser.add_argument("--dry-run", action="store_true", help="Perform simulation without DB or file changes")
    parser.add_argument("--skip-db", action="store_true", help="Skip Supabase database synchronization")
    parser.add_argument("--skip-files", action="store_true", help="Skip local file generation")

    args = parser.parse_args()

    sync_toffee_pipeline(
        source_url=args.source_url,
        playlists_dir=args.playlists_dir,
        output_dir=args.output_dir,
        dry_run=args.dry_run,
        skip_db=args.skip_db,
        skip_files=args.skip_files
    )


if __name__ == "__main__":
    main()
