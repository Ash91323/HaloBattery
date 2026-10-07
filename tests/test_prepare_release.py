from pathlib import Path
import tempfile
import unittest

from tools.prepare_release import next_version, prepare


class ReleaseTests(unittest.TestCase):
    def test_auto_increment_uses_highest_stable_tag(self):
        self.assertEqual(next_version("1.13.0", []), "1.13.1")
        self.assertEqual(next_version("1.13.0", ["v1.13.8", "v1.13.9", "v9.0.0-beta"]), "1.13.10")
        self.assertEqual(next_version("2.0.0", ["v1.13.9"]), "2.0.1")
        self.assertEqual(next_version("1.13.0", ["v1.13.65535"]), "1.14.0")

    def fixture(self, root):
        (root / "halo_battery.pyw").write_text('VERSION = "1.13.0"\n', encoding="utf-8")
        (root / "CHANGELOG.md").write_text('## [Unreleased]\n\n- 繁體中文\n\n## [1.13.0]\n\nOld notes\n', encoding="utf-8")

    def test_main_build_versions_executable_and_notes_together(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            result = prepare(root, "branch", "main", ["v1.13.2"], "abcd123")
            self.assertEqual(result, dict(version="1.13.3", tag="v1.13.3", publish="true"))
            self.assertIn('VERSION = "1.13.3"', (root / "halo_battery.pyw").read_text())
            notes = (root / "release_notes.md").read_text(encoding="utf-8")
            self.assertIn("繁體中文", notes)
            self.assertIn("abcd123", notes)
            self.assertNotIn("Old notes", notes)

    def test_other_branches_only_build_and_tag_must_match(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            self.fixture(root)
            self.assertEqual(prepare(root, "branch", "feature", [], "abc")["publish"], "false")
            self.assertEqual(prepare(root, "tag", "v1.13.0", [], "abc")["version"], "1.13.0")
            with self.assertRaises(ValueError):
                prepare(root, "tag", "v1.14.0", [], "abc")
