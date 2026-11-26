import os
import json
import tempfile
import pytest

from scripts.sync_sm_edge import (
    generate_signature,
    slugify_category,
    format_channel_m3u,
    build_playlists
)


def test_generate_signature():
    ts = "1710000000"
    sig = generate_signature(ts, secret=b"key")
    assert len(sig) == 64
    assert all(c in "0123456789abcdef" for c in sig)


def test_slugify_category():
    assert slugify_category("Kids") == "kids"
    assert slugify_category("Bangla") == "bangla"
    assert slugify_category("Indian Bangla") == "indian_bangla"
    assert slugify_category("𝐌𝐮𝐬𝐢𝐜") == "music"
    assert slugify_category("M IPTV") == "m_iptv"


def test_format_channel_m3u_standard():
    ch = {
        "id": 150,
        "name": "Durunto",
        "logo": "https://example.com/durunto.png",
        "stream_url": "http://example.com/durunto/index.m3u8"
    }
    lines = format_channel_m3u(ch, "Kids")
    assert len(lines) == 2
    assert '#EXTINF:-1 tvg-id="150" tvg-name="Durunto" tvg-logo="https://example.com/durunto.png" group-title="Kids",Durunto' in lines[0]
    assert lines[1] == "http://example.com/durunto/index.m3u8"


def test_format_channel_m3u_with_drm():
    ch = {
        "id": 78,
        "name": "Fancode",
        "logo": "https://example.com/fancode.png",
        "stream_url": "https://example.com/dash/cenc.mpd",
        "kid": "82dfca238e8c4b430a3269db71965db9",
        "key": "a00b28caf4ac628e77a553d440c0ddca"
    }
    lines = format_channel_m3u(ch, "Sports")
    assert any("org.w3.clearkey" in l for l in lines)
    assert any("82dfca238e8c4b430a3269db71965db9:a00b28caf4ac628e77a553d440c0ddca" in l for l in lines)
    assert lines[-1] == "https://example.com/dash/cenc.mpd"


def test_build_playlists():
    sample_data = {
        "app_name": "SM IPTV",
        "developed_by": "Monirul Islam",
        "categories": [
            {
                "name": "Kids",
                "channels": [
                    {
                        "id": 150,
                        "name": "Durunto",
                        "logo": "https://example.com/durunto.png",
                        "stream_url": "http://example.com/durunto/index.m3u8"
                    }
                ]
            }
        ]
    }
    with tempfile.TemporaryDirectory() as tmp_dir:
        catalog = build_playlists(sample_data, output_dir=tmp_dir)
        assert catalog["total_channels"] == 1
        assert catalog["total_categories"] == 1
        assert os.path.exists(os.path.join(tmp_dir, "kids.m3u"))
        assert os.path.exists(os.path.join(tmp_dir, "all.m3u"))
        assert os.path.exists(os.path.join(tmp_dir, "categories.json"))
