"""List HOME Menu extdata without modifying or copying its files."""
import argparse
import json
import struct

from dock_probe import Console, ProtocolError, integer, small_buffer


def inspect_savedata(console, archive):
    name = b"/SaveData.dat\0"
    path = small_buffer(struct.pack("<II", 3, len(name)) + name)
    opened = console.call("FSUSER_OpenFile", [integer(archive, 8), path, integer(1, 4), integer(0, 4)])
    if len(opened.get(0, b"")) != 4 or len(opened.get(1, b"")) != 8:
        raise ProtocolError("Invalid HOME savedata file response")
    handle, = struct.unpack("<i", opened[0])
    try:
        size, = struct.unpack("<Q", opened[1])
        if size > 1024 * 1024:
            raise ProtocolError("HOME savedata exceeds diagnostic limit")
        data = console.call("FSFILE_Read", [integer(handle, 4), integer(0, 8), integer(size, 4)]).get(0, b"")
        return {"size": size, "bytes_read": len(data), "read_complete": len(data) == size}
    finally:
        console.call("FSFILE_Close", [integer(handle, 4)])


def list_home(console, extdata_id):
    path = struct.pack("<IIIII", 2, 12, 1, extdata_id, 0)
    opened = console.call("FSUSER_OpenArchive", [integer(6, 4), small_buffer(path)]).get(0, b"")
    if len(opened) != 8:
        raise ProtocolError("Invalid archive handle")
    archive, = struct.unpack("<q", opened)
    try:
        root = small_buffer(struct.pack("<II", 3, 2) + b"/\0")
        opened = console.call("FSUSER_OpenDirectory", [integer(archive, 8), root]).get(0, b"")
        if len(opened) != 4:
            raise ProtocolError("Invalid directory handle")
        directory, = struct.unpack("<i", opened)
        try:
            entries = []
            for _ in range(32):
                data = console.call("FSDIR_Read", [integer(directory, 4), integer(16, 4)]).get(0, b"")
                if not data:
                    return {"root_entries": entries, "savedata": inspect_savedata(console, archive)}
                if len(data) % 0x228:
                    raise ProtocolError("Invalid directory entry size")
                for offset in range(0, len(data), 0x228):
                    entries.append(data[offset:offset + 0x20C].decode("utf-16-le").split("\0", 1)[0])
            raise ProtocolError("Directory enumeration exceeded limit")
        finally:
            console.call("FSDIR_Close", [integer(directory, 4)])
    finally:
        console.call("FSUSER_CloseArchive", [integer(archive, 8)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--extdata-id", type=lambda s: int(s, 16), required=True)
    args = parser.parse_args()
    with Console(args.address) as console:
        try:
            print(json.dumps(list_home(console, args.extdata_id), indent=2))
        except ProtocolError as error:
            print(json.dumps({"error": str(error)}))
