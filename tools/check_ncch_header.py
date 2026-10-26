"""Read only NCCH headers in one NAND title's content directory."""
import argparse
import json
import struct

from dock_probe import Console, ProtocolError, buffer_parameter, integer
from plugin_transfer import RemoteSD, fs_path


class NandContent(RemoteSD):
    def __enter__(self):
        path = buffer_parameter(struct.pack("<II", 1, 1) + b"\0")
        response = self.console.call("FSUSER_OpenArchive", [integer(0x567890AB, 4), path])
        self.archive, = struct.unpack("<q", response[0])
        return self

    def content_names(self, directory):
        response = self.console.call("FSUSER_OpenDirectory", [integer(self.archive, 8), fs_path(directory)])
        handle, = struct.unpack("<i", response[0])
        try:
            data = self.console.call("FSDIR_Read", [integer(handle, 4), integer(32, 4)]).get(0, b"")
            if len(data) % 0x228:
                raise ProtocolError("Invalid NAND directory listing")
            names = []
            for offset in range(0, len(data), 0x228):
                raw = data[offset:offset + 0x20C]
                end = next((i for i in range(0, len(raw), 2)
                            if raw[i:i + 2] == b"\0\0"), len(raw))
                names.append(raw[:end].decode("utf-16-le"))
            return names
        finally:
            self.console.call("FSDIR_Close", [integer(handle, 4)])

    def header(self, filename):
        with self.opened(filename, 1) as handle:
            data = self.console.call("FSFILE_Read", [integer(handle, 4), integer(0, 8), integer(512, 4)]).get(0, b"")
        if len(data) != 512 or data[0x100:0x104] != b"NCCH":
            raise ProtocolError("Not an NCCH header")
        program_id, = struct.unpack_from("<Q", data, 0x118)
        offset, size = struct.unpack_from("<II", data, 0x1B0)
        return {"file": filename, "program_id": f"{program_id:016X}",
                "no_romfs_flag": bool(data[0x18F] & 2),
                "no_crypto_flag": bool(data[0x18F] & 4),
                "content_unit_exponent": data[0x18E],
                "romfs_offset_units": offset, "romfs_size_units": size}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("title", type=lambda value: int(value, 16))
    args = parser.parse_args()
    try:
        with Console(args.address) as console, NandContent(console) as filesystem:
            directory = f"/title/{args.title >> 32:08x}/{args.title & 0xffffffff:08x}/content"
            result = [filesystem.header(directory + "/" + name)
                      for name in filesystem.content_names(directory) if name.endswith(".app")]
        print(json.dumps(result, indent=2))
    except (ProtocolError, OSError) as error:
        print(json.dumps({"error": str(error)}))
