import hashlib
import io
import json
from pathlib import Path
import tempfile
import types
import unittest
from unittest import mock
import zipfile

import updater as U
from test_hide_rename import hb, make_app


class UpdaterTests(unittest.TestCase):
    def archive(self, files):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as package:
            for name, body in files:
                if isinstance(name, str) and "\\" in name:
                    info = zipfile.ZipInfo()
                    info.filename = name  # bypass Windows ZipInfo normalization
                    name = info
                package.writestr(name, body)
        stream.seek(0)
        return stream

    def test_extract_preserves_bundle_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            destination = Path(folder) / "package"
            U.extract_package(self.archive([("HaloBattery/HaloBattery.exe", b"MZapp"),
                                            ("HaloBattery/_internal/library.dll", b"dll")]), destination)
            self.assertEqual((destination / "HaloBattery.exe").read_bytes(), b"MZapp")
            self.assertEqual((destination / "_internal/library.dll").read_bytes(), b"dll")

    def test_reject_traversal_ads_settings_duplicates_and_incomplete_packages(self):
        good = [("HaloBattery/HaloBattery.exe", b"MZapp"), ("HaloBattery/_internal/library.dll", b"dll")]
        for name in ("HaloBattery/../outside", "HaloBattery/_internal/../../outside", "/absolute",
                     "HaloBattery/_internal/x:stream", "HaloBattery/_internal/trailing. ",
                     "HaloBattery/config.json", "HaloBattery\\_internal\\bad", "HaloBattery/halobattery.EXE"):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as folder:
                with self.assertRaises(ValueError):
                    U.extract_package(self.archive(good + [(name, b"bad")]), Path(folder) / "out")
        with tempfile.TemporaryDirectory() as folder, self.assertRaises(ValueError):
            U.extract_package(self.archive(good[:1]), Path(folder) / "out")

    def test_reject_symlink_and_oversized_archive(self):
        link = zipfile.ZipInfo("HaloBattery/_internal/link")
        link.external_attr = 0o120777 << 16
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):
                U.extract_package(self.archive([(link, b"target")]), Path(folder) / "out")
            with mock.patch.object(U, "MAX_UNPACKED", 1), self.assertRaises(ValueError):
                U.extract_package(self.archive([("HaloBattery/HaloBattery.exe", b"MZapp")]), Path(folder) / "out")

    def test_download_verifies_digest_size_and_redirect_host(self):
        content = b"a verified release"
        digest = hashlib.sha256(content).hexdigest()
        with tempfile.TemporaryDirectory() as folder:
            for expected, size, host, valid in [(digest, len(content), "https://release-assets.githubusercontent.com/x", True),
                                               ("0" * 64, len(content), "https://github.com/x", False),
                                               (digest, 2, "https://github.com/x", False),
                                               (digest, len(content), "https://example.com/x", False)]:
                response = io.BytesIO(content)
                response.geturl = lambda: host
                with mock.patch.object(U.urllib.request, "urlopen", return_value=response):
                    if valid:
                        U.download("https://github.com/x", expected, size, Path(folder) / "zip")
                    else:
                        with self.assertRaises(ValueError):
                            U.download("https://github.com/x", expected, size, Path(folder) / "zip")

    def test_release_asset_is_bound_to_repo_version_and_digest(self):
        url = f"https://github.com/{U.updates.REPO}/releases/download/v1.15.0/HaloBattery-1.15.0.zip"
        asset = dict(name="HaloBattery-1.15.0.zip", state="uploaded", size=100,
                     browser_download_url=url, digest="sha256:" + "a" * 64)
        for change, good in [({}, True), ({"digest": None}, False),
                             ({"browser_download_url": url.replace("Ash91323", "HeyOkay")}, False),
                             ({"size": U.MAX_DOWNLOAD + 1}, False), ({"state": "new"}, False)]:
            response = io.BytesIO(json.dumps(dict(tag_name="v1.15.0", assets=[dict(asset, **change)])).encode())
            with mock.patch.object(U.urllib.request, "urlopen", return_value=response):
                if good:
                    self.assertEqual(U.read_release("1.15.0"), (url, "a" * 64, 100))
                else:
                    with self.assertRaises(ValueError):
                        U.read_release("1.15.0")

    def bundle(self, folder, version):
        folder.mkdir()
        (folder / "HaloBattery.exe").write_bytes(b"MZ" + version)
        (folder / "_internal").mkdir()
        (folder / "_internal/library.dll").write_bytes(version)

    def test_install_replaces_app_and_preserves_portable_settings(self):
        with tempfile.TemporaryDirectory() as folder:
            target, package = Path(folder) / "app", Path(folder) / "new"
            self.bundle(target, b"old")
            self.bundle(package, b"new")
            for name in ("portable.txt", "config.json", "history.json"):
                (target / name).write_text("preserve", encoding="utf-8")
            launch = mock.Mock(return_value=types.SimpleNamespace(poll=lambda: None))
            with mock.patch.object(U.time, "sleep"):
                backup = U.install_files(package, target, launch)
            self.assertEqual((target / "_internal/library.dll").read_bytes(), b"new")
            self.assertEqual((backup / "HaloBattery.exe").read_bytes(), b"MZold")
            for name in ("portable.txt", "config.json", "history.json"):
                self.assertEqual((target / name).read_text(), "preserve")
            launch.assert_called_once_with((target / "HaloBattery.exe").resolve())

    def test_startup_failure_restores_both_old_paths_and_restarts(self):
        with tempfile.TemporaryDirectory() as folder:
            target, package = Path(folder) / "app", Path(folder) / "new"
            self.bundle(target, b"old")
            self.bundle(package, b"new")
            launch = mock.Mock(return_value=types.SimpleNamespace(poll=lambda: 1))
            with mock.patch.object(U.time, "sleep"), self.assertRaises(RuntimeError):
                U.install_files(package, target, launch)
            self.assertEqual((target / "HaloBattery.exe").read_bytes(), b"MZold")
            self.assertEqual((target / "_internal/library.dll").read_bytes(), b"old")
            self.assertEqual(launch.call_count, 2)

    def test_partial_replacement_failure_restores_old_paths(self):
        with tempfile.TemporaryDirectory() as folder:
            target, package = Path(folder) / "app", Path(folder) / "new"
            self.bundle(target, b"old")
            self.bundle(package, b"new")
            replace = U.os.replace
            def fail(source, dest):
                if Path(source).resolve() == (target / "_internal").resolve():
                    raise PermissionError("locked DLL")
                return replace(source, dest)
            with mock.patch.object(U.os, "replace", side_effect=fail), self.assertRaises(PermissionError):
                U.install_files(package, target, mock.Mock())
            self.assertEqual((target / "HaloBattery.exe").read_bytes(), b"MZold")
            self.assertEqual((target / "_internal/library.dll").read_bytes(), b"old")

    def test_download_failure_does_not_quit_running_app(self):
        app = make_app()
        with mock.patch.object(hb.updater, "prepare", side_effect=ValueError("bad checksum")), \
                mock.patch.object(app, "notify_any") as notify, mock.patch.object(app, "quit") as quit_app:
            app._install_update("1.15.0")
            quit_app.assert_not_called()
            notify.assert_called_once()
            self.assertFalse(app._update_busy)

    def test_helper_is_ready_before_app_quits(self):
        app = make_app()
        app.stop_evt = types.SimpleNamespace(is_set=lambda: False)
        order = []
        with mock.patch.object(hb.updater, "prepare", return_value="work"), \
                mock.patch.object(hb.updater, "start_helper", side_effect=lambda work: order.append("ready")), \
                mock.patch.object(app, "quit", side_effect=lambda: order.append("quit")):
            app._install_update("1.15.0")
        self.assertEqual(order, ["ready", "quit"])
