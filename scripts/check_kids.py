#!/usr/bin/env python3
"""Quick script to check Kids category channels from SM IPTV API."""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from sm_iptv_client import SmIptvClient

client = SmIptvClient()

print("🔍 Resolving worker gateway...")
worker = client.get_worker_url()
print(f"   Worker: {worker}")

print("🔑 Getting session token...")
token = client.get_token()
print(f"   Token: {token[:20]}... OK")

print("📡 Fetching all channels...")
data = client.get_channels()

categories = data.get("categories", [])
print(f"\n📂 Total categories found: {len(categories)}")
print("=" * 60)

# Show all categories
for cat in categories:
    name = cat.get("name", "?")
    count = len(cat.get("channels", []))
    marker = " ⬅ KIDS" if "kid" in name.lower() else ""
    print(f"  [{count:3d} channels]  {name}{marker}")

print("=" * 60)

# Now show Kids category in detail
print("\n🧒 KIDS Category — Channel Details:")
print("=" * 60)

kids_cats = [c for c in categories if "kid" in c.get("name", "").lower()]

if not kids_cats:
    print("❌ No Kids category found!")
else:
    for cat in kids_cats:
        name = cat.get("name", "?")
        channels = cat.get("channels", [])
        print(f"\n📁 Category: {name}  ({len(channels)} channels)\n")
        for i, ch in enumerate(channels, 1):
            ch_name = ch.get("name", "Unknown")
            stream = ch.get("stream_url", "N/A")
            logo = ch.get("logo", "")
            drm = " 🔐 DRM" if ch.get("kid") else ""
            print(f"  {i:3}. {ch_name}{drm}")
            print(f"       Stream: {stream[:80]}{'...' if len(stream) > 80 else ''}")
            if logo:
                print(f"       Logo:   {logo[:80]}{'...' if len(logo) > 80 else ''}")
            print()
