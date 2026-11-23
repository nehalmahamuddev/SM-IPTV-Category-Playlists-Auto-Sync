import pytest
from scripts.sync_toffee import (
    slugify_channel_name,
    normalize_toffee_channel,
    deduplicate_channels,
    format_m3u_entry
)


def test_slugify_channel_name():
    assert slugify_channel_name("Toffee TV") == "toffee_toffee_tv"
    assert slugify_channel_name("Somoy TV") == "toffee_somoy_tv"
    assert slugify_channel_name("9X Tashan") == "toffee_9x_tashan"
    assert slugify_channel_name("Channel 24 (HD)") == "toffee_channel_24_hd"
    assert slugify_channel_name("  DBC News   ") == "toffee_dbc_news"


def test_normalize_toffee_channel():
    raw_item = {
        "category_name": "Family",
        "name": "Toffee TV",
        "link": "https://prod-linear-media.toffeelive.com/cdn/live/toffee_drama/playlist.m3u8?token=123",
        "headers": {
            "Host": "prod-linear-media.toffeelive.com",
            "user-agent": "okhttp/5.1.0"
        },
        "logo": "https://assets-prod.services.toffeelive.com/poster.png"
    }

    norm = normalize_toffee_channel(raw_item, sort_order=1)

    assert norm["id"] == "toffee_toffee_tv"
    assert norm["name"] == "Toffee TV"
    assert norm["category"] == "toffee"
    assert norm["country"] == "BD"
    assert norm["language"] == "bn"
    assert norm["is_live"] is True
    assert norm["quality"] == "HD"
    assert norm["stream_url"] == raw_item["link"]
    assert norm["headers"]["user-agent"] == "okhttp/5.1.0"
    assert norm["sort_order"] == 1
    assert len(norm["servers"]) == 1
    assert norm["servers"][0]["name"] == "Server 1 (Toffee Live)"
    assert norm["servers"][0]["scheme"] == 0
    assert norm["servers"][0]["active"] is True


def test_deduplicate_channels():
    channels = [
        {"id": "toffee_sports", "name": "Sports"},
        {"id": "toffee_sports", "name": "Sports 2"}
    ]
    deduped = deduplicate_channels(channels)
    assert deduped[0]["id"] == "toffee_sports"
    assert deduped[1]["id"] == "toffee_sports_2"


def test_format_m3u_entry():
    channel = {
        "id": "toffee_toffee_tv",
        "name": "Toffee TV",
        "logo": "https://assets-prod.services.toffeelive.com/poster.png",
        "category": "toffee",
        "stream_url": "https://prod-linear-media.toffeelive.com/cdn/live/toffee_drama/playlist.m3u8",
        "headers": {
            "user-agent": "okhttp/5.1.0",
            "Host": "prod-linear-media.toffeelive.com"
        }
    }
    entry = format_m3u_entry(channel)
    assert "#EXTINF:-1" in entry
    assert 'group-title="Toffee"' in entry
    assert 'tvg-name="Toffee TV"' in entry
    assert "#EXTVLCOPT:http-user-agent=okhttp/5.1.0" in entry
    assert "https://prod-linear-media.toffeelive.com/cdn/live/toffee_drama/playlist.m3u8" in entry
