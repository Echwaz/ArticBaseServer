"""Check remote HOME Menu sections; retain no executable or filesystem content."""
import argparse
import json
import struct

from dock_probe import Console, ProtocolError, integer, small_buffer


def inspect_section(console, title, kind, name):
    archive = struct.pack("<IIQII", 2, 16, title, 0, 0)
    path = struct.pack("<IIIII8s", 2, 20, 0, 0, kind, name)
    opened = console.call("FSUSER_OpenFileDirectly", [
        integer(0x2345678A, 4), small_buffer(archive), small_buffer(path),
        integer(1, 4), integer(0, 4),
    ]).get(0, b"")
    if len(opened) != 4:
        raise ProtocolError("Invalid file handle")
    handle, = struct.unpack("<i", opened)
    try:
        size_data = console.call("FSFILE_GetSize", [integer(handle, 4)]).get(0, b"")
        if len(size_data) != 8:
            raise ProtocolError("Invalid section size")
        size, = struct.unpack("<Q", size_data)
        result = {"size": size, "opened": True}
        amount = min(size, 512) if kind == 0 else size
        if amount > console.max_size - 8:
            result["read"] = "not attempted: exceeds transport buffer"
            return result
        data = console.call("FSFILE_Read", [integer(handle, 4), integer(0, 8), integer(amount, 4)]).get(0, b"")
        result["bytes_read"] = len(data)
        result["read_complete"] = len(data) == amount
        return result
    finally:
        console.call("FSFILE_Close", [integer(handle, 4)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    args = parser.parse_args()
    result = {}
    with Console(args.address) as console:
        for label, kind, name in (("code", 1, b""), ("code_exefs", 2, b".code"), ("romfs", 0, b"")):
            try:
                result[label] = inspect_section(console, 0x0004003000008202, kind, name)
            except ProtocolError as error:
                result[label] = {"error": str(error)}
    print(json.dumps(result, indent=2))
