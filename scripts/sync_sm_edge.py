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
from typing import Dict, List, Optional, Any

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


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting SM IPTV Latest Edge Sync...")
    print(f"1. Fetching linear channels from Supabase Edge Function...")
    print(f"   Endpoint: {SUPABASE_EDGE_URL}")
    data = fetch_channels_data()
    cats = data.get("categories", [])
    print(f"   Retrieved {len(cats)} categories from upstream.")

    print(f"2. Generating playlists in '{OUTPUT_DIR}'...")
    catalog = build_playlists(data, OUTPUT_DIR)
    print(f"Done! Synced {catalog['total_channels']} channels across {catalog['total_categories']} categories.")


if __name__ == "__main__":
    main()
