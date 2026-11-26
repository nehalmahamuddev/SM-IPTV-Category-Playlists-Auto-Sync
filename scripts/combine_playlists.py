#!/usr/bin/env python3
"""
Combined Multi-Source Playlist & JSON Generator
Merges all categories and sources (`output/channels.json` from SM IPTV and
`output/toffee.json` from Toffee) into:
  1. `output/combined.m3u` - single category-wise M3U playlist
  2. `output/combined.json` - category-grouped JSON catalog

Deduplication & Multi-Server Rules:
- Channels are matched by canonical normalized name/ID (stripping 'toffee_' prefix
  and quality tags).
- The first category a channel appears in (e.g., SM IPTV 'bangla') becomes its
  primary category.
- If the same channel appears again with an identical `stream_url`, it is treated
  as a duplicate and skipped.
- If it has a different `stream_url`, that stream is appended to the existing
  channel as Server 2, Server 3, Server 4, etc.
"""

import os
import re
import sys
import json
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple, Any

# Ensure sibling imports work whether run as `python scripts/combine_playlists.py` or imported
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)

from refine_playlists import format_channel_to_m3u, refine_channel_metadata


DEFAULT_CHANNELS_JSON = os.environ.get("CHANNELS_JSON_PATH", os.path.join("output", "channels.json"))
DEFAULT_TOFFEE_JSON = os.environ.get("TOFFEE_JSON_PATH", os.path.join("output", "toffee.json"))
DEFAULT_OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "output")


def canonical_channel_key(ch: Dict[str, Any]) -> str:
    """
    Returns a canonical key for matching the same channel across sources/categories.
    Strips 'toffee_' prefix and quality suffixes so e.g. 'toffee_somoy_tv' matches 'somoy_tv'.
    """
    raw_name = (ch.get("name") or "").strip()
    if raw_name:
        slug, _, _ = refine_channel_metadata(raw_name)
        if slug and slug != "channel":
            return slug

    ch_id = (ch.get("id") or "").strip().lower()
    if ch_id.startswith("toffee_"):
        ch_id = ch_id[len("toffee_"):]
    ch_id = re.sub(r'[^a-z0-9_]+', '_', ch_id).strip('_')
    return ch_id or "channel"


def _extract_servers(ch: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Extracts normalized server dicts from a channel entry."""
    servers = ch.get("servers")
    if isinstance(servers, list) and servers:
        return servers

    stream_url = (ch.get("stream_url") or "").strip()
    if not stream_url:
        return []

    return [{
        "name": f"Server 1 ({ch.get('quality', 'HD')})",
        "stream_url": stream_url,
        "quality": ch.get("quality", "HD"),
        "headers": ch.get("headers") or {},
        "drm": ch.get("drm"),
        "sort_order": 1,
    }]


def _load_channels_file(filepath: str) -> List[Dict[str, Any]]:
    """Loads channels list from a JSON file if it exists."""
    if not os.path.exists(filepath):
        print(f"   [Skip] Source file not found: {filepath}")
        return []
    with open(filepath, "r", encoding="utf-8") as f:
        data = json.load(f)
    if isinstance(data, dict):
        return data.get("channels", []) or []
    if isinstance(data, list):
        return data
    return []


def combine_sources(
    sm_channels: List[Dict[str, Any]],
    toffee_channels: List[Dict[str, Any]],
) -> Dict[str, List[Dict[str, Any]]]:
    """
    Combines SM IPTV and Toffee channel lists into a category-grouped dictionary.
    Deduplicates identical stream URLs and numbers distinct stream URLs as Server 1, 2, 3...
    """
    # Map canonical_key -> channel dict (kept in its primary category)
    by_key: Dict[str, Dict[str, Any]] = {}
    # Preserve category insertion order: SM IPTV categories first, then Toffee
    categories: Dict[str, List[Dict[str, Any]]] = {}

    for source_channels in (sm_channels, toffee_channels):
        for raw_ch in source_channels:
            key = canonical_channel_key(raw_ch)
            category = (raw_ch.get("category") or "other").strip() or "other"
            incoming_servers = _extract_servers(raw_ch)
            if not incoming_servers:
                continue

            if key not in by_key:
                # First time seeing this channel: establish its primary category
                _, clean_name, detected_quality = refine_channel_metadata(raw_ch.get("name") or key)
                quality = raw_ch.get("quality") or detected_quality or "HD"
                ch_entry: Dict[str, Any] = {
                    "id": key,
                    "name": (raw_ch.get("name") or clean_name).strip(),
                    "category": category,
                    "logo": (raw_ch.get("logo") or "").strip(),
                    "quality": quality,
                    "servers": [],
                }
                by_key[key] = ch_entry
                categories.setdefault(category, []).append(ch_entry)

            target_ch = by_key[key]
            if not target_ch["logo"] and raw_ch.get("logo"):
                target_ch["logo"] = raw_ch["logo"].strip()

            existing_urls = {s["stream_url"].strip() for s in target_ch["servers"] if s.get("stream_url")}

            for srv in incoming_servers:
                url = (srv.get("stream_url") or "").strip()
                if not url or url in existing_urls:
                    continue

                existing_urls.add(url)
                server_idx = len(target_ch["servers"]) + 1
                srv_quality = srv.get("quality") or target_ch["quality"] or "HD"
                target_ch["servers"].append({
                    "name": f"Server {server_idx} ({srv_quality})",
                    "stream_url": url,
                    "quality": srv_quality,
                    "headers": srv.get("headers") or {},
                    "drm": srv.get("drm"),
                    "sort_order": server_idx,
                })

    return categories


def build_combined_outputs(
    channels_json_path: str = DEFAULT_CHANNELS_JSON,
    toffee_json_path: str = DEFAULT_TOFFEE_JSON,
    output_dir: str = DEFAULT_OUTPUT_DIR,
) -> Tuple[str, str, Dict[str, Any]]:
    """
    Loads sources, merges channels, and writes `combined.m3u` and `combined.json`
    into `output_dir`. Returns (m3u_path, json_path, json_payload).
    """
    os.makedirs(output_dir, exist_ok=True)

    sm_channels = _load_channels_file(channels_json_path)
    toffee_channels = _load_channels_file(toffee_json_path)
    print(f"   Loaded {len(sm_channels)} SM IPTV channels and {len(toffee_channels)} Toffee channels.")

    categories = combine_sources(sm_channels, toffee_channels)

    total_channels = sum(len(chs) for chs in categories.values())
    total_streams = sum(len(ch["servers"]) for chs in categories.values() for ch in chs)
    category_counts = {
        cat: {
            "channels": len(chs),
            "streams": sum(len(ch["servers"]) for ch in chs),
        }
        for cat, chs in categories.items()
    }

    now_utc = datetime.now(timezone.utc)
    m3u_lines = [
        '#EXTM3U name="SM IPTV - Combined All Sources & Categories"',
        f'# Updated: {now_utc.strftime("%Y-%m-%d %H:%M:%S UTC")}',
        f'# Categories: {len(categories)} | Channels: {total_channels} | Streams: {total_streams}',
        '',
    ]

    for cat, chs in categories.items():
        m3u_lines.append(f'# --- Category: {cat} ({len(chs)} channels) ---')
        for ch in chs:
            m3u_lines.extend(format_channel_to_m3u(ch))

    m3u_path = os.path.join(output_dir, "combined.m3u")
    with open(m3u_path, "w", encoding="utf-8") as f:
        f.write("\n".join(m3u_lines) + "\n")

    json_payload: Dict[str, Any] = {
        "updated_at": now_utc.isoformat(),
        "total_categories": len(categories),
        "total_channels": total_channels,
        "total_streams": total_streams,
        "category_counts": category_counts,
        "categories": categories,
    }

    json_path = os.path.join(output_dir, "combined.json")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(json_payload, f, indent=2, ensure_ascii=False)

    print(
        f"   [Combined] {len(categories)} categories, {total_channels} channels, "
        f"{total_streams} streams -> {m3u_path} & {json_path}"
    )
    return m3u_path, json_path, json_payload


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Building combined M3U & JSON...")
    build_combined_outputs()
    print("Combined playlist generation completed successfully!")


if __name__ == "__main__":
    main()
