#!/usr/bin/env python3
"""Use sm-iptv-sourch bootstrap to get worker URL, then fetch Kids channels."""

import requests, json, time, sys, os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sm_iptv_client import SmIptvClient

BOOTSTRAP = "https://bb.sm-monirul.xyz/cc/exp/"
UA = "okhttp/4.12.0"

session = requests.Session()
session.headers.update({"User-Agent": UA})

# Step 1: Hit bootstrap to get worker URL
print(f"🌐 Hitting bootstrap: {BOOTSTRAP}")
resp = session.get(BOOTSTRAP, timeout=15)
print(f"   Status: {resp.status_code}")
print(f"   Raw response: {resp.text}")
print()

worker_url = resp.json().get("url", "").strip()
if not worker_url.endswith("/"):
    worker_url += "/"
print(f"✅ Worker URL from bootstrap: {worker_url}")
print()

# Step 2: Use this worker URL with the client
client = SmIptvClient(session=session)
client.worker_url = worker_url

print("🔑 Getting session token...")
token = client.get_token()
print(f"   Token: {token[:25]}... OK")
print()

print("📡 Fetching all channels...")
data = client.get_channels()

categories = data.get("categories", [])
print(f"📂 Total categories: {len(categories)}")
print("=" * 65)

for cat in categories:
    name  = cat.get("name", "?")
    count = len(cat.get("channels", []))
    marker = " ⬅ KIDS" if "kid" in name.lower() else ""
    print(f"  [{count:3d} channels]  {name}{marker}")

print("=" * 65)

# Kids detail
kids_cats = [c for c in categories if "kid" in c.get("name", "").lower()]
print(f"\n🧒 KIDS Category — Full Channel List:")
print("=" * 65)

if not kids_cats:
    print("❌ No Kids category found!")
else:
    for cat in kids_cats:
        name     = cat.get("name", "?")
        channels = cat.get("channels", [])
        print(f"\n📁 \"{name}\"  →  {len(channels)} channels\n")
        for i, ch in enumerate(channels, 1):
            ch_name = ch.get("name", "Unknown")
            stream  = ch.get("stream_url", "N/A")
            logo    = ch.get("logo", "")
            drm     = " 🔐 DRM" if ch.get("kid") else ""
            ua      = ch.get("user_agent", "")
            referer = ch.get("referer", "")
            origin  = ch.get("origin", "")
            print(f"  {i:3}. {ch_name}{drm}")
            print(f"       Stream : {stream}")
            if logo:    print(f"       Logo   : {logo}")
            if ua:      print(f"       UA     : {ua}")
            if referer: print(f"       Referer: {referer}")
            if origin:  print(f"       Origin : {origin}")
            print()
