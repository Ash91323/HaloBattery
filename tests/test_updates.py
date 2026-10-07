import io
import json
import unittest
import urllib.error
from unittest import mock

import updates


class ForkUpdatesTests(unittest.TestCase):
    def test_source_migration_discards_upstream_cache_and_keeps_preferences(self):
        cfg = dict(language="zh-TW", update_check=False, names={"a": "我的鍵盤"},
                   update_latest="1.14.0", update_url="https://github.com/HeyOkay/HaloBattery/releases/tag/v1.14.0",
                   update_notified="1.14.0", update_last=12345)
        self.assertTrue(updates.migrate_source(cfg))
        self.assertEqual(cfg, dict(language="zh-TW", update_check=False,
                                   names={"a": "我的鍵盤"}, update_repo=updates.REPO))
        cfg["update_latest"] = "1.15.0"
        self.assertFalse(updates.migrate_source(cfg))
        self.assertEqual(cfg["update_latest"], "1.15.0")

    def test_fetch_uses_personal_fork_and_constructs_its_release_link(self):
        payload = dict(tag_name="v1.15.0", html_url="https://github.com/HeyOkay/HaloBattery/releases/tag/v1.15.0")
        with mock.patch.object(updates.urllib.request, "urlopen",
                               return_value=io.BytesIO(json.dumps(payload).encode())) as fetch:
            version, url = updates.fetch_latest("1.13.0")
        self.assertEqual(fetch.call_args.args[0].full_url,
                         "https://api.github.com/repos/Ash91323/HaloBattery/releases/latest")
        self.assertEqual((version, url), ("1.15.0", "https://github.com/Ash91323/HaloBattery/releases/tag/v1.15.0"))
        self.assertTrue(updates.is_newer(version, "1.13.0"))

    def test_fork_without_a_release_has_no_update(self):
        error = urllib.error.HTTPError(updates.API_URL, 404, "Not Found", {}, None)
        with mock.patch.object(updates.urllib.request, "urlopen", side_effect=error):
            version, url = updates.fetch_latest("1.13.0")
        self.assertFalse(updates.is_newer(version, "1.13.0"))
        self.assertEqual(url, updates.RELEASES_URL)

    def test_rate_limit_still_propagates_for_retry(self):
        error = urllib.error.HTTPError(updates.API_URL, 403, "Forbidden", {}, None)
        with mock.patch.object(updates.urllib.request, "urlopen", side_effect=error):
            with self.assertRaises(urllib.error.HTTPError):
                updates.fetch_latest("1.13.0")
