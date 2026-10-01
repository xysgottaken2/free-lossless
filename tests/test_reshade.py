"""ReShade support: detection next to the app and the installer download.

The download runs on the user's machine, so it must resolve the current version by
itself (reshade.me only keeps the latest release online) and must refuse to save
anything that is not a Windows executable.
"""
import io
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

import reshade


class FakeResponse(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False


def fake_opener(payload, calls=None):
    def opener(request, timeout=0):
        if calls is not None:
            calls.append((getattr(request, "full_url", request), timeout))
        if isinstance(payload, Exception):
            raise payload
        return FakeResponse(payload)
    return opener


class DetectionTests(unittest.TestCase):
    def test_an_empty_folder_has_no_reshade(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(reshade.detect(directory), [])
            self.assertFalse(reshade.is_installed(directory))

    def test_the_marker_files_are_reported(self):
        with TemporaryDirectory() as directory:
            (Path(directory) / "dxgi.dll").write_bytes(b"MZ")
            (Path(directory) / "ReShade.ini").write_text("", encoding="utf-8")
            (Path(directory) / "outro.dll").write_bytes(b"")
            found = reshade.detect(directory)
            self.assertIn("dxgi.dll", found)
            self.assertIn("ReShade.ini", found)
            self.assertNotIn("outro.dll", found)

    def test_a_folder_that_does_not_exist_is_not_an_error(self):
        self.assertEqual(reshade.detect("/pasta/inexistente"), [])

    def test_the_app_directory_is_where_the_script_lives(self):
        self.assertEqual(reshade.app_directory(), Path(reshade.__file__).resolve().parent)

    def test_the_instructions_name_the_executable(self):
        self.assertIn("FreeLossless.exe", reshade.instructions("FreeLossless.exe"))


class UrlResolutionTests(unittest.TestCase):
    PAGE = """
        <a href="/downloads/ReShade_Setup_6.9.0_Addon.exe">add-on</a>
        <a href="https://reshade.me/downloads/ReShade_Setup_6.9.0.exe">download</a>
    """

    def test_the_current_installer_is_read_from_the_home_page(self):
        url, error = reshade.resolve_installer_url(fake_opener(self.PAGE.encode()))
        self.assertIsNone(error)
        self.assertEqual(url, "https://reshade.me/downloads/ReShade_Setup_6.9.0.exe")

    def test_the_addon_build_is_used_when_it_is_the_only_one(self):
        page = '<a href="/downloads/ReShade_Setup_6.9.0_Addon.exe">add-on</a>'
        url, error = reshade.resolve_installer_url(fake_opener(page.encode()))
        self.assertIsNone(error)
        self.assertTrue(url.endswith("ReShade_Setup_6.9.0_Addon.exe"))
        self.assertTrue(url.startswith("https://reshade.me/"))

    def test_a_page_without_a_link_is_reported(self):
        url, error = reshade.resolve_installer_url(fake_opener(b"<html>nada</html>"))
        self.assertIsNone(url)
        self.assertIn("não listou", error)

    def test_a_network_failure_is_reported_and_not_raised(self):
        url, error = reshade.resolve_installer_url(fake_opener(OSError("sem rede")))
        self.assertIsNone(url)
        self.assertIn("sem rede", error)


class DownloadTests(unittest.TestCase):
    PROGRAM = b"MZ" + b"\x00" * 1_200_000
    URL = "https://reshade.me/downloads/ReShade_Setup_6.9.0.exe"

    def test_the_installer_is_saved_with_its_own_name(self):
        with TemporaryDirectory() as directory:
            path, error = reshade.download_installer(
                directory, opener=fake_opener(self.PROGRAM),
                resolver=lambda: (self.URL, None))
            self.assertIsNone(error)
            self.assertEqual(path.name, "ReShade_Setup_6.9.0.exe")
            self.assertEqual(path.read_bytes()[:2], b"MZ")

    def test_a_truncated_or_wrong_file_is_deleted(self):
        with TemporaryDirectory() as directory:
            path, error = reshade.download_installer(
                directory, opener=fake_opener(b"<html>erro</html>"),
                resolver=lambda: (self.URL, None))
            self.assertIsNone(path)
            self.assertIn("não é um instalador válido", error)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_a_network_failure_leaves_no_file_behind(self):
        with TemporaryDirectory() as directory:
            path, error = reshade.download_installer(
                directory, opener=fake_opener(OSError("caiu")),
                resolver=lambda: (self.URL, None))
            self.assertIsNone(path)
            self.assertIn("caiu", error)
            self.assertEqual(list(Path(directory).iterdir()), [])

    def test_the_resolution_error_is_passed_through(self):
        with TemporaryDirectory() as directory:
            path, error = reshade.download_installer(
                directory, resolver=lambda: (None, "sem link"))
            self.assertIsNone(path)
            self.assertEqual(error, "sem link")

    def test_the_download_goes_to_the_official_host(self):
        calls = []
        with TemporaryDirectory() as directory:
            reshade.download_installer(directory, opener=fake_opener(self.PROGRAM, calls),
                                       resolver=lambda: (self.URL, None))
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][0], self.URL)


class GameFolderTests(unittest.TestCase):
    """Finding ReShade in a game folder, for the menu hint."""

    def test_files_that_show_a_reshade_installation(self):
        with TemporaryDirectory() as directory:
            self.assertEqual(reshade.marker_files(directory), [])
            (Path(directory) / "ReShade.ini").write_text("", encoding="utf-8")
            (Path(directory) / "dxgi.dll").write_bytes(b"")
            (Path(directory) / "reshade-shaders").mkdir()
            found = reshade.marker_files(directory)
            self.assertIn("ReShade.ini", found)
            self.assertIn("dxgi.dll", found)
            self.assertIn("reshade-shaders", found)

    def test_a_missing_folder_or_process_is_not_an_error(self):
        self.assertEqual(reshade.marker_files(None), [])
        self.assertEqual(reshade.marker_files("/pasta/que/nao/existe"), [])
        self.assertEqual(reshade.installed_for_process(None), (None, []))

    def test_looking_up_a_game_that_is_not_running_reports_nothing(self):
        directory, files = reshade.installed_for_process("jogo-que-nao-existe-12345.exe")
        self.assertIsNone(directory)
        self.assertEqual(files, [])


class OpenFolderTests(unittest.TestCase):
    def test_a_failure_to_open_the_folder_is_only_reported(self):
        with patch.object(reshade.os, "system", side_effect=OSError("sem explorer")):
            self.assertFalse(reshade.open_folder("/tmp") or False)


if __name__ == "__main__":
    unittest.main()
