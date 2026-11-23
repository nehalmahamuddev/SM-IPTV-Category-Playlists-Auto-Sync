#!/usr/bin/env python3
"""Check Kids category using a specific worker URL directly."""

import sys, os, time
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sm_iptv_client import SmIptvClient

WORKER_URL = os.environ.get("SM_WORKER_URL", "https://ck.sm-monirulislam-exp.workers.dev/")

client = SmIptvClient()

# Force use the specific worker URL directly (bypass bootstrap)
client.worker_url = WORKER_URL
print(f"🔧 Using worker URL directly: {WORKER_URL}")

print("🔑 Getting session token...")
token = client.get_token()
print(f"   Token: {token[:25]}... OK")

print("📡 Fetching all channels...")
data = client.get_channels()

categories = data.get("categories", [])
print(f"\n📂 Total categories found: {len(categories)}")
print("=" * 65)

for cat in categories:
    name = cat.get("name", "?")
    count = len(cat.get("channels", []))
    marker = " ⬅ KIDS" if "kid" in name.lower() else ""
    print(f"  [{count:3d} channels]  {name}{marker}")

print("=" * 65)

# Kids detail
print("\n🧒 KIDS Category — Full Channel List:")
print("=" * 65)

kids_cats = [c for c in categories if "kid" in c.get("name", "").lower()]

if not kids_cats:
    print("❌ No Kids category found!")
else:
    for cat in kids_cats:
        name = cat.get("name", "?")
        channels = cat.get("channels", [])
        print(f"\n📁 Category: \"{name}\"  →  {len(channels)} channels\n")
        for i, ch in enumerate(channels, 1):
            ch_name   = ch.get("name", "Unknown")
            stream    = ch.get("stream_url", "N/A")
            logo      = ch.get("logo", "")
            drm       = " 🔐 DRM" if ch.get("kid") else ""
            ua        = ch.get("user_agent", "")
            referer   = ch.get("referer", "")
            print(f"  {i:3}. {ch_name}{drm}")
            print(f"       Stream : {stream}")
            if logo:
                print(f"       Logo   : {logo}")
            if ua:
                print(f"       UA     : {ua}")
            if referer:
                print(f"       Ref    : {referer}")
            print()
