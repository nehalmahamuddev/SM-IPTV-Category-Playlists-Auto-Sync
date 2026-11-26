import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from combine_playlists import build_combined_outputs, combine_sources


def test_combine_deduplicates_identical_urls_and_numbers_distinct_urls():
    sm_channels = [
        {
            "id": "somoy_tv",
            "name": "Somoy TV",
            "category": "bangla",
            "logo": "https://example.com/somoy.png",
            "quality": "HD",
            "servers": [
                {
                    "name": "Server 1 (HD)",
                    "stream_url": "https://stream.example.com/somoy/1.m3u8",
                    "quality": "HD",
                    "headers": {},
                    "drm": None,
                    "sort_order": 1,
                }
            ],
        }
    ]
    toffee_channels = [
        # Same channel, one identical URL (should skip) and one new URL (should become Server 2)
        {
            "id": "toffee_somoy_tv",
            "name": "Somoy TV",
            "category": "toffee",
            "logo": "https://example.com/somoy_toffee.png",
            "quality": "HD",
            "servers": [
                {
                    "name": "Server 1 (Toffee Live)",
                    "stream_url": "https://stream.example.com/somoy/1.m3u8",
                    "quality": "HD",
                    "headers": {},
                    "drm": None,
                    "sort_order": 1,
                },
                {
                    "name": "Server 2 (Toffee Live)",
                    "stream_url": "https://stream.example.com/somoy/2.m3u8",
                    "quality": "FHD",
                    "headers": {"User-Agent": "okhttp/5.1.0"},
                    "drm": None,
                    "sort_order": 2,
                },
            ],
        },
        # Unique Toffee channel -> stays in 'toffee'
        {
            "id": "toffee_toffee_movies",
            "name": "Toffee Movies",
            "category": "toffee",
            "logo": "https://example.com/movies.png",
            "quality": "HD",
            "stream_url": "https://stream.example.com/movies/1.m3u8",
            "headers": {"Host": "toffee.example.com"},
            "drm": None,
        },
    ]

    categories = combine_sources(sm_channels, toffee_channels)

    assert list(categories.keys()) == ["bangla", "toffee"]
    assert len(categories["bangla"]) == 1
    somoy = categories["bangla"][0]
    assert somoy["id"] == "somoy_tv"
    assert somoy["category"] == "bangla"
    assert len(somoy["servers"]) == 2
    assert somoy["servers"][0]["name"] == "Server 1 (HD)"
    assert somoy["servers"][0]["stream_url"] == "https://stream.example.com/somoy/1.m3u8"
    assert somoy["servers"][1]["name"] == "Server 2 (FHD)"
    assert somoy["servers"][1]["stream_url"] == "https://stream.example.com/somoy/2.m3u8"
    assert somoy["servers"][1]["sort_order"] == 2

    assert len(categories["toffee"]) == 1
    assert categories["toffee"][0]["id"] == "toffee_movies"


def test_build_combined_outputs_writes_m3u_and_json(tmp_path):
    sm_path = tmp_path / "channels.json"
    toffee_path = tmp_path / "toffee.json"
    out_dir = tmp_path / "out"

    sm_path.write_text(json.dumps({
        "channels": [
            {
                "id": "t_sports",
                "name": "T Sports",
                "category": "sports",
                "logo": "https://example.com/tsports.png",
                "quality": "HD",
                "servers": [
                    {
                        "name": "Server 1 (HD)",
                        "stream_url": "https://sm.example.com/tsports.m3u8",
                        "quality": "HD",
                        "headers": {},
                        "drm": None,
                        "sort_order": 1,
                    }
                ],
            }
        ]
    }), encoding="utf-8")

    toffee_path.write_text(json.dumps({
        "channels": [
            {
                "id": "toffee_t_sports",
                "name": "T Sports HD",
                "category": "toffee",
                "logo": "",
                "quality": "HD",
                "stream_url": "https://toffee.example.com/tsports.m3u8",
                "headers": {"User-Agent": "okhttp/5.1.0"},
                "drm": None,
            }
        ]
    }), encoding="utf-8")

    m3u_path, json_path, payload = build_combined_outputs(
        channels_json_path=str(sm_path),
        toffee_json_path=str(toffee_path),
        output_dir=str(out_dir),
    )

    assert os.path.exists(m3u_path)
    assert os.path.exists(json_path)
    assert payload["total_categories"] == 1
    assert payload["total_channels"] == 1
    assert payload["total_streams"] == 2
    assert "sports" in payload["categories"]
    assert len(payload["categories"]["sports"][0]["servers"]) == 2

    m3u_text = open(m3u_path, "r", encoding="utf-8").read()
    assert "#EXTM3U" in m3u_text
    assert "T Sports (Server 1 (HD))" in m3u_text
    assert "T Sports (Server 2 (HD))" in m3u_text
    assert "https://sm.example.com/tsports.m3u8" in m3u_text
    assert "https://toffee.example.com/tsports.m3u8" in m3u_text
