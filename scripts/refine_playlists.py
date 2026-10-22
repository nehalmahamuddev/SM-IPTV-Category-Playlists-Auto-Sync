#!/usr/bin/env python3
"""
SM IPTV Playlist Refinement Engine
Reads raw playlists from `playlists/`, normalizes channels into canonical IDs,
strips quality suffixes, groups multiple stream URLs per channel, and outputs
clean, refined M3U playlists and `output/channels.json` into the `output/` directory.
"""

import os
import re
import sys
import json
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

INPUT_DIR = os.environ.get("RAW_PLAYLISTS_DIR", "playlists")
OUTPUT_DIR = os.environ.get("REFINED_OUTPUT_DIR", "output")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync")
GITHUB_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
RAW_BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{OUTPUT_DIR}"


def refine_channel_metadata(raw_name: str) -> Tuple[str, str, str]:
    """
    Refines raw channel name into:
    1. canonical_id: lowercase slug stripped of quality tags (e.g. 't_sports')
    2. clean_name: human-readable name stripped of quality (e.g. 'T Sports')
    3. quality: detected quality string (e.g. 'FHD', 'HD', '4K', 'SD')
    """
    name = unicodedata.normalize("NFKD", raw_name).strip()

    # Detect quality tag
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

    # Clean channel name (strip quality words, server numbers, trailing punctuation)
    clean = re.sub(r'\b(4K|UHD|FHD|1080p|720p|HD|SD|HQ)\b', '', name, flags=re.IGNORECASE)
    clean = re.sub(r'(?<=[a-zA-Z0-9])(FHD|UHD|4K|HD)\b', '', clean, flags=re.IGNORECASE)
    clean = re.sub(r'^[0-9]+[\.\-\s]+', '', clean)
    clean = re.sub(r'[\.\-\|\:\_\s]+$', '', clean)
    clean = re.sub(r'\s+', ' ', clean).strip()
    if not clean:
        clean = name

    # Generate canonical slug ID
    slug = clean.lower()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[-\s]+', '_', slug).strip('_')
    if not slug:
        slug = "channel"

    return slug, clean, quality


def parse_m3u_file(filepath: str, default_category: str) -> List[Dict[str, Any]]:
    """Parses an M3U file into structured channel items."""
    if not os.path.exists(filepath):
        return []

    with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
        lines = [line.strip() for line in f if line.strip()]

    items = []
    current_inf = None
    current_headers = {}
    current_drm = None

    for line in lines:
        if line.startswith("#EXTINF:"):
            current_inf = line
            current_headers = {}
            current_drm = None

            # Extract user agent, referrer & origin from inline attributes if present
            ua_m = re.search(r'http-user-agent="([^"]+)"', line, re.IGNORECASE)
            if ua_m:
                current_headers["User-Agent"] = ua_m.group(1)

            ref_m = re.search(r'http-referrer="([^"]+)"', line, re.IGNORECASE)
            if ref_m:
                current_headers["Referer"] = ref_m.group(1)

            orig_m = re.search(r'http-origin="([^"]+)"', line, re.IGNORECASE)
            if orig_m:
                current_headers["Origin"] = orig_m.group(1)

        elif line.startswith("#EXTVLCOPT:"):
            opt = line[len("#EXTVLCOPT:"):].strip()
            if "=" in opt:
                k, v = opt.split("=", 1)
                k_lower = k.lower()
                if "user-agent" in k_lower:
                    current_headers["User-Agent"] = v
                elif "origin" in k_lower:
                    current_headers["Origin"] = v
                elif "referrer" in k_lower or "referer" in k_lower:
                    current_headers["Referer"] = v
                elif "cookie" in k_lower:
                    current_headers["Cookie"] = v

        elif line.startswith("#KODIPROP:inputstream.adaptive.license_key="):
            key_val = line.split("=", 1)[1].strip()
            if ":" in key_val:
                kid, key = key_val.split(":", 1)
                current_drm = {"type": "clearkey", "kid": kid, "key": key}

        elif not line.startswith("#") and (line.startswith("http://") or line.startswith("https://")):
            stream_url = line
            if current_inf:
                # Extract tvg-name, tvg-logo, group-title, and display title
                logo_m = re.search(r'tvg-logo="([^"]*)"', current_inf)
                group_m = re.search(r'group-title="([^"]*)"', current_inf)
                
                # Title is after the last comma
                comma_idx = current_inf.rfind(",")
                raw_title = current_inf[comma_idx + 1:].strip() if comma_idx != -1 else "Unknown"

                logo = logo_m.group(1) if logo_m else ""
                category = group_m.group(1) if group_m else default_category

                items.append({
                    "raw_title": raw_title,
                    "logo": logo,
                    "category": category,
                    "stream_url": stream_url,
                    "headers": current_headers,
                    "drm": current_drm
                })

            current_inf = None
            current_headers = {}
            current_drm = None

    return items


def refine_channels(raw_items: List[Dict[str, Any]], category_slug: str) -> Dict[str, Dict[str, Any]]:
    """
    Groups raw stream items by canonical channel ID and assigns Server 1, Server 2 labels.
    """
    channels: Dict[str, Dict[str, Any]] = {}

    for item in raw_items:
        raw_name = item["raw_title"]
        stream_url = item["stream_url"]
        canonical_id, clean_name, quality = refine_channel_metadata(raw_name)

        if canonical_id not in channels:
            channels[canonical_id] = {
                "id": canonical_id,
                "name": clean_name,
                "category": category_slug,
                "logo": item["logo"],
                "quality": quality,
                "servers": []
            }

        ch = channels[canonical_id]
        if not ch["logo"] and item["logo"]:
            ch["logo"] = item["logo"]

        # Deduplicate streams for this channel
        existing_urls = {s["stream_url"] for s in ch["servers"]}
        if stream_url not in existing_urls:
            server_idx = len(ch["servers"]) + 1
            server_name = f"Server {server_idx} ({quality})"
            ch["servers"].append({
                "name": server_name,
                "stream_url": stream_url,
                "quality": quality,
                "headers": item["headers"],
                "drm": item["drm"],
                "sort_order": server_idx
            })

    return channels


def format_channel_to_m3u(channel: Dict[str, Any]) -> List[str]:
    """
    Formats a refined channel and its multiple stream servers into M3U Plus directives.
    Each server shares the canonical tvg-id, with clear server indicators in the title.
    """
    lines = []
    ch_id = channel["id"]
    base_name = channel["name"]
    logo = channel.get("logo", "")
    category = channel.get("category", "")
    servers = channel.get("servers", [])

    for s in servers:
        server_name = s.get("name", "Server 1")
        display_title = f"{base_name} ({server_name})" if len(servers) > 1 else base_name
        stream_url = s["stream_url"]
        headers = s.get("headers") or {}
        drm = s.get("drm")

        extinf = f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{base_name}" tvg-logo="{logo}" group-title="{category}"'
        if headers.get("User-Agent"):
            extinf += f' http-user-agent="{headers["User-Agent"]}"'
        if headers.get("Referer"):
            extinf += f' http-referrer="{headers["Referer"]}"'
        if headers.get("Origin"):
            extinf += f' http-origin="{headers["Origin"]}"'
        extinf += f',{display_title}'

        lines.append(extinf)
        if headers.get("User-Agent"):
            lines.append(f'#EXTVLCOPT:http-user-agent={headers["User-Agent"]}')
        if headers.get("Referer"):
            lines.append(f'#EXTVLCOPT:http-referrer={headers["Referer"]}')
        if headers.get("Origin"):
            lines.append(f'#EXTVLCOPT:http-origin={headers["Origin"]}')
        if headers.get("Cookie"):
            lines.append(f'#EXTVLCOPT:http-cookie={headers["Cookie"]}')
        if drm and drm.get("type") == "clearkey":
            lines.append('#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey')
            lines.append(f'#KODIPROP:inputstream.adaptive.license_key={drm["kid"]}:{drm["key"]}')

        lines.append(stream_url)

    return lines


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting SM IPTV Refinement Engine...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    category_files = [
        ("bangla.m3u", "bangla", "Bangla"),
        ("sports.m3u", "sports", "Sports"),
        ("indian_bangla.m3u", "indian_bangla", "Indian Bangla"),
        ("hindi.m3u", "hindi", "Hindi"),
        ("documentory.m3u", "documentory", "Documentary"),
        ("kids.m3u", "kids", "Kids"),
        ("music.m3u", "music", "Music"),
        ("islamic.m3u", "islamic", "Islamic"),
        ("live_sports.m3u", "live_sports", "Live Sports Events")
    ]

    all_refined_channels: Dict[str, Dict[str, Any]] = {}
    category_summaries = []
    master_m3u_lines = [
        '#EXTM3U name="SM IPTV - Refined Master Playlist"',
        f'# Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
        ''
    ]

    for filename, cat_slug, display_cat in category_files:
        raw_filepath = os.path.join(INPUT_DIR, filename)
        if not os.path.exists(raw_filepath):
            print(f"   [Skip] {raw_filepath} does not exist.")
            continue

        raw_items = parse_m3u_file(raw_filepath, default_category=display_cat)
        refined_for_cat = refine_channels(raw_items, category_slug=cat_slug)

        cat_m3u_lines = [
            f'#EXTM3U name="SM IPTV - Refined {display_cat}"',
            f'# Category: {display_cat}',
            f'# Updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
            ''
        ]

        total_streams_in_cat = 0
        for ch_id, ch in refined_for_cat.items():
            formatted = format_channel_to_m3u(ch)
            cat_m3u_lines.extend(formatted)
            master_m3u_lines.extend(formatted)
            total_streams_in_cat += len(ch["servers"])

            # Merge into all_refined_channels
            if ch_id not in all_refined_channels:
                all_refined_channels[ch_id] = ch
            else:
                # Merge servers
                existing_urls = {s["stream_url"] for s in all_refined_channels[ch_id]["servers"]}
                for s in ch["servers"]:
                    if s["stream_url"] not in existing_urls:
                        all_refined_channels[ch_id]["servers"].append(s)

        out_filepath = os.path.join(OUTPUT_DIR, filename)
        with open(out_filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(cat_m3u_lines) + "\n")

        print(f"   [Refined] {display_cat}: {len(refined_for_cat)} channels, {total_streams_in_cat} streams -> {out_filepath}")
        category_summaries.append({
            "name": display_cat,
            "slug": cat_slug,
            "filename": filename,
            "channel_count": len(refined_for_cat),
            "stream_count": total_streams_in_cat,
            "raw_url": f"{RAW_BASE_URL}/{filename}"
        })

    # Save master refined all.m3u
    master_path = os.path.join(OUTPUT_DIR, "all.m3u")
    with open(master_path, "w", encoding="utf-8") as f:
        f.write("\n".join(master_m3u_lines) + "\n")

    total_channels = len(all_refined_channels)
    total_streams = sum(len(ch["servers"]) for ch in all_refined_channels.values())
    print(f"   [Master Refined] All Channels -> {master_path} ({total_channels} channels, {total_streams} streams)")

    # Save output/channels.json (Clean structured JSON for DB ingestion)
    channels_json_path = os.path.join(OUTPUT_DIR, "channels.json")
    with open(channels_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_channels": total_channels,
            "total_streams": total_streams,
            "channels": list(all_refined_channels.values())
        }, f, indent=2, ensure_ascii=False)
    print(f"   [JSON Database Ingest] Saved {channels_json_path}")

    # Generate output/README.md
    readme_path = os.path.join(OUTPUT_DIR, "README.md")
    updated_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    readme = f"""# SM IPTV - Refined Multi-Stream Playlists

> **Auto-generated and refined every 30 minutes via GitHub Actions.**  
> **Last Synchronized:** `{updated_str}`  
> **Total Unique Channels:** `{total_channels}`  
> **Total Stream Servers:** `{total_streams}`  

---

## Refined Master Playlist (Multi-Stream Enabled)

Each channel in this playlist groups multiple server URLs under the same canonical `tvg-id`, allowing IPTV players (TiviMate, OTT Navigator) to switch smoothly between backup servers.

| Playlist | Channels | Total Servers | Direct Raw Link |
|---|---|---|---|
| **All Channels (Master)** | **{total_channels}** | **{total_streams}** | [`{RAW_BASE_URL}/all.m3u`]({RAW_BASE_URL}/all.m3u) |

---

## Category Playlists

| Category | Unique Channels | Available Servers | Direct Raw Link |
|---|---|---|---|
"""
    for cat in category_summaries:
        readme += f"| **{cat['name']}** | `{cat['channel_count']}` | `{cat['stream_count']}` | [`{cat['raw_url']}`]({cat['raw_url']}) |\n"

    readme += f"""
---

## Structured Data for Database Ingestion

* **JSON Catalog:** [`{RAW_BASE_URL}/channels.json`]({RAW_BASE_URL}/channels.json)
"""

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme)

    print(f"   [README] Saved {readme_path}")
    print("Playlist Refinement completed successfully!")


if __name__ == "__main__":
    main()
