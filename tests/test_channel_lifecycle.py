import os
import json
import tempfile
import pytest

from scripts.generate_category_playlists import prune_orphan_playlists
from scripts.refine_playlists import discover_categories, prune_orphan_output_playlists


def test_prune_orphan_playlists():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # Create test files
        active_file = os.path.join(tmp_dir, "sports.m3u")
        orphan_file = os.path.join(tmp_dir, "old_category.m3u")
        master_file = os.path.join(tmp_dir, "all.m3u")
        toffee_file = os.path.join(tmp_dir, "toffee.m3u")
        readme_file = os.path.join(tmp_dir, "README.md")

        for fpath in [active_file, orphan_file, master_file, toffee_file, readme_file]:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")

        # Prune with active set containing only sports.m3u
        prune_orphan_playlists(tmp_dir, {"sports.m3u"})

        # Assertions
        assert os.path.exists(active_file)
        assert os.path.exists(master_file)
        assert os.path.exists(toffee_file)
        assert os.path.exists(readme_file)
        assert not os.path.exists(orphan_file)


def test_discover_categories_from_json():
    with tempfile.TemporaryDirectory() as tmp_dir:
        cat_json = os.path.join(tmp_dir, "categories.json")
        sample_meta = {
            "categories": [
                {"name": "Bangla", "slug": "bangla", "filename": "bangla.m3u"},
                {"name": "Sports", "slug": "sports", "filename": "sports.m3u"},
                {"name": "New Category", "slug": "new_cat", "filename": "new_cat.m3u"}
            ]
        }
        with open(cat_json, "w", encoding="utf-8") as f:
            json.dump(sample_meta, f)

        discovered = discover_categories(tmp_dir)
        assert len(discovered) == 3
        assert discovered[0] == ("bangla.m3u", "bangla", "Bangla")
        assert discovered[2] == ("new_cat.m3u", "new_cat", "New Category")


def test_discover_categories_fallback_scan():
    with tempfile.TemporaryDirectory() as tmp_dir:
        # No categories.json, create direct .m3u files
        for name in ["bangla.m3u", "sports.m3u", "all.m3u", "toffee.m3u"]:
            with open(os.path.join(tmp_dir, name), "w", encoding="utf-8") as f:
                f.write("#EXTM3U\n")

        discovered = discover_categories(tmp_dir)
        # all.m3u and toffee.m3u must be excluded
        filenames = [item[0] for item in discovered]
        assert "bangla.m3u" in filenames
        assert "sports.m3u" in filenames
        assert "all.m3u" not in filenames
        assert "toffee.m3u" not in filenames


def test_prune_orphan_output_playlists():
    with tempfile.TemporaryDirectory() as tmp_dir:
        active_out = os.path.join(tmp_dir, "bangla.m3u")
        orphan_out = os.path.join(tmp_dir, "obsolete.m3u")
        master_out = os.path.join(tmp_dir, "all.m3u")
        channels_json = os.path.join(tmp_dir, "channels.json")

        for fpath in [active_out, orphan_out, master_out, channels_json]:
            with open(fpath, "w", encoding="utf-8") as f:
                f.write("content\n")

        prune_orphan_output_playlists(tmp_dir, {"bangla.m3u"})

        assert os.path.exists(active_out)
        assert os.path.exists(master_out)
        assert os.path.exists(channels_json)
        assert not os.path.exists(orphan_out)
