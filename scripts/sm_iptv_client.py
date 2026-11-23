#!/usr/bin/env python3
"""
SM IPTV Client & M3U Playlist Generator
Reverse-engineered from SM IPTV.apk (com.sm.smiptv)
"""

import os
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
    DEFAULT_WORKER_URL = os.environ.get("SM_WORKER_URL", "https://ck.sm-monirulislam-exp.workers.dev/").strip()
    if not DEFAULT_WORKER_URL.endswith("/"):
        DEFAULT_WORKER_URL += "/"

    BOOTSTRAP_URLS = [
        "https://bb.sm-monirul.xyz/cc/exp/",
    ]
    SECURITY_KEY = os.environ.get("SM_SECURITY_KEY", "VFMFLPzAIv")
    DEFAULT_USER_AGENT = "okhttp/4.12.0"

    def __init__(self, session: Optional[requests.Session] = None):
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": self.DEFAULT_USER_AGENT})
        self.worker_url: Optional[str] = self.DEFAULT_WORKER_URL
        self.token: Optional[str] = None
        self.token_expires_at: float = 0.0

    @staticmethod
    def generate_signature(timestamp: str) -> str:
        """Generates dynamic X-Signature required by SM IPTV v2.0 gateway."""
        key = SmIptvClient.SECURITY_KEY
        key_bytes = key.encode()
        ts_bytes = timestamp.encode()
        return "".join(
            f"{b ^ key_bytes[i % len(key_bytes)]:02x}"
            for i, b in enumerate(ts_bytes)
        )

    def get_worker_url(self, force_refresh: bool = False) -> str:
        """Returns the active Cloudflare Worker API gateway (supports SM_WORKER_URL env and bootstrap fallback)."""
        if self.worker_url and not force_refresh:
            return self.worker_url

        if "SM_WORKER_URL" in os.environ:
            env_url = os.environ["SM_WORKER_URL"].strip()
            if not env_url.endswith("/"):
                env_url += "/"
            self.worker_url = env_url
            return self.worker_url

        if force_refresh:
            for b_url in self.BOOTSTRAP_URLS:
                try:
                    resp = self.session.get(b_url, timeout=10)
                    resp.raise_for_status()
                    url = resp.json().get("url", "").strip()
                    if url.startswith("https://"):
                        if not url.endswith("/"):
                            url += "/"
                        self.worker_url = url
                        return self.worker_url
                except Exception:
                    continue

        self.worker_url = self.DEFAULT_WORKER_URL
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

    def _auth_request(self, method: str, endpoint: str, max_retries: int = 3) -> Dict[str, Any]:
        """
        Executes an authenticated request with:
        1. Dynamic X-Signature & X-Timestamp headers
        2. Automatic retry with exponential backoff on network errors, 5xx, 429, 401/403, and empty/invalid JSON
        3. Automatic gateway & token refreshing on failure
        """
        delays = [3, 6, 12]
        last_error = None

        for attempt in range(max_retries):
            try:
                worker = self.get_worker_url()
                token = self.get_token()
                ts = str(int(time.time() * 1000))
                sig = self.generate_signature(ts)
                headers = {
                    "Authorization": f"Bearer {token}",
                    "User-Agent": self.DEFAULT_USER_AGENT,
                    "X-Timestamp": ts,
                    "X-Signature": sig
                }
                url = f"{worker}{endpoint.lstrip('/')}"
                resp = self.session.request(method, url, headers=headers, timeout=15)

                if resp.status_code in (401, 403):
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    self.get_token(force_refresh=True)
                    if attempt < max_retries - 1:
                        time.sleep(delays[attempt])
                    continue

                if resp.status_code in (429, 500, 502, 503, 504):
                    last_error = f"HTTP {resp.status_code}: {resp.text}"
                    self.get_worker_url(force_refresh=True)
                    self.get_token(force_refresh=True)
                    if attempt < max_retries - 1:
                        time.sleep(delays[attempt])
                    continue

                resp.raise_for_status()

                # Verify body is not empty and is valid JSON
                text = resp.text.strip()
                if not text:
                    raise ValueError(f"Empty response body received from {url}")

                return resp.json()

            except Exception as e:
                last_error = e
                if attempt < max_retries - 1:
                    try:
                        self.get_worker_url(force_refresh=True)
                        self.get_token(force_refresh=True)
                    except Exception:
                        pass
                    time.sleep(delays[attempt])

        raise RuntimeError(f"All {max_retries} attempts failed for endpoint '{endpoint}'. Last error: {last_error}")

    def get_channels(self) -> Dict[str, Any]:
        """Fetches the complete Live TV channels catalog grouped by category."""
        return self._auth_request("GET", "channels")

    def get_sports(self) -> Dict[str, Any]:
        """Fetches the Live Sports events and match feeds."""
        return self._auth_request("GET", "sports")

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
                    origin = ch.get("origin")
                    user_agent = ch.get("user_agent")
                    kid = ch.get("kid")
                    key = ch.get("key")

                    if origin and not referer:
                        referer = origin if origin.endswith("/") else f"{origin}/"

                    extinf = f'#EXTINF:-1 tvg-id="{ch_id}" tvg-name="{name}" tvg-logo="{logo}" group-title="{cat_name}"'
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
                        origin = stream.get("origin")
                        cookie = stream.get("cookie")
                        kid = stream.get("kid")
                        key = stream.get("key")

                        if origin and not referer:
                            referer = origin if origin.endswith("/") else f"{origin}/"

                        extinf = f'#EXTINF:-1 tvg-name="{display_name}" tvg-logo="{event_logo}" group-title="Live Sports | {category}"'
                        if user_agent:
                            extinf += f' http-user-agent="{user_agent}"'
                        if referer:
                            extinf += f' http-referrer="{referer}"'
                        if origin:
                            extinf += f' http-origin="{origin}"'
                        extinf += f',{display_name}'

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
            except Exception as e:
                lines.append(f'# Error fetching live sports: {e}')

        return "\n".join(lines)


if __name__ == "__main__":
    client = SmIptvClient()
    print("1. Resolving Active Worker Gateway...")
    worker = client.get_worker_url()
    print("   Active Gateway:", worker)

    print("2. Obtaining Session Token...")
    token = client.get_token()
    print(f"   Token: {token[:25]}... (expires in 30 min)")

    print("3. Generating M3U Playlist...")
    m3u_content = client.generate_m3u(include_sports=True)
    out_file = "sm_iptv_playlist.m3u"
    with open(out_file, "w", encoding="utf-8") as f:
        f.write(m3u_content)

    line_count = len(m3u_content.splitlines())
    print(f"4. Success! Generated {out_file} with {line_count} lines.")
