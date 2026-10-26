"""Back up or install a test plugin at Artic Base's fixed SD-card location."""
import argparse
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import struct

from dock_probe import Console, ProtocolError, buffer_parameter, integer

PLUGIN = "/3ds/ArticBase/ArticBase.3gx"
LIMIT = 4 * 1024 * 1024


def digest(data):
    return hashlib.sha256(data).hexdigest()


def fs_path(name, identifier=0):
    data = name.encode("ascii") + b"\0"
    return buffer_parameter(struct.pack("<II", 3, len(data)) + data, identifier)


class RemoteSD:
    def __init__(self, console):
        self.console = console

    def __enter__(self):
        path = buffer_parameter(struct.pack("<II", 1, 1) + b"\0")
        response = self.console.call("FSUSER_OpenArchive", [integer(9, 4), path])
        self.archive, = struct.unpack("<q", response[0])
        return self

    def __exit__(self, *_):
        self.console.call("FSUSER_CloseArchive", [integer(self.archive, 8)])

    @contextmanager
    def opened(self, name, mode):
        response = self.console.call("FSUSER_OpenFile", [
            integer(self.archive, 8), fs_path(name), integer(mode, 4), integer(0, 4)])
        handle, = struct.unpack("<i", response[0])
        try:
            yield handle
        finally:
            self.console.call("FSFILE_Close", [integer(handle, 4)])

    def read(self, name):
        with self.opened(name, 1) as handle:
            size, = struct.unpack("<Q", self.console.call("FSFILE_GetSize", [integer(handle, 4)])[0])
            if size > LIMIT:
                raise ProtocolError("Plugin exceeds transfer limit")
            result = bytearray()
            while len(result) < size:
                amount = min(65536, size - len(result))
                block = self.console.call("FSFILE_Read", [
                    integer(handle, 4), integer(len(result), 8), integer(amount, 4)]).get(0, b"")
                if len(block) != amount:
                    raise ProtocolError("Incomplete plugin read")
                result.extend(block)
            return bytes(result)

    def write_new(self, name, data):
        self.console.call("FSUSER_CreateFile", [
            integer(self.archive, 8), fs_path(name), integer(0, 4), integer(len(data), 8)])
        with self.opened(name, 2) as handle:
            for offset in range(0, len(data), 65536):
                block = data[offset:offset + 65536]
                response = self.console.call("FSFILE_Write", [
                    integer(handle, 4), integer(offset, 8), integer(len(block), 4),
                    integer(1, 4), buffer_parameter(block)])
                if response.get(0) != struct.pack("<I", len(block)):
                    raise ProtocolError("Incomplete plugin write")

    def rename(self, source, target):
        self.console.call("FSUSER_RenameFile", [
            integer(self.archive, 8), fs_path(source, 0),
            integer(self.archive, 8), fs_path(target, 1)])


def install(filesystem, data, expected_hash, suffix):
    if len(data) < 0x100 or len(data) > LIMIT or data[:8] != b"3GX$0002":
        raise ValueError("Invalid 3GX plugin")
    if not suffix.isalnum():
        raise ValueError("Invalid deployment suffix")
    original = filesystem.read(PLUGIN)
    if digest(original) != expected_hash:
        raise ProtocolError("Installed plugin changed since backup; installation cancelled")
    stage = f"/3ds/ArticBase/ArticBase-stage-{suffix}.3gx"
    backup = f"/3ds/ArticBase/ArticBase-backup-{suffix}.3gx"
    filesystem.write_new(stage, data)
    if filesystem.read(stage) != data:
        raise ProtocolError("Staged plugin verification failed; original plugin is intact")
    filesystem.rename(PLUGIN, backup)
    try:
        filesystem.rename(stage, PLUGIN)
        if filesystem.read(PLUGIN) != data:
            raise ProtocolError("Installed plugin verification failed")
    except Exception:
        # Preserve the staged/failed plugin and restore the known original.
        try:
            filesystem.rename(PLUGIN, stage)
        except Exception:
            pass
        filesystem.rename(backup, PLUGIN)
        raise
    return {"sha256": digest(data), "remote_backup": backup, "bytes": len(data)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--backup", type=Path)
    action.add_argument("--install", type=Path)
    parser.add_argument("--expected-sha256")
    args = parser.parse_args()
    if args.install and not args.expected_sha256:
        parser.error("--install requires --expected-sha256 from a verified local backup")
    with Console(args.address) as console, RemoteSD(console) as filesystem:
        if args.backup:
            original = filesystem.read(PLUGIN)
            with args.backup.open("xb") as output:
                output.write(original)
            result = {"backup": str(args.backup), "sha256": digest(original), "bytes": len(original)}
        else:
            suffix = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
            result = install(filesystem, args.install.read_bytes(), args.expected_sha256, suffix)
    print(json.dumps(result, indent=2))
