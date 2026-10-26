"""Integration tests for the actual Azahar C++ transport and TitleReader."""
import os
import subprocess
import struct
import unittest
import tempfile
from pathlib import Path

from test_dock_probe import FakeConsole

PROBE = os.environ.get("ARTIC_NATIVE_PROBE")
CORE_PROBE = os.environ.get("ARTIC_CORE_PROBE")
os.environ.setdefault("ARTIC_DISABLE_DISK_CACHE", "1")
os.environ.setdefault("ARTIC_DISABLE_PREFETCH", "1")


@unittest.skipUnless(PROBE, "Set ARTIC_NATIVE_PROBE to the compiled native probe")
class NativeTitleReaderTests(unittest.TestCase):
    def run_probe(self, server):
        return subprocess.run([PROBE, "127.0.0.1", "0004000000123400", "1", "icon", str(server.port)],
                              text=True, capture_output=True, timeout=15)

    def test_reads_selected_title_and_whole_exefs_section(self):
        with FakeConsole() as server:
            result = self.run_probe(server)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("exheader_bytes=1024 section_bytes=14016", result.stdout)
        self.assertEqual(server.requests.count("FSFILE_Close"), 1)

    def test_rejects_metadata_for_different_title(self):
        with FakeConsole() as server:
            server.wrong_title = True
            result = self.run_probe(server)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("exheader_bytes=0", result.stdout)
        self.assertEqual(server.requests[-1], "$STOP")

    def test_rejects_incomplete_exefs_and_closes_handle(self):
        with FakeConsole() as server:
            server.truncate_icon = True
            result = self.run_probe(server)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("section_bytes=0", result.stdout)
        self.assertEqual(server.requests.count("FSFILE_Close"), 1)

    def test_rejects_oversized_exefs_without_allocating_or_reading_it(self):
        with FakeConsole() as server:
            server.icon_size = 1 << 32
            result = self.run_probe(server)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("FSFILE_Read", server.requests)
        self.assertEqual(server.requests.count("FSFILE_Close"), 1)

    def test_preserves_console_open_error(self):
        with FakeConsole() as server:
            server.open_error = -0x377FB9C9
            result = self.run_probe(server)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertIn("open_error=c8804637", result.stdout)
        self.assertNotIn("FSFILE_Close", server.requests)

    def run_home(self, server):
        return subprocess.run([PROBE, "127.0.0.1", "0004003000008202", "0", "--home-romfs", str(server.port)],
                              text=True, capture_output=True, timeout=15)

    def test_reads_home_romfs_in_ranges_and_extracts_level_three(self):
        with FakeConsole() as server:
            result = self.run_home(server)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("section_bytes=64", result.stdout)
        self.assertEqual(server.requests.count("Title_ReadHomeRomFS"), 2)

    def test_rejects_invalid_home_romfs_and_transport_sizes(self):
        for case in ("magic", "range", "short", "oversized"):
            with self.subTest(case=case), FakeConsole() as server:
                if case == "magic":
                    server.romfs_image[0] = 0
                elif case == "range":
                    server.romfs_image[0x1004:0x1008] = b"\xff" * 4
                elif case == "short":
                    server.romfs_truncate = True
                else:
                    server.romfs_size_override = 1 << 32
                result = self.run_home(server)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertIn("section_bytes=0", result.stdout)
            self.assertEqual(server.requests[-1], "$STOP")

    def test_streams_small_samples_of_large_romfs_without_loading_whole_file(self):
        with FakeConsole() as server:
            server.romfs_size_override = 1 << 32
            struct.pack_into("<Q", server.romfs_image, 0x44, 1 << 31)
            result = subprocess.run([PROBE, "127.0.0.1", "0004000000123400", "1",
                                     "--stream-romfs", str(server.port)], text=True,
                                    capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stream_size=2147483648 sample_bytes=40", result.stdout)
        self.assertEqual(server.requests.count("Title_ReadRomFS"), 2)

    def test_reads_present_and_absent_gamecard_without_opening_its_content(self):
        for present in (False, True):
            with self.subTest(present=present), FakeConsole() as server:
                server.gamecard_present = present
                result = subprocess.run([PROBE, "127.0.0.1", "0004000000123400", "1",
                                         "--card", str(server.port)], text=True,
                                        capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn("card_title=" + ("4000000197100" if present else "0"), result.stdout)
            self.assertNotIn("FSUSER_OpenFileDirectly", server.requests)


@unittest.skipUnless(CORE_PROBE, "Set ARTIC_CORE_PROBE to the full-core session probe")
class CoreSessionTests(unittest.TestCase):
    def test_cartridge_changes_and_network_error_have_distinct_status(self):
        with FakeConsole() as server:
            server.gamecard_sequence = [0x0004000000197100, None, "error", 0x0004000000055D00, "absent_error"]
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--card-status"],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(server.requests.count("AM_GetTitleCount"), 5)
        self.assertEqual(server.requests.count("AM_GetTitleList"), 2)
        self.assertEqual(server.requests[-1], "$STOP")

    def test_extdata_backup_before_write_and_failure_blocks_writes(self):
        for broken in (False, True):
            with self.subTest(broken=broken), tempfile.TemporaryDirectory() as profile, FakeConsole() as server:
                server.save_listing_bad = broken
                server.save_listing_zero_size = True
                env = dict(os.environ, ARTIC_TEST_USER_DIR=profile)
                result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--extdata-route"],
                                        text=True, capture_output=True, timeout=30, env=env)
                self.assertEqual(result.returncode, int(broken), result.stdout + result.stderr)
                complete = list((Path(profile) / "dock-extdata-backups").rglob("backup-complete.txt"))
                self.assertEqual(len(complete), int(not broken))
                if not broken: self.assertEqual((complete[0].parent / "main").read_bytes(), b"SAVE")
            self.assertEqual(server.requests.count("FSUSER_OpenArchive"), 1)
            if broken: self.assertNotIn("FSFILE_Write", server.requests)
            else:
                self.assertEqual(server.save_data, b"OKAY")
                self.assertLess(server.requests.index("FSFILE_Read"), server.requests.index("FSFILE_Write"))
            self.assertNotIn("FSUSER_CreateExtSaveData", server.requests)
            self.assertNotIn("FSUSER_DeleteExtSaveData", server.requests)

    def test_registered_code_size_above_limit_is_rejected_before_transfer(self):
        with FakeConsole() as server:
            server.registered_code_size = 16 * 1024 * 1024 + 1
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--large-code"],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertNotIn("Title_ReadCodeChunk", server.requests)
        self.assertNotIn("FSFILE_Read", server.requests)
        self.assertEqual(server.requests.count("FSFILE_Close"), 1)

    def test_base_and_update_romfs_use_separate_cached_content(self):
        with tempfile.TemporaryDirectory() as cache, FakeConsole() as server:
            server.update_romfs_image = bytearray(server.romfs_image)
            server.update_romfs_image[-1] = 7
            env = dict(os.environ, ARTIC_DISABLE_DISK_CACHE="0", ARTIC_ROMFS_CACHE_DIR=cache)
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--update-romfs"],
                                    text=True, capture_output=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(len(list(Path(cache).rglob("*.page"))), 2)
        self.assertEqual(server.requests.count("Title_ReadRomFS"), 3)
        self.assertEqual(server.requests.count("Title_ReadUpdateRomFS"), 3)
        self.assertEqual(server.requests[-1], "$STOP")

    def test_large_code_is_complete_and_short_chunk_is_rejected(self):
        for truncate in (False, True):
            with self.subTest(truncate=truncate), FakeConsole() as server:
                server.registered_code_size = 5 * 1024 * 1024 + 17
                server.fragment_size = 4096
                server.code_truncate = truncate
                result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--large-code"],
                                        text=True, capture_output=True, timeout=30)
            self.assertEqual(result.returncode, int(truncate), result.stdout + result.stderr)
            self.assertEqual(server.requests.count("Title_ReadCodeChunk"), 1 if truncate else 6)
            self.assertNotIn("FSFILE_Read", server.requests)
            self.assertEqual(server.requests.count("FSFILE_Close"), 1)
            self.assertEqual(server.requests[-1], "$STOP")

    def test_save_targets_selected_title_and_backs_up_before_write(self):
        with tempfile.TemporaryDirectory() as profile, FakeConsole() as server:
            env = dict(os.environ, ARTIC_TEST_USER_DIR=profile)
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--save-route"],
                                    text=True, capture_output=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            backups = list(Path(profile).rglob("backup-complete.txt"))
            self.assertEqual(len(backups), 1)
            self.assertEqual((backups[0].parent / "main").read_bytes(), b"SAVE")
        self.assertEqual(server.save_data, b"OKAY")
        self.assertLess(server.requests.index("FSFILE_Read"), server.requests.index("FSFILE_Write"))
        self.assertEqual(server.requests.count("FSUSER_ControlArchive"), 1)

    def test_save_backup_failure_prevents_console_writes(self):
        with tempfile.TemporaryDirectory() as profile, FakeConsole() as server:
            server.save_listing_bad = True
            env = dict(os.environ, ARTIC_TEST_USER_DIR=profile)
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--save-route"],
                                    text=True, capture_output=True, timeout=30, env=env)
            self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
            self.assertEqual(list(Path(profile).rglob("backup-complete.txt")), [])
        self.assertNotIn("FSFILE_Write", server.requests)

    def test_home_layout_reads_both_archives_without_writing(self):
        with FakeConsole() as server:
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--home-layout"],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("home_sd_layout=1 home_nand_layout=1", result.stdout)
        self.assertEqual(server.requests.count("FSUSER_CloseArchive"), 2)
        self.assertEqual(server.requests.count("FSFILE_Close"), 2)
        self.assertFalse(any("Write" in method or "Create" in method for method in server.requests))

    def test_home_layout_rejects_unexpected_size_and_closes_handles(self):
        with FakeConsole() as server:
            server.layout_bad_size = True
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--home-layout"],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(server.requests.count("FSUSER_CloseArchive"), 1)
        self.assertEqual(server.requests.count("FSFILE_Close"), 1)

    def test_large_streaming_read_uses_one_request_and_caches_complete_pages(self):
        with FakeConsole() as server:
            size = 4 * 65536 + 103
            server.romfs_image = server.romfs_image[:0x1000] + bytearray(i % 251 for i in range(size))
            struct.pack_into("<Q", server.romfs_image, 0x44, size)
            struct.pack_into("<10I", server.romfs_image, 0x1000,
                             0x28, 0x28, 0, 0x28, 0, 0x28, 0, 0x28, 0, 0x28)
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--romfs-batch"],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("coalesced_read=1 trailing_page_complete=1", result.stdout)
        self.assertEqual(server.requests.count("Title_ReadRomFS"), 2)

    def test_ncch_icon_accepts_unspecified_media_upper_bytes(self):
        with FakeConsole() as server:
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--ncch-media"],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("ncch_media_low_byte=1 buffered_icon=1", result.stdout)
        self.assertIn("region_setting_respected=1", result.stdout)
        self.assertEqual(server.requests.count("FSFILE_Close"), 2)
        self.assertEqual(server.requests[-1], "$STOP")

    def test_streaming_backend_cache_and_eof_bounds(self):
        with FakeConsole() as server:
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--romfs-cache"],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("stream_cache_reused=1 eof_bounded=1", result.stdout)
        self.assertEqual(server.requests.count("Title_ReadRomFS"), 3)
        self.assertEqual(server.requests.count("$STOP"), 1)

    def test_disk_cache_survives_restart_and_rejects_corruption(self):
        with tempfile.TemporaryDirectory() as cache:
            env = dict(os.environ, ARTIC_DISABLE_DISK_CACHE="0",
                       ARTIC_ROMFS_CACHE_DIR=cache)
            def run(expected, version=0):
                with FakeConsole() as server:
                    server.romfs_image[0x90] = version
                    result = subprocess.run(
                        [CORE_PROBE, "127.0.0.1", str(server.port), "--romfs-cache"],
                        text=True, capture_output=True, timeout=30, env=env)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                self.assertEqual(server.requests.count("Title_ReadRomFS"), expected)
            run(2)
            run(1)
            pages = list(Path(cache).rglob("*.page"))
            self.assertEqual(len(pages), 1)
            data = bytearray(pages[0].read_bytes())
            data[-1] ^= 1
            pages[0].write_bytes(data)
            run(2)
            run(1)
            run(2, version=1)
            run(1, version=1)
            self.assertEqual(len(list(Path(cache).rglob("*.page"))), 2)

    def test_background_prefetch_reads_next_page_and_shuts_down(self):
        with FakeConsole() as server:
            size = 4 * 65536 + 103
            server.romfs_image = server.romfs_image[:0x1000] + bytearray(i % 251 for i in range(size))
            struct.pack_into("<Q", server.romfs_image, 0x44, size)
            struct.pack_into("<10I", server.romfs_image, 0x1000,
                             0x28, 0x28, 0, 0x28, 0, 0x28, 0, 0x28, 0, 0x28)
            env = dict(os.environ, ARTIC_DISABLE_PREFETCH="0")
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--romfs-prefetch"],
                                    text=True, capture_output=True, timeout=30, env=env)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("prefetch_ready=1 clean_shutdown=1", result.stdout)
        self.assertEqual(server.requests.count("Title_ReadRomFS"), 3)
        self.assertEqual(server.requests[-1], "$STOP")

    def test_streaming_backend_rejects_file_size_changes(self):
        with FakeConsole() as server:
            server.romfs_change_size = True
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port), "--romfs-cache"],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 1, result.stdout + result.stderr)
        self.assertEqual(server.requests[-1], "$STOP")

    def test_child_and_reset_loaders_keep_one_connection_alive(self):
        with FakeConsole() as server:
            result = subprocess.run([CORE_PROBE, "127.0.0.1", str(server.port)],
                                    text=True, capture_output=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("borrowed_session_alive=1 reset_session_alive=1", result.stdout)
        self.assertEqual(server.requests.count("$VERSION"), 1)
        self.assertEqual(server.requests.count("$STOP"), 1)
        self.assertEqual(server.requests.count("FSFILE_Close"), 2)


if __name__ == "__main__":
    unittest.main()
