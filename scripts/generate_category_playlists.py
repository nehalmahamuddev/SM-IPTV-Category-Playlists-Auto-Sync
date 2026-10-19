#!/usr/bin/env python3
"""
SM IPTV Category Playlists Generator
Fetches live channels and sports from SM IPTV APIs and generates:
1. Individual .m3u files for each channel category in `playlists/`
2. Dedicated `playlists/live_sports.m3u` for live match feeds
3. Master `playlists/all.m3u` with all categories and live feeds
4. Index catalog in `playlists/README.md` with raw GitHub links and channel counts
5. Metadata index in `playlists/categories.json`
"""

import os
import re
import sys
import json
import time
import unicodedata
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any

try:
    import requests
except ImportError:
    print("Error: 'requests' is required. Run 'pip install requests'.", file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
BOOTSTRAP_URL = "https://app-main-ap.sm-monirul.xyz/exp/"
DEFAULT_USER_AGENT = "okhttp/4.12.0"
OUTPUT_DIR = os.environ.get("PLAYLISTS_DIR", "playlists")
GITHUB_REPO = os.environ.get("GITHUB_REPOSITORY", "nehalmahamuddev/SM-IPTV-Category-Playlists-Auto-Sync")
GITHUB_BRANCH = os.environ.get("GITHUB_REF_NAME", "main")
RAW_BASE_URL = f"https://raw.githubusercontent.com/{GITHUB_REPO}/{GITHUB_BRANCH}/{OUTPUT_DIR}"


def slugify_category(name: str) -> str:
    """
    Converts category names to clean filesystem-safe slugs.
    Handles math/stylized Unicode (e.g. bold serif 𝐌𝐮𝐬𝐢𝐜 -> music).
    """
    # Normalize unicode (compatibility decomposition turns math bold letters into standard ASCII)
    normalized = unicodedata.normalize("NFKD", name)
    clean = re.sub(r"[^\w\s-]", "", normalized).strip().lower()
    clean = re.sub(r"[-\s]+", "_", clean)
    if not clean:
        clean = "other"
    return clean


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
        expires_in = data.get("expires_in", 1800)
        self.token_expires_at = now + expires_in
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


def format_channel_m3u(ch: Dict[str, Any], group_title: str) -> List[str]:
    """Formats a single channel item into M3U Plus directives."""
    lines = []
    ch_id = ch.get("id", "")
    name = ch.get("name", "Unknown Channel").strip()
    logo = ch.get("logo", "").strip()
    stream_url = (ch.get("stream_url") or "").strip()
    if not stream_url:
        return []

    cookie = ch.get("cookie")
    referer = ch.get("referer")
    user_agent = ch.get("user_agent")
    kid = ch.get("kid")
    key = ch.get("key")

    extinf = f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{group_title}"'
    if user_agent:
        extinf += f' http-user-agent="{user_agent}"'
    if referer:
        extinf += f' http-referrer="{referer}"'
    extinf += f',{name}'

    lines.append(extinf)
    if user_agent:
        lines.append(f'#EXTVLCOPT:http-user-agent={user_agent}')
    if referer:
        lines.append(f'#EXTVLCOPT:http-referrer={referer}')
    if cookie:
        lines.append(f'#EXTVLCOPT:http-cookie={cookie}')
    if kid and key:
        lines.append('#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey')
        lines.append(f'#KODIPROP:inputstream.adaptive.license_key={kid}:{key}')

    lines.append(stream_url)
    return lines


def format_sport_stream_m3u(match: Dict[str, Any], stream: Dict[str, Any], idx: int) -> List[str]:
    """Formats a live sports event stream into M3U Plus directives."""
    lines = []
    category = match.get("Category", "Sports Event")
    event_name = match.get("event_name", "Live Match")
    event_info = match.get("eventInfo") or {}
    event_logo = event_info.get("event_logo") or event_info.get("teamAFlag") or ""

    ch_name = stream.get("channel_name") or f"Feed {idx+1}"
    stream_url = (stream.get("stream_url") or "").strip()
    if not stream_url:
        return []

    display_name = f"[Live] {event_name} - {ch_name}"
    user_agent = stream.get("user_agent")
    referer = stream.get("referer")
    kid = stream.get("kid")
    key = stream.get("key")

    extinf = f'#EXTINF:-1 tvg-name="{display_name}" tvg-logo="{event_logo}" group-title="Live Sports | {category}"'
    if user_agent:
        extinf += f' http-user-agent="{user_agent}"'
    if referer:
        extinf += f' http-referrer="{referer}"'
    extinf += f',{display_name}'

    lines.append(extinf)
    if user_agent:
        lines.append(f'#EXTVLCOPT:http-user-agent={user_agent}')
    if referer:
        lines.append(f'#EXTVLCOPT:http-referrer={referer}')
    if kid and key:
        lines.append('#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey')
        lines.append(f'#KODIPROP:inputstream.adaptive.license_key={kid}:{key}')

    lines.append(stream_url)
    return lines


def main():
    print(f"[{datetime.now(timezone.utc).isoformat()}] Starting SM IPTV Category Playlists Generator...")
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    client = SmIptvClient()
    print("1. Connecting to bootstrap gateway...")
    worker = client.get_worker_url()
    print(f"   Active Gateway: {worker}")

    print("2. Fetching session token...")
    token = client.get_token()
    print(f"   Session Token Acquired (valid for 30m): {token[:20]}...")

    # Fetch Channels
    print("3. Fetching linear channels catalog...")
    channels_data = client.get_channels()
    categories = channels_data.get("categories", [])
    print(f"   Found {len(categories)} categories.")

    # Fetch Sports
    print("4. Fetching live sports events...")
    sports_data = client.get_sports()
    matches = sports_data.get("matches", [])
    print(f"   Found {len(matches)} matches.")

    category_stats = []
    all_playlist_lines = [
        '#EXTM3U name="SM IPTV - All Channels & Live Sports"',
        f'# Generated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
        ''
    ]

    # Process each category
    for cat in categories:
        raw_name = cat.get("name", "Other")
        # Display name normalized for math unicode
        display_name = unicodedata.normalize("NFKD", raw_name)
        slug = slugify_category(raw_name)
        filename = f"{slug}.m3u"
        filepath = os.path.join(OUTPUT_DIR, filename)

        cat_lines = [
            f'#EXTM3U name="SM IPTV - {display_name}"',
            f'# Category: {display_name}',
            f'# Updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
            ''
        ]

        valid_channels = 0
        for ch in cat.get("channels", []):
            formatted = format_channel_m3u(ch, group_title=display_name)
            if formatted:
                valid_channels += 1
                cat_lines.extend(formatted)
                all_playlist_lines.extend(formatted)

        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(cat_lines) + "\n")

        print(f"   [Category] {display_name} -> {filename} ({valid_channels} channels)")
        category_stats.append({
            "name": display_name,
            "slug": slug,
            "filename": filename,
            "count": valid_channels,
            "type": "linear_tv",
            "raw_url": f"{RAW_BASE_URL}/{filename}"
        })

    # Process Live Sports into separate playlist
    live_sports_lines = [
        '#EXTM3U name="SM IPTV - Live Sports Events"',
        f'# Updated: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")}',
        ''
    ]
    live_sports_count = 0
    for match in matches:
        for idx, stream in enumerate(match.get("streams", [])):
            formatted = format_sport_stream_m3u(match, stream, idx)
            if formatted:
                live_sports_count += 1
                live_sports_lines.extend(formatted)
                all_playlist_lines.extend(formatted)

    live_sports_file = "live_sports.m3u"
    live_sports_path = os.path.join(OUTPUT_DIR, live_sports_file)
    with open(live_sports_path, "w", encoding="utf-8") as f:
        f.write("\n".join(live_sports_lines) + "\n")

    print(f"   [Sports Events] Live Sports -> {live_sports_file} ({live_sports_count} feeds)")
    category_stats.append({
        "name": "Live Sports Events",
        "slug": "live_sports",
        "filename": live_sports_file,
        "count": live_sports_count,
        "type": "live_events",
        "raw_url": f"{RAW_BASE_URL}/{live_sports_file}"
    })

    # Save Master Playlist
    master_file = "all.m3u"
    master_path = os.path.join(OUTPUT_DIR, master_file)
    total_items = sum(c["count"] for c in category_stats)
    with open(master_path, "w", encoding="utf-8") as f:
        f.write("\n".join(all_playlist_lines) + "\n")
    print(f"   [Master] All Channels -> {master_file} ({total_items} total streams)")

    # Save categories.json metadata
    categories_json_path = os.path.join(OUTPUT_DIR, "categories.json")
    with open(categories_json_path, "w", encoding="utf-8") as f:
        json.dump({
            "app_name": "SM IPTV",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "total_categories": len(category_stats),
            "total_channels": total_items,
            "master_playlist": f"{RAW_BASE_URL}/{master_file}",
            "categories": category_stats
        }, f, indent=2, ensure_ascii=False)

    # Generate README.md index with direct raw links
    readme_path = os.path.join(OUTPUT_DIR, "README.md")
    updated_str = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    readme_content = f"""# SM IPTV Category Playlists

> **Auto-generated and refreshed every 30 minutes via GitHub Actions.**  
> **Last Synchronized:** `{updated_str}`  
> **Total Channels & Feeds:** `{total_items}`  

---

## Master Playlist (All Categories + Live Sports)

| Playlist | Channels | Direct Raw Link (Copy into IPTV Player) |
|---|---|---|
| **All Channels & Sports** | **{total_items}** | [`{RAW_BASE_URL}/all.m3u`]({RAW_BASE_URL}/all.m3u) |

---

## Category Playlists

| Category | Streams | Raw Playlist URL |
|---|---|---|
"""
    for item in category_stats:
        readme_content += f"| **{item['name']}** | `{item['count']}` | [`{item['raw_url']}`]({item['raw_url']}) |\n"

    readme_content += """
---

## Compatible IPTV Players & Setup

These M3U playlists include standard channel metadata (`tvg-id`, `tvg-name`, `tvg-logo`, `group-title`), stream-specific HTTP headers (`User-Agent`, `Referer`), and ClearKey DRM tags (`org.w3.clearkey`).

### Recommended Players:
* **Android / Fire TV / Google TV:** [TiviMate IPTV Player](https://play.google.com/store/apps/details?id=ar.tvplayer.tv), [OTT Navigator](https://play.google.com/store/apps/details?id=studio.scillarium.ottnavigator), [Televizo](https://play.google.com/store/apps/details?id=com.televizo.tv)
* **Windows / macOS / Linux:** [VLC Media Player](https://www.videolan.org/vlc/), [IPTVnator](https://github.com/4ray/iptvnator), [Kodi](https://kodi.tv/)
* **iOS / Apple TV:** [IPTVX](https://iptvx.app/), [Smarters Player Lite](https://apps.apple.com/app/smarters-player-lite/id1628995509)

### How to use:
1. Copy the desired **Raw Playlist URL** from the table above.
2. Open your IPTV Player and choose **Add Playlist** -> **M3U Playlist URL**.
3. Paste the URL and set the refresh frequency to **Daily** or **Every 6 hours**.
"""

    with open(readme_path, "w", encoding="utf-8") as f:
        f.write(readme_content)

    print(f"5. Saved playlists/README.md and playlists/categories.json catalog successfully.")
    print("Done!")


if __name__ == "__main__":
    main()
