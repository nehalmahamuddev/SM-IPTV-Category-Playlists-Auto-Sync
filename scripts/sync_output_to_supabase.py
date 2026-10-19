#!/usr/bin/env python3
"""
SM IPTV Refined Output -> Supabase Sync Engine
Ingests canonical channels and multiple stream servers directly from `output/channels.json`
into Supabase tables (`public.channels` and `public.stream_servers`) using a Reconcile / Mirror strategy.
"""

import os
import sys
import json
import argparse
from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Tuple, Any

try:
    import requests
except ImportError:
    print("Error: 'requests' is required. Run 'pip install requests'.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Default Configuration
# ---------------------------------------------------------------------------
DEFAULT_CHANNELS_JSON = os.environ.get("CHANNELS_JSON_PATH", os.path.join("output", "channels.json"))

SUPABASE_URL = os.environ.get("SUPABASE_URL", "https://hqmhuvsjlykrdusfkmeg.supabase.co").rstrip("/")
SUPABASE_SERVICE_ROLE_KEY = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
SUPABASE_ANON_KEY = os.environ.get(
    "SUPABASE_ANON_KEY",
    "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6ImhxbWh1dnNqbHlrcmR1c2ZrbWVnIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODI4MjI3OTEsImV4cCI6MjA5ODM5ODc5MX0.sfNEW7QG0idyVVRHlDtYjITDfIbsFQQm2u9a3ffoNoA"
)
ADMIN_SECRET_TOKEN = (os.environ.get("ADMIN_SECRET_TOKEN") or "GoLiveAdminSecret2026").strip()

# Target Linear TV categories to sync to Supabase (excludes live_sports by default)
DEFAULT_TARGET_CATEGORIES = [
    "bangla",
    "sports",
    "indian_bangla",
    "hindi",
    "documentory",
    "kids",
    "music",
    "islamic"
]


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
        """Fetches rows from Supabase PostgREST with pagination support."""
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
        """Upserts a list of rows in batches."""
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
            resp = requests.post(url, headers=headers, json=batch, timeout=25)
            if not resp.ok:
                print(f"[Supabase Upsert Error on {table}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                resp.raise_for_status()
            total += len(batch)
        return total

    def insert_rows(self, table: str, rows: List[Dict[str, Any]]) -> int:
        """Inserts a list of rows in batches."""
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
        """Updates a specific row by its id."""
        url = f"{self.base_url}/rest/v1/{table}?id=eq.{row_id}"
        headers = dict(self.headers)
        headers["Prefer"] = "return=minimal"
        resp = requests.patch(url, headers=headers, json=patch_data, timeout=15)
        if not resp.ok:
            print(f"[Supabase Update Error on {table} {row_id}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
            resp.raise_for_status()
        return True

    def delete_rows_by_ids(self, table: str, ids: List[str]) -> int:
        """Deletes rows matching a list of ids in batches."""
        if not ids:
            return 0
        batch_size = 100
        total = 0
        for i in range(0, len(ids), batch_size):
            batch = ids[i:i + batch_size]
            id_in = f"({','.join(batch)})"
            url = f"{self.base_url}/rest/v1/{table}?id=in.{id_in}"
            headers = dict(self.headers)
            headers["Prefer"] = "return=minimal"
            resp = requests.delete(url, headers=headers, timeout=20)
            if not resp.ok:
                print(f"[Supabase Delete Error on {table}] Status: {resp.status_code}, Body: {resp.text}", file=sys.stderr)
                resp.raise_for_status()
            total += len(batch)
        return total


# ---------------------------------------------------------------------------
# Country & Language Resolvers
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Core Synchronization Logic
# ---------------------------------------------------------------------------
def sync_output_to_supabase(
    channels_json_path: str = DEFAULT_CHANNELS_JSON,
    target_categories: Optional[List[str]] = None,
    dry_run: bool = False
):
    print("=" * 72)
    print("SM IPTV Refined Output -> Supabase Sync Engine")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()} | Dry-Run: {dry_run}")
    print("=" * 72)

    if not os.path.exists(channels_json_path):
        raise FileNotFoundError(f"Channels catalog file not found: {channels_json_path}. Run 'scripts/refine_playlists.py' first!")

    with open(channels_json_path, "r", encoding="utf-8") as f:
        catalog_data = json.load(f)

    all_channels = catalog_data.get("channels", [])
    print(f"1. Loaded {len(all_channels)} total channels from '{channels_json_path}'")

    # Filter by target categories
    categories_set = set(target_categories or DEFAULT_TARGET_CATEGORIES)
    filtered_channels = [ch for ch in all_channels if ch.get("category") in categories_set]
    print(f"   Filtering to {len(filtered_channels)} channels across categories: {sorted(list(categories_set))}")

    # Initialize Supabase client
    auth_key = SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY
    if not auth_key:
        raise ValueError("Missing SUPABASE_SERVICE_ROLE_KEY or SUPABASE_ANON_KEY.")

    db = SupabaseDbClient(SUPABASE_URL, auth_key, ADMIN_SECRET_TOKEN)

    # 2. Query existing channels and stream_servers in Supabase for target categories
    print("\n2. Querying existing channels and stream_servers from Supabase...")
    
    # Query channels for these categories
    cat_filter = f"({','.join(categories_set)})"
    existing_channels_rows = db.get_all(
        "channels",
        select="id,name,category,stream_url,quality,logo,sort_order",
        filters={"category": f"in.{cat_filter}"}
    )
    existing_channels = {c["id"]: c for c in existing_channels_rows}
    print(f"   Found {len(existing_channels)} existing channels in target categories.")

    # Collect IDs of channels
    target_channel_ids = {ch["id"] for ch in filtered_channels}.union(set(existing_channels.keys()))

    # Fetch existing stream_servers for these channels
    existing_servers: Dict[str, List[Dict[str, Any]]] = {}
    total_existing_servers = 0
    if target_channel_ids:
        id_list = list(target_channel_ids)
        batch_size = 80
        for i in range(0, len(id_list), batch_size):
            chunk = id_list[i:i + batch_size]
            id_in = f"({','.join(chunk)})"
            server_rows = db.get_all(
                "stream_servers",
                select="id,channel_id,name,stream_url,sort_order,active,drm,headers,scheme",
                filters={"channel_id": f"in.{id_in}"}
            )
            for s in server_rows:
                cid = s["channel_id"]
                existing_servers.setdefault(cid, []).append(s)
                total_existing_servers += 1

    print(f"   Found {total_existing_servers} existing stream_servers across {len(existing_servers)} channels.")

    # 3. Build channels upsert list and stream_servers reconcile actions
    print("\n3. Building channels records and reconciling multi-stream servers...")

    channels_to_upsert: List[Dict[str, Any]] = []
    servers_to_insert: List[Dict[str, Any]] = []
    servers_to_update: List[Tuple[str, Dict[str, Any]]] = []
    server_ids_to_delete: List[str] = []

    for sort_idx, ch in enumerate(filtered_channels, start=1):
        ch_id = ch["id"]
        ch_name = ch["name"]
        cat_slug = ch["category"]
        logo = ch.get("logo") or ""
        quality = ch.get("quality", "HD")
        servers = ch.get("servers", [])

        country, language = resolve_channel_metadata(cat_slug)

        primary_url = servers[0]["stream_url"] if servers else ""
        primary_headers = servers[0].get("headers") or {} if servers else {}
        primary_drm = servers[0].get("drm") if servers else None

        channels_to_upsert.append({
            "id": ch_id,
            "name": ch_name,
            "logo": logo,
            "category": cat_slug,
            "country": country,
            "language": language,
            "is_live": True,
            "is_trending": False,
            "quality": quality,
            "stream_url": primary_url,
            "headers": primary_headers,
            "drm": primary_drm,
            "proxy": False,
            "sort_order": sort_idx
        })

        # Reconcile / Mirror stream_servers for this channel
        current_servers = existing_servers.get(ch_id, [])
        db_by_url = {s["stream_url"]: s for s in current_servers if s.get("stream_url")}
        desired_urls = {s["stream_url"] for s in servers}

        # A. Insert new servers
        for s_idx, s in enumerate(servers, start=1):
            s_url = s["stream_url"]
            s_name = s.get("name", f"Server {s_idx} ({quality})")
            s_headers = s.get("headers") or {}
            s_drm = s.get("drm")
            s_scheme = 2 if s_drm else 0

            if s_url not in db_by_url:
                servers_to_insert.append({
                    "channel_id": ch_id,
                    "name": s_name,
                    "stream_url": s_url,
                    "headers": s_headers,
                    "drm": s_drm,
                    "scheme": s_scheme,
                    "has_header": bool(s_headers),
                    "has_vpn_detection": False,
                    "sort_order": s_idx,
                    "active": True
                })
            else:
                # B. Check if existing server needs update
                existing = db_by_url[s_url]
                needs_update = False
                patch = {}

                if existing.get("name") != s_name:
                    patch["name"] = s_name
                    needs_update = True
                if existing.get("sort_order") != s_idx:
                    patch["sort_order"] = s_idx
                    needs_update = True
                if existing.get("drm") != s_drm:
                    patch["drm"] = s_drm
                    patch["scheme"] = s_scheme
                    needs_update = True
                if existing.get("headers") != s_headers:
                    patch["headers"] = s_headers
                    patch["has_header"] = bool(s_headers)
                    needs_update = True

                if needs_update:
                    servers_to_update.append((existing["id"], patch))

        # C. Identify obsolete servers to prune
        for existing in current_servers:
            e_url = existing.get("stream_url")
            if e_url and e_url not in desired_urls:
                server_ids_to_delete.append(existing["id"])

    print(f"   * Channels to upsert: {len(channels_to_upsert)}")
    print(f"   * Stream servers to insert: {len(servers_to_insert)}")
    print(f"   * Stream servers to update: {len(servers_to_update)}")
    print(f"   * Obsolete stream servers to delete: {len(server_ids_to_delete)}")

    # 4. Dry-Run Reporting
    if dry_run:
        print("\n" + "=" * 50)
        print("[DRY-RUN MODE] Preview of actions:")
        print("=" * 50)
        print("\n[Preview: Channels to Upsert (First 5)]:")
        for ch in channels_to_upsert[:5]:
            print(f"   - ID: {ch['id']:<20} | Name: {ch['name']:<25} | Cat: {ch['category']:<15} | Quality: {ch['quality']}")

        print("\n[Preview: Stream Servers to Insert (First 5)]:")
        for s in servers_to_insert[:5]:
            print(f"   - Channel: {s['channel_id']:<20} | Server: {s['name']:<20} | URL: {s['stream_url'][:60]}...")

        if servers_to_update:
            print("\n[Preview: Stream Servers to Update (First 5)]:")
            for s_id, patch in servers_to_update[:5]:
                print(f"   - Server ID: {s_id} | Changes: {patch}")

        if server_ids_to_delete:
            print(f"\n[Preview: Stream Server IDs to Delete (Total {len(server_ids_to_delete)})]:")
            print(f"   - IDs: {server_ids_to_delete[:10]}")

        print("\n[DRY RUN COMPLETE] No modifications were made to Supabase.")
        return

    # 5. Live Execution
    print("\n4. Executing Database Updates in Supabase...")

    # Step 1: Upsert Channels
    if channels_to_upsert:
        print(f"   Upserting {len(channels_to_upsert)} channels into 'public.channels'...")
        cnt = db.upsert_rows("channels", channels_to_upsert, on_conflict="id")
        print(f"   Successfully upserted {cnt} channels.")

    # Step 2: Insert New Servers
    if servers_to_insert:
        print(f"   Inserting {len(servers_to_insert)} new stream servers into 'public.stream_servers'...")
        cnt = db.insert_rows("stream_servers", servers_to_insert)
        print(f"   Successfully inserted {cnt} stream servers.")

    # Step 3: Update Modified Servers
    if servers_to_update:
        print(f"   Updating {len(servers_to_update)} existing stream servers...")
        up_cnt = 0
        for s_id, patch in servers_to_update:
            db.update_row("stream_servers", s_id, patch)
            up_cnt += 1
        print(f"   Successfully updated {up_cnt} stream servers.")

    # Step 4: Delete Obsolete Servers
    if server_ids_to_delete:
        print(f"   Pruning {len(server_ids_to_delete)} obsolete stream servers...")
        del_cnt = db.delete_rows_by_ids("stream_servers", server_ids_to_delete)
        print(f"   Successfully deleted {del_cnt} obsolete stream servers.")

    print("\n" + "=" * 72)
    print("Supabase Linear Channels & Multi-Stream Sync Completed Successfully!")
    print("=" * 72)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Sync refined SM IPTV channels from output/channels.json to Supabase")
    parser.add_argument("--file", default=DEFAULT_CHANNELS_JSON, help="Path to refined channels.json")
    parser.add_argument("--categories", nargs="+", default=DEFAULT_TARGET_CATEGORIES, help="Categories to sync")
    parser.add_argument("--dry-run", action="store_true", help="Preview sync actions without writing to Supabase")
    args = parser.parse_args()

    sync_output_to_supabase(
        channels_json_path=args.file,
        target_categories=args.categories,
        dry_run=args.dry_run
    )
