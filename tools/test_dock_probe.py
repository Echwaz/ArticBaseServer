import socket
import struct
import threading
import unittest

from dock_probe import Console, ProtocolError, BigBuffer, buffers, probe, receive


class FakeConsole:
    def __enter__(self):
        self.fragment_size = 3
        self.code_truncate = False
        self.registered_code_size = None
        self.update_romfs_image = None
        self.wrong_title = False
        self.truncate_icon = False
        self.icon_size = 0x36C0
        self.open_error = 0
        self.romfs_image = bytearray(0x1040)
        self.romfs_image[:4] = b"IVFC"
        struct.pack_into("<I", self.romfs_image, 4, 0x10000)
        struct.pack_into("<Q", self.romfs_image, 0x44, 0x40)
        struct.pack_into("<I", self.romfs_image, 0x4C, 12)
        struct.pack_into("<10I", self.romfs_image, 0x1000,
                         0x28, 0x28, 0, 0x28, 0, 0x28, 0, 0x28, 0, 0x28)
        self.romfs_size_override = None
        self.romfs_truncate = False
        self.gamecard_present = False
        self.gamecard_title = 0x0004000000197100
        self.gamecard_sequence = None
        self.romfs_change_size = False
        self.layout_bad_size = False
        self.save_data = b"SAVE"
        self.save_directory_reads = 0
        self.save_listing_bad = False
        self.save_listing_zero_size = False
        self.listeners = []
        for _ in range(5):
            listener = socket.socket()
            listener.bind(("127.0.0.1", 0))
            listener.listen(1)
            listener.settimeout(5)
            self.listeners.append(listener)
        self.port = self.listeners[0].getsockname()[1]
        self.error = None
        self.requests = []
        self.thread = threading.Thread(target=self.run)
        self.thread.start()
        return self

    def run(self):
        peers = []
        try:
            control, _ = self.listeners[0].accept()
            control.settimeout(5)
            peers.append(control)
            workers = []
            while True:
                request_id, raw_method, count = struct.unpack("<I32sI", receive(control, 40))
                method = raw_method.split(b"\0", 1)[0].decode()
                params = receive(control, count * 32)
                self.requests.append(method)
                if method.startswith("$"):
                    replies = {
                        "$VERSION": "2",
                        "$PORTS": ",".join(str(s.getsockname()[1]) for s in self.listeners[1:]),
                        "$READY": "1",
                        "$MAXSIZE": "4718592",
                        "$MAXPARAM": "10",
                        "$PING": "",
                        "$STOP": "",
                    }
                    control.sendall(struct.pack("<I28s", request_id, replies[method].encode()))
                    if method == "$STOP":
                        break
                    if method == "$READY":
                        for listener in self.listeners[1:]:
                            worker, _ = listener.accept()
                            worker.settimeout(5)
                            workers.append(worker)
                            peers.append(worker)
                    continue
                method_result = 0
                extra_payload = b""
                if method == "Process_GetTitleID":
                    self.assert_params(params, [])
                    data = struct.pack("<Q", 0x0004000000123400)
                elif method == "Title_GetExheader":
                    self.assert_params(params, [(3, 8), (0, 1)])
                    title, = struct.unpack_from("<Q", params, 4)
                    data = bytearray(0x400)
                    struct.pack_into("<Q", data, 0x200, title + int(self.wrong_title))
                    data = bytes(data)
                elif method in ("Title_ReadHomeRomFS", "Title_ReadRomFS", "Title_ReadUpdateRomFS"):
                    if method in ("Title_ReadRomFS", "Title_ReadUpdateRomFS"):
                        self.assert_params(params, [(3, 8), (0, 1), (3, 8), (2, 4)])
                        first = 64
                    else:
                        self.assert_params(params, [(3, 8), (2, 4)])
                        first = 0
                    offset, = struct.unpack_from("<q", params, first + 4)
                    amount, = struct.unpack_from("<i", params, first + 36)
                    if offset < 0 or not 0 < amount <= 256 * 1024:
                        raise AssertionError("Invalid RomFS range")
                    image = self.update_romfs_image if method == "Title_ReadUpdateRomFS" and self.update_romfs_image is not None else self.romfs_image
                    data = bytes(image[offset:offset + amount])
                    if self.romfs_truncate:
                        data = data[:-1]
                    total = self.romfs_size_override or len(self.romfs_image)
                    if self.romfs_change_size and self.requests.count("Title_ReadRomFS") > 1:
                        total += 1
                    extra_payload = struct.pack("<IIQ", 1, 8, total)
                elif method == "AM_GetTitleCount":
                    self.assert_params(params, [(0, 1)])
                    media = params[4]
                    if media == 2 and self.gamecard_sequence is not None:
                        state = self.gamecard_sequence.pop(0)
                        if state == "error": method_result = -1
                        elif state == "absent_error": method_result = 0xC880448D - 2**32
                        else:
                            self.gamecard_present = state is not None
                            if state is not None: self.gamecard_title = state
                    data = struct.pack("<I", int(self.gamecard_present) if media == 2 else 1)
                elif method == "AM_GetTitleList":
                    self.assert_params(params, [(2, 4), (0, 1)])
                    media = params[36]
                    title = {0: 0x0004003000008F02, 1: 0x0004000000123400,
                             2: self.gamecard_title}[media]
                    data = struct.pack("<Q", title)
                elif method == "FSUSER_OpenFileDirectly":
                    self.assert_params(params, [(2, 4), (4, 24), (4, 28), (2, 4), (2, 4)])
                    if struct.unpack_from("<I", params, 100)[0] != 1:
                        raise AssertionError("File must be opened read-only")
                    data = struct.pack("<i", 123)
                    if self.open_error:
                        method_result = self.open_error
                        data = b""
                elif method == "FSUSER_OpenArchive":
                    archive, = struct.unpack_from("<I", params, 4)
                    self.assert_params(params, [(2, 4), (4, 16 if archive == 8 else 20)])
                    dock_extdata = archive == 6 and struct.unpack_from("<I", params, 48)[0] == 0x1234
                    expected = ((2, 12, 1, 0x1234, 0) if dock_extdata else (2, 12, 1, 0x123400, 0x40000) if archive == 0x567890B2 else
                                (2, 8, 0, 0x20082) if archive == 8 else (2, 12, 1, 0x82, 0))
                    if params[36:36 + 4 * len(expected)] != struct.pack("<" + "I" * len(expected), *expected):
                        raise AssertionError("Wrong HOME archive path")
                    data = struct.pack("<q", 300 if dock_extdata or archive == 0x567890B2 else 101 if archive == 8 else 100)
                elif method == "FSUSER_CloseArchive":
                    self.assert_params(params, [(3, 8)])
                    data = b""
                elif method == "FSUSER_OpenFile":
                    archive, = struct.unpack_from("<q", params, 4)
                    if archive == 300:
                        path_type, path_size = struct.unpack_from("<II", params, 36)
                        encoding = "utf-16-le" if path_type == 4 else "ascii"
                        name = params[44:44 + path_size].decode(encoding).rstrip("\0")
                        if name != "/main": raise AssertionError("Wrong save file")
                        data = struct.pack("<i", 500)
                    else:
                        name = b"/Launcher.dat\0" if archive == 101 else b"/SaveData.dat\0"
                        self.assert_params(params, [(3, 8), (4, 8 + len(name)), (2, 4), (2, 4)])
                        if params[44:44 + len(name)] != name or struct.unpack_from("<I", params, 68)[0] != 1:
                            raise AssertionError("HOME layout must be opened read-only")
                        data = struct.pack("<i", archive + 100)
                elif method == "FSUSER_OpenDirectory":
                    if struct.unpack_from("<q", params, 4)[0] != 300: raise AssertionError("Wrong save archive")
                    data = struct.pack("<i", 550)
                elif method == "FSDIR_Read":
                    data = bytearray(0x228) if self.save_directory_reads == 0 else b""
                    if data:
                        data[:10] = "main\0".encode("utf-16-le")
                        struct.pack_into("<Q", data, 0x220, 0 if self.save_listing_zero_size else len(self.save_data))
                    self.save_directory_reads += 1
                    if self.save_listing_bad: data = b"!"
                    data = bytes(data)
                elif method in ("FSDIR_Close", "FSFILE_Flush", "FSUSER_ControlArchive"):
                    data = b""
                elif method == "FSUSER_GetSaveDataSecureValue":
                    self.assert_params(params, [(3, 8), (2, 4)])
                    data = struct.pack("<BB6xQ", 0, 0, 0)
                elif method == "FSFILE_Write":
                    self.assert_params(params, [(2, 4), (3, 8), (2, 4), (2, 4), (4, 4)])
                    if struct.unpack_from("<i", params, 4)[0] != 500: raise AssertionError("Wrong save handle")
                    self.save_data = params[132:136]
                    data = struct.pack("<I", 4)
                elif method == "FSFILE_Read" and struct.unpack_from("<i", params, 4)[0] >= 200:
                    self.assert_params(params, [(2, 4), (3, 8), (2, 4)])
                    handle, = struct.unpack_from("<i", params, 4)
                    size = len(self.save_data) if handle == 500 else 0x2558 if handle == 201 else 0x2DA0
                    offset, = struct.unpack_from("<q", params, 36)
                    amount, = struct.unpack_from("<i", params, 68)
                    data = self.save_data if handle == 500 else bytes([handle & 255]) * size
                    data = data[offset:offset + amount]
                elif method == "Title_GetCodeSize":
                    self.assert_params(params, [(3, 8), (0, 1)])
                    data = struct.pack("<Q", self.registered_code_size if self.registered_code_size is not None else self.icon_size)
                elif method == "Title_ReadCodeChunk":
                    self.assert_params(params, [(3, 8), (0, 1), (2, 4), (2, 4), (2, 4)])
                    total, = struct.unpack_from("<i", params, 68)
                    offset, = struct.unpack_from("<i", params, 100)
                    amount, = struct.unpack_from("<i", params, 132)
                    if total != (self.registered_code_size if self.registered_code_size is not None else self.icon_size) or offset < 0 or amount > 1024 * 1024 or offset + amount > total:
                        raise AssertionError("Invalid code chunk bounds")
                    data = bytes(i % 251 for i in range(offset, offset + amount))
                    if self.code_truncate: data = data[:-1]
                elif method == "FSFILE_Read":
                    self.assert_params(params, [(2, 4), (3, 8), (2, 4)])
                    if struct.unpack_from("<i", params, 68)[0] != 0x36C0:
                        raise AssertionError("ExeFS section must be read in full")
                    data = bytearray(0x36C0)
                    data[:4] = b"SMDH"
                    data[0x208:0x208 + 8] = "Test".encode("utf-16-le")
                    data = bytes(data)
                    if self.truncate_icon:
                        data = data[:-1]
                elif method == "FSFILE_GetSize":
                    self.assert_params(params, [(2, 4)])
                    handle, = struct.unpack_from("<i", params, 4)
                    size = (len(self.save_data) if handle == 500 else 0x2558 if handle == 201 else 0x2DA0) if handle >= 200 else self.icon_size
                    data = struct.pack("<Q", size + int(self.layout_bad_size and handle >= 200))
                elif method == "FSFILE_Close":
                    self.assert_params(params, [(2, 4)])
                    data = b""
                elif method == "EchoLarge":
                    kind, identifier, length = struct.unpack_from("<HHI", params)
                    if kind != 5 or identifier != 7:
                        raise AssertionError("Invalid large parameter")
                    request = struct.pack("<IIiI16x", request_id, 3, identifier, length)
                    worker = workers[request_id % 4]
                    worker.sendall(request)
                    if receive(worker, 32) != request:
                        raise AssertionError("Invalid input acknowledgement")
                    data = receive(worker, length)
                else:
                    raise AssertionError(method)
                payload = (struct.pack("<II", 0, len(data)) + data + extra_payload
                           if data or extra_payload else b"")
                response = struct.pack("<IIiI16x", request_id, 0, method_result, len(payload)) + payload
                # TCP may split either headers or payloads across reads.
                for offset in range(0, len(response), self.fragment_size):
                    workers[request_id % 4].sendall(response[offset:offset + self.fragment_size])
        except BaseException as error:
            self.error = error
        finally:
            for peer in peers:
                peer.close()

    @staticmethod
    def assert_params(params, expected):
        actual = [struct.unpack_from("<HH", params, offset) for offset in range(0, len(params), 32)]
        if len(actual) != len(expected) or any(
                kind != wanted_kind or (kind >= 4 and size != wanted_size)
                for (kind, size), (wanted_kind, wanted_size) in zip(actual, expected)):
            raise AssertionError((actual, expected))

    def __exit__(self, *_):
        self.thread.join(7)
        for listener in self.listeners:
            listener.close()
        if self.thread.is_alive():
            raise AssertionError("Fake console did not stop")
        if self.error:
            raise self.error


class DockProbeTests(unittest.TestCase):
    def test_large_parameter_handshake(self):
        data = bytes(range(256)) * 4
        with FakeConsole() as server:
            with Console("127.0.0.1", server.port) as console:
                self.assertEqual(console.call("EchoLarge", [BigBuffer(data, 7)])[0], data)

    def test_icon_header_is_read_only_and_handle_is_closed(self):
        with FakeConsole() as server:
            with Console("127.0.0.1", server.port) as console:
                result = console.inspect_icon(0x0004000000123400, 1)
        self.assertEqual(result["english_name"], "Test")
        self.assertIn("FSFILE_Close", server.requests)

    def test_title_discovery_over_fragmented_tcp_and_clean_shutdown(self):
        with FakeConsole() as server:
            result = probe("127.0.0.1", server.port)
        self.assertEqual(result["active_title"], "0004000000123400")
        self.assertEqual(result["media"]["NAND"]["title_ids"], ["0004003000008F02"])
        self.assertEqual(result["media"]["SD"]["title_ids"], ["0004000000123400"])
        self.assertEqual(result["media"]["GameCard"]["title_ids"], [])
        self.assertEqual(server.requests[-1], "$STOP")
        self.assertNotIn("FSFILE_Write", server.requests)

    def test_rejects_malformed_response_buffers(self):
        for payload in (b"abc", struct.pack("<II", 0, 99), struct.pack("<IIII", 0, 0, 0, 0)):
            with self.subTest(payload=payload), self.assertRaises(ProtocolError):
                buffers(payload)

    def test_peer_disconnect_does_not_spin(self):
        left, right = socket.socketpair()
        try:
            right.close()
            with self.assertRaises(ProtocolError):
                receive(left, 32)
        finally:
            left.close()


if __name__ == "__main__":
    unittest.main()
