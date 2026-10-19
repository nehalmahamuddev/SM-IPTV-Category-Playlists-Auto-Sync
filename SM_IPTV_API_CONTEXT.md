# SM IPTV Backend Architecture & Live TV / M3U APIs Context

> **Reconstructed from:** `SM IPTV.apk` (`com.sm.smiptv`)  
> **Target OS:** Android (Jetpack Compose + Media3 ExoPlayer + Retrofit2)  
> **Generated Date:** 2026-10-19  
> **Status:** Verified with Live API Handshake & Payload Validation  

---

## 1. System Architecture Overview

The backend uses a **two-tier dynamic gateway architecture** designed to allow zero-downtime origin rotation without publishing APK updates:

```
[Client / App]
       |
       | 1. GET /exp/ (Bootstrap Configuration)
       v
[Config Gateway: https://app-main-ap.sm-monirul.xyz/]
       |
       | Returns active Edge Worker URL
       | e.g. "https://app-dt-1.sm-monirul-islam-rs.workers.dev/"
       v
[Cloudflare Edge Worker API Gateway]
       |
       | 2. POST /token (Request Session Token)
       | Returns Bearer JWT (expires_in: 1800s / 30 mins)
       |
       +----> 3. GET /channels (Authorization: Bearer <token>)
       |      Returns 180+ Live TV Channels grouped by Category
       |
       +----> 4. GET /sports (Authorization: Bearer <token>)
              Returns Live Sports Matches & multi-feed streams
```

---

## 2. API Endpoints Specification

### 2.1 Bootstrap Gateway (Worker URL Discovery)

* **Class in APK:** `com.sm.smiptv.network.ConfigService` (invoked in `v6.j` and `v6.n`)
* **Endpoint:** `GET https://app-main-ap.sm-monirul.xyz/exp/`
* **Headers:**
  ```http
  User-Agent: okhttp/4.12.0
  ```
* **Response Body (`200 OK`):**
  ```json
  {
    "url": "https://app-dt-1.sm-monirul-islam-rs.workers.dev/"
  }
  ```
* **Validation Logic in App (`v6.j:c`):**
  - Trailing slash `/` is appended if missing.
  - Verifies that URL begins with `https://`.
  - Result is cached in memory for subsequent API service instances.

---

### 2.2 Authentication / Session Token

* **Class in APK:** `com.sm.smiptv.network.AuthService`
* **Endpoint:** `POST <WORKER_URL>token`
  *(e.g., `POST https://app-dt-1.sm-monirul-islam-rs.workers.dev/token`)*
* **Headers:**
  ```http
  User-Agent: okhttp/4.12.0
  Content-Length: 0
  ```
* **Response Body (`200 OK`):**
  ```json
  {
    "token": "eyJpYXQiOjE3OTI0MTc1MjIsImV4cCI6MTc5MjQxOTMyMn0.10HIgvLJQFvORdbesv4bNAPDO_VovPgIcOCb8A5hmFQ",
    "expires_in": 1800
  }
  ```
* **Client Token Lifecycle (`v6.j:b` & `v6.n:a`):**
  - Token validity is 1800 seconds (30 minutes).
  - Client stores `expiresAt = currentTimeSeconds + expiresIn`.
  - App triggers auto-refresh when `currentTimeSeconds >= (expiresAt - 60)` (refresh 1 minute before expiration).
  - On any `401 Unauthorized` or `HttpException`, token cache is invalidated and refreshed.

---

### 2.3 Live TV Channels Catalog

* **Class in APK:** `com.sm.smiptv.network.ChannelService`
* **Endpoint:** `GET <WORKER_URL>channels`
* **Headers:**
  ```http
  User-Agent: okhttp/4.12.0
  Authorization: Bearer <TOKEN>
  ```
* **Response Model (`com.sm.smiptv.model.ChannelDataResponse`):**
  ```json
  {
    "app_name": "SM IPTV",
    "developed_by": "Monirul Islam Shakib",
    "telegram_channel": "https://t.me/sm_iptv_bd",
    "categories": [
      {
        "name": "Bangla",
        "channels": [
          {
            "id": "1",
            "name": "G-Series",
            "logo": "https://aynaott.com/images/channel/gseries.png",
            "stream_url": "https://vods2.aynaott.com/gseriesDrama/tracks-v1a1/mono.ts.m3u8",
            "cookie": null,
            "referer": null,
            "user_agent": null,
            "origin": null,
            "kid": null,
            "key": null
          }
        ]
      }
    ]
  }
  ```

#### Category Inventory (180 Total Channels):
1. **Bangla** (65 channels) — National, news, drama, entertainment (BTV, G-Series, Channel i, Deepto, etc.)
2. **Sports** (24 channels) — T Sports, PTV Sports, Star Sports, Sony Sports, Willow, SuperSport, etc.
3. **Indian Bangla** (11 channels) — Zee Bangla, Star Jalsha, Jalsha Movies, Colors Bangla, etc.
4. **Hindi** (40 channels) — Sony Max, Star Plus, Zee TV, Zee Cinema, Colors, Aaj Tak, etc.
5. **Documentory** (8 channels) — Discovery, Animal Planet, Nat Geo, History TV, etc.
6. **Kids** (13 channels) — Durunto, Nick Bangla, Cartoon Network, Sonic, Pogo, etc.
7. **Music (𝐌𝐮𝐬𝐢𝐜)** (13 channels) — MTV, 9XM, B4U Music, Zing, Sangeet Bangla, etc.
8. **Islamic** (6 channels) — Peace TV, Quran TV, Madani Channel, Makkah Live, etc.

---

### 2.4 Live Sports Events & Match Feeds

* **Class in APK:** `com.sm.smiptv.network.SportsService`
* **Endpoint:** `GET <WORKER_URL>sports`
* **Headers:**
  ```http
  User-Agent: okhttp/4.12.0
  Authorization: Bearer <TOKEN>
  ```
* **Response Model (`com.sm.smiptv.model.LiveEventResponse`):**
  ```json
  {
    "name": "SM IPTV Sports Hub",
    "owner": "Monirul Islam Shakib",
    "telegram_channel": "https://t.me/sm_iptv_bd",
    "last_update_time": "19/10/2026",
    "total_matches": 39,
    "live_match": "...",
    "matches": [
      {
        "status": "LIVE",
        "Category": "Cricket",
        "event_name": "Team A Vs Team B",
        "eventInfo": {
          "teamA": "Team A",
          "teamB": "Team B",
          "teamAFlag": "https://...",
          "teamBFlag": "https://...",
          "eventName": "Tournament / League Name",
          "event_logo": "https://...",
          "startTime": "19/10/2026 07:30:00 PM"
        },
        "streams": [
          {
            "channel_name": "T Sports HD (Server 1)",
            "stream_url": "https://.../index.m3u8",
            "referer": "https://...",
            "user_agent": "Mozilla/5.0 ...",
            "kid": null,
            "key": null
          },
          {
            "channel_name": "TSN4 Sports FHD (DASH ClearKey)",
            "stream_url": "https://otte.cache.aiv-cdn.net/.../cenc.mpd",
            "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36...",
            "kid": "abc5b2883121012850ebda05b528c5ec",
            "key": "e5250924f4b738905f7163a0134587a7"
          }
        ]
      }
    ]
  }
  ```

---

### 2.5 App Update & Announcement Feed

* **Class in APK:** `v6.y` -> `com.sm.smiptv.network.UpdateService`
* **Base64 in Bytecode:** `aHR0cHM6Ly9lcHgtdWx0cmEuc20tbW9uaXJ1bC54eXovYXBwL2FwcF91cGRhdGEuanNvbg==`
* **Endpoint:** `GET https://epx-ultra.sm-monirul.xyz/app/app_updata.json`
* **Response Model (`com.sm.smiptv.model.UpdateInfo`):**
  ```json
  {
    "versionCode": 6,
    "versionName": "1.0.6",
    "updateUrl": "https://...",
    "title": "New Update Available",
    "message": "Update notes and bug fixes",
    "mandatory": false,
    "changes": [
      "Added new sports servers",
      "Fixed player playback buffering"
    ]
  }
  ```

---

## 3. Stream Protocols & Player Integration

In `com.sm.smiptv.model.Channel` and `Stream`:

| Stream Type | Ext / Container | Proportion | Handling Details |
|---|---|---|---|
| **HLS Direct** | `.m3u8` | ~90% | Standard HLS direct playback |
| **HLS with Headers** | `.m3u8` | ~7% | Requires `referer`, `cookie`, `origin`, or `user_agent` headers in HTTP request |
| **DASH ClearKey** | `.mpd` (CENC) | ~3% | Requires ClearKey DRM parameters (`kid` + `key`) |

### 3.1 Standard M3U Playlist Formatting

For standard IPTV players (TiviMate, OTT Navigator, VLC, IPTV Smarters):

#### Standard Channel:
```m3u
#EXTINF:-1 tvg-id="1" tvg-name="G-Series" tvg-logo="https://aynaott.com/images/channel/gseries.png" group-title="Bangla",G-Series
https://vods2.aynaott.com/gseriesDrama/tracks-v1a1/mono.ts.m3u8
```

#### Channel with Custom Headers:
```m3u
#EXTINF:-1 tvg-id="66" tvg-name="T Sports" tvg-logo="https://..." group-title="Sports" http-user-agent="Mozilla/5.0..." http-referrer="https://...",T Sports
#EXTVLCOPT:http-user-agent=Mozilla/5.0...
#EXTVLCOPT:http-referrer=https://...
https://tvsen5.aynaott.com/TnMn5kZz8aLmjklkk/index.m3u8
```

#### Channel with ClearKey DRM (Kodi / TiviMate / OTT Navigator syntax):
```m3u
#EXTINF:-1 tvg-id="ihys8nw4wv" tvg-name="TSN4 SPORTS FHD" group-title="Sports",TSN4 SPORTS FHD
#KODIPROP:inputstream.adaptive.license_type=org.w3.clearkey
#KODIPROP:inputstream.adaptive.license_key=abc5b2883121012850ebda05b528c5ec:e5250924f4b738905f7163a0134587a7
https://otte.cache.aiv-cdn.net/bom-nitro/live/clients/dash/enc/ihys8nw4wv/out/v1/fde190f369484bc6b6117cc16cd82a9f/cenc.mpd
```

---

## 4. Complete Python Client & M3U Generator Implementation

Save the following module as `sm_iptv_client.py` for integration in other projects:

```python
import time
import requests
import json
from typing import Dict, List, Optional, Any

class SmIptvClient:
    """
    Client for SM IPTV dynamic backend APIs.
    Automatically handles worker URL discovery, session token rotation,
    channel extraction, sports feed syncing, and M3U playlist generation.
    """
    BOOTSTRAP_URL = "https://app-main-ap.sm-monirul.xyz/exp/"
    DEFAULT_USER_AGENT = "okhttp/4.12.0"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.DEFAULT_USER_AGENT})
        self.worker_url: Optional[str] = None
        self.token: Optional[str] = None
        self.token_expires_at: float = 0.0

    def get_worker_url(self, force_refresh: bool = False) -> str:
        """Discovers the active Cloudflare Worker API gateway."""
        if self.worker_url and not force_refresh:
            return self.worker_url

        resp = self.session.get(self.BOOTSTRAP_URL, timeout=10)
        resp.raise_for_status()
        url = resp.json().get("url", "").strip()
        if not url.startswith("https://"):
            raise ValueError(f"Invalid worker URL received: {url}")
        if not url.endswith("/"):
            url += "/"
        self.worker_url = url
        return self.worker_url

    def get_token(self, force_refresh: bool = False) -> str:
        """Obtains or refreshes the 30-minute JWT session token."""
        now = time.time()
        if self.token and not force_refresh and now < (self.token_expires_at - 60):
            return self.token

        worker = self.get_worker_url(force_refresh=force_refresh)
        resp = self.session.post(f"{worker}token", timeout=10)
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
            "User-Agent": self.DEFAULT_USER_AGENT
        }
        url = f"{worker}{endpoint.lstrip('/')}"
        resp = self.session.request(method, url, headers=headers, timeout=15)
        if resp.status_code == 401 and retry:
            self.get_token(force_refresh=True)
            return self._auth_request(method, endpoint, retry=False)
        resp.raise_for_status()
        return resp

    def get_channels(self) -> Dict[str, Any]:
        """Fetches the complete Live TV channels catalog grouped by category."""
        return self._auth_request("GET", "channels").json()

    def get_sports(self) -> Dict[str, Any]:
        """Fetches the Live Sports events and match feeds."""
        return self._auth_request("GET", "sports").json()

    def generate_m3u(self, include_sports: bool = True) -> str:
        """
        Generates a standard M3U Plus playlist string with metadata,
        logos, headers, and ClearKey DRM tags.
        """
        lines = [
            '#EXTM3U name="SM IPTV Channels"',
            '# Generated by SM IPTV Client Pipeline'
        ]

        # 1. Process Live TV channels
        try:
            channel_data = self.get_channels()
            categories = channel_data.get("categories", [])
            for cat in categories:
                cat_name = cat.get("name", "General")
                for ch in cat.get("channels", []):
                    ch_id = ch.get("id", "")
                    name = ch.get("name", "Unknown Channel")
                    logo = ch.get("logo", "")
                    stream_url = (ch.get("stream_url") or "").strip()
                    if not stream_url:
                        continue

                    cookie = ch.get("cookie")
                    referer = ch.get("referer")
                    user_agent = ch.get("user_agent")
                    kid = ch.get("kid")
                    key = ch.get("key")

                    extinf = f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{cat_name}"'
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
        except Exception as e:
            lines.append(f'# Error fetching live channels: {e}')

        # 2. Process Live Sports feeds if requested
        if include_sports:
            try:
                sports_data = self.get_sports()
                matches = sports_data.get("matches", [])
                for match in matches:
                    category = match.get("Category", "Sports Event")
                    event_name = match.get("event_name", "Live Match")
                    event_info = match.get("eventInfo") or {}
                    event_logo = event_info.get("event_logo") or event_info.get("teamAFlag") or ""

                    for idx, stream in enumerate(match.get("streams", [])):
                        ch_name = stream.get("channel_name") or f"Feed {idx+1}"
                        stream_url = (stream.get("stream_url") or "").strip()
                        if not stream_url:
                            continue

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
            except Exception as e:
                lines.append(f'# Error fetching live sports: {e}')

        return "\n".join(lines)


if __name__ == "__main__":
    client = SmIptvClient()
    print("Resolving Worker URL...")
    worker = client.get_worker_url()
    print("Active Worker Gateway:", worker)

    print("Obtaining Session Token...")
    token = client.get_token()
    print(f"Token acquired: {token[:25]}... (valid for 30m)")

    print("Generating M3U playlist...")
    m3u_content = client.generate_m3u(include_sports=True)
    with open("sm_iptv_playlist.m3u", "w", encoding="utf-8") as f:
        f.write(m3u_content)

    print(f"Done! Playlist saved to sm_iptv_playlist.m3u ({len(m3u_content.splitlines())} lines).")
```

---

## 5. Security & Stability Considerations

1. **Gateway Resilience:** Never hardcode the `*.workers.dev` endpoint directly in client code; always query `https://app-main-ap.sm-monirul.xyz/exp/` to discover the live worker URL. The developer rotates workers if Cloudflare limits or bandwidth caps are reached.
2. **Token Expiry Management:** Cache token responses locally and refresh prior to 1800s expiration to avoid connection drops during live playback.
3. **Stream Protocol Diversity:** Player clients should handle both HLS (`.m3u8`) and DASH MPD (`.mpd`) with ClearKey decryption support.
