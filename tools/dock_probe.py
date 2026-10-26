"""Read-only Artic Base transport and console-title probe; not a dock implementation."""

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import ipaddress
import json
import select
import socket
import struct
import time


class ProtocolError(Exception):
    pass


def receive(sock, size):
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ProtocolError("Console closed the connection")
        data.extend(chunk)
    return bytes(data)


def buffers(payload):
    result = {}
    while payload:
        if len(payload) < 8:
            raise ProtocolError("Truncated buffer header")
        key, size = struct.unpack_from("<II", payload)
        if size > len(payload) - 8 or key in result:
            raise ProtocolError("Invalid response buffer")
        result[key] = payload[8:8 + size]
        payload = payload[8 + size:]
    return result


def integer(value, width):
    kind, fmt = {1: (0, "<b"), 4: (2, "<i"), 8: (3, "<q")}[width]
    return struct.pack("<HH28s", kind, width, struct.pack(fmt, value))


def small_buffer(data):
    if len(data) > 28:
        raise ValueError("Small parameters cannot exceed 28 bytes")
    return struct.pack("<HH28s", 4, len(data), data)


@dataclass(frozen=True)
class BigBuffer:
    data: bytes
    identifier: int = 0

    def encode(self):
        if not 0 <= self.identifier <= 65535:
            raise ValueError("Invalid buffer ID")
        return struct.pack("<HHI24x", 5, self.identifier, len(self.data))


def buffer_parameter(data, identifier=0):
    return small_buffer(data) if len(data) <= 28 else BigBuffer(data, identifier)


class Console:
    def __init__(self, address, port=5543, timeout=5):
        self.address = str(ipaddress.IPv4Address(address))
        self.port = port
        self.timeout = timeout
        self.stack = ExitStack()
        self.sequence = 0
        self.workers = []
        self.control = None

    def connect(self, port):
        return self.stack.enter_context(
            socket.create_connection((self.address, port), self.timeout))

    def packet(self, method, params=()):
        self.sequence += 1
        name = method.encode("ascii")
        if len(name) > 31 or len(params) > 10:
            raise ValueError("Invalid Artic request")
        encoded = [p.encode() if isinstance(p, BigBuffer) else p for p in params]
        return struct.pack("<I32sI", self.sequence, name, len(params)) + b"".join(encoded)

    def simple(self, method):
        self.control.sendall(self.packet(method))
        response = receive(self.control, 32)
        if struct.unpack_from("<I", response)[0] != self.sequence:
            raise ProtocolError("Unexpected control response ID")
        return response[4:].split(b"\0", 1)[0].decode("ascii")

    def __enter__(self):
        try:
            self.control = self.connect(self.port)
            if self.simple("$VERSION") != "2":
                raise ProtocolError("Unsupported Artic protocol version")
            ports = [int(p) for p in self.simple("$PORTS").split(",")]
            if len(ports) != 4 or len(set(ports)) != 4 or any(p < 1 or p > 65535 for p in ports):
                raise ProtocolError("Invalid worker ports")
            deadline = time.monotonic() + self.timeout
            while self.simple("$READY") != "1":
                if time.monotonic() >= deadline:
                    raise ProtocolError("Console workers did not become ready")
                time.sleep(0.05)
            self.workers = [self.connect(p) for p in ports]
            self.max_size = int(self.simple("$MAXSIZE"))
            if not 8 <= self.max_size <= 16 * 1024 * 1024:
                raise ProtocolError("Invalid work buffer limit")
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *_):
        if self.control is not None:
            try:
                self.simple("$STOP")
            except (OSError, ProtocolError, ValueError):
                pass
        self.stack.close()

    def call(self, method, params=()):
        pending = {}
        for param in params:
            if isinstance(param, BigBuffer):
                if param.identifier in pending or len(param.data) > self.max_size - 8:
                    raise ValueError("Duplicate or oversized input buffer")
                pending[param.identifier] = param.data
        self.control.sendall(self.packet(method, params))
        ready, _, _ = select.select(self.workers, [], [], self.timeout)
        if not ready:
            raise ProtocolError(f"Timed out waiting for {method}")
        worker = ready[0]
        while True:
            header = receive(worker, 32)
            request_id, state, result, size = struct.unpack_from("<IIiI", header)
            if request_id != self.sequence:
                raise ProtocolError("Unexpected worker response ID")
            if state != 3:
                break
            data = pending.pop(result, None)
            if data is None or len(data) != size:
                raise ProtocolError("Unexpected input-buffer request")
            worker.sendall(header + data)
        if state != 0:
            raise ProtocolError(f"{method}: protocol state {state}, detail {result}")
        if size > self.max_size:
            raise ProtocolError("Response exceeds negotiated buffer size")
        payload = receive(worker, size)
        if result < 0:
            raise ProtocolError(f"{method}: console result 0x{result & 0xffffffff:08X}")
        return buffers(payload)

    def titles(self, media):
        count_data = self.call("AM_GetTitleCount", [integer(media, 1)]).get(0, b"")
        if len(count_data) != 4:
            raise ProtocolError("Invalid title count")
        count, = struct.unpack("<I", count_data)
        if count > (self.max_size - 8) // 8:
            raise ProtocolError("Title list exceeds console buffer")
        if count == 0:
            return []
        data = self.call("AM_GetTitleList", [integer(count, 4), integer(media, 1)]).get(0, b"")
        if len(data) % 8 or len(data) > count * 8:
            raise ProtocolError("Invalid title list")
        return [f"{title:016X}" for (title,) in struct.iter_unpack("<Q", data)]

    def inspect_icon(self, title, media):
        archive = struct.pack("<IIQII", 2, 16, title, media, 0)
        path = struct.pack("<IIIII8s", 2, 20, 0, 0, 2, b"icon")
        opened = self.call("FSUSER_OpenFileDirectly", [
            integer(0x2345678A, 4), small_buffer(archive), small_buffer(path),
            integer(1, 4), integer(0, 4),
        ]).get(0, b"")
        if len(opened) != 4:
            raise ProtocolError("Invalid file handle")
        handle, = struct.unpack("<i", opened)
        try:
            size_data = self.call("FSFILE_GetSize", [integer(handle, 4)]).get(0, b"")
            if len(size_data) != 8:
                raise ProtocolError("Invalid icon size response")
            size, = struct.unpack("<Q", size_data)
            if not 0x408 <= size <= 65536:
                raise ProtocolError("Unexpected SMDH size")
            # ExeFS icon reads must request the entire section on the console.
            data = self.call("FSFILE_Read", [
                integer(handle, 4), integer(0, 8), integer(size, 4),
            ]).get(0, b"")
            if len(data) != size or data[:4] != b"SMDH":
                raise ProtocolError("Icon does not contain the expected SMDH header")
            name = data[0x208:0x288].decode("utf-16-le").split("\0", 1)[0]
            return {"title_id": f"{title:016X}", "english_name": name,
                    "icon_readable": True}
        finally:
            self.call("FSFILE_Close", [integer(handle, 4)])


def probe(address, port=5543, inspect_content=False):
    with Console(address, port) as console:
        current = console.call("Process_GetTitleID").get(0, b"")
        if len(current) != 8:
            raise ProtocolError("Invalid active title ID")
        report = {
            "stage": "transport-and-title-discovery-only",
            "active_title": f"{struct.unpack('<Q', current)[0]:016X}",
            "media": {},
        }
        for media, name in enumerate(("NAND", "SD", "GameCard")):
            try:
                report["media"][name] = {"title_ids": console.titles(media)}
            except ProtocolError as error:
                report["media"][name] = {"error": str(error)}
        if inspect_content:
            candidates = []
            home_ids = {"0004003000008202", "0004003000008F02", "0004003000009802",
                        "000400300000A102", "000400300000A902", "000400300000B102"}
            for title in report["media"]["NAND"].get("title_ids", []):
                if title in home_ids:
                    candidates.append((int(title, 16), 0))
            for title in report["media"]["SD"].get("title_ids", []):
                if (title.startswith("00040000") and title != report["active_title"]
                        and int(title[8:], 16) < 0x02000000):
                    candidates.append((int(title, 16), 1))
                    if len(candidates) >= 4:
                        break
            report["content_checks"] = []
            for title, media in candidates:
                try:
                    report["content_checks"].append(console.inspect_icon(title, media))
                except ProtocolError as error:
                    report["content_checks"].append({"title_id": f"{title:016X}", "error": str(error)})
        return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address", help="IPv4 address displayed by Artic Base Server")
    parser.add_argument("--port", type=int, default=5543)
    parser.add_argument("--inspect-content", action="store_true",
                        help="Read small icon headers for HOME Menu and one inactive SD title")
    args = parser.parse_args()
    try:
        print(json.dumps(probe(args.address, args.port, args.inspect_content), indent=2))
    except (OSError, ProtocolError, ValueError) as error:
        parser.exit(1, f"Probe failed: {error}\n")


if __name__ == "__main__":
    main()
