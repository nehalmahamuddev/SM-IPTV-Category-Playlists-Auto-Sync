#!/usr/bin/env python3
"""Probe the specific worker URL to see what endpoints exist."""

import requests, json, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sm_iptv_client import SmIptvClient

WORKER_URL = os.environ.get("SM_WORKER_URL", "https://ck.sm-monirulislam-exp.workers.dev/")
UA = "okhttp/4.12.0"

session = requests.Session()
session.headers.update({"User-Agent": UA})

endpoints_to_try = [
    ("GET",  ""),
    ("GET",  "token"),
    ("POST", "token"),
    ("GET",  "channels"),
    ("GET",  "sports"),
    ("GET",  "exp"),
    ("GET",  "exp/"),
    ("GET",  "api"),
    ("GET",  "api/"),
    ("GET",  "api/channels"),
    ("GET",  "api/token"),
    ("GET",  "live"),
    ("GET",  "live/"),
    ("GET",  "playlist"),
    ("GET",  "m3u"),
    ("GET",  "status"),
    ("GET",  "health"),
]

print(f"🔍 Probing Unauthenticated: {WORKER_URL}")
print("=" * 70)

for method, path in endpoints_to_try:
    url = WORKER_URL.rstrip("/") + "/" + path.lstrip("/")
    try:
        resp = session.request(method, url, timeout=10)
        code = resp.status_code
        snippet = resp.text[:120].replace("\n", " ").strip()
        icon = "✅" if code < 300 else ("⚠️" if code < 500 else "❌")
        print(f"  {icon} [{code}] {method:4} /{path:<25}  {snippet}")
    except Exception as e:
        print(f"  💥       {method:4} /{path:<25}  ERROR: {e}")

print("=" * 70)

# Probe Authenticated Endpoints
print("\n🔑 Probing Authenticated Endpoints (Token + VFMFLPzAIv Signature):")
print("-" * 70)
try:
    client = SmIptvClient()
    client.worker_url = WORKER_URL
    token = client.get_token()
    print(f"  ✅ [200] POST /token    token: {token[:25]}... (valid 30m)")

    for ep in ["channels", "sports"]:
        try:
            data = client._auth_request("GET", ep)
            if isinstance(data, dict):
                keys = list(data.keys())
                print(f"  ✅ [200] GET  /{ep:<25}  SUCCESS keys={keys}")
            else:
                print(f"  ✅ [200] GET  /{ep:<25}  SUCCESS len={len(data)}")
        except Exception as e:
            print(f"  ❌ [ERR] GET  /{ep:<25}  ERROR: {e}")
except Exception as e:
    print(f"  ❌ Failed to obtain token: {e}")

print("=" * 70)
