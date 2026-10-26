"""Compare NCCH icon read sizes without retaining icon content."""
import argparse
import struct

from dock_probe import Console, ProtocolError, integer, small_buffer


def check(console, title, media):
    archive = struct.pack("<IIQII", 2, 16, title, media, 0)
    path = struct.pack("<IIIII8s", 2, 20, 0, 0, 2, b"icon")
    handle, = struct.unpack("<i", console.call("FSUSER_OpenFileDirectly", [
        integer(0x2345678A, 4), small_buffer(archive), small_buffer(path),
        integer(1, 4), integer(0, 4),
    ])[0])
    try:
        size, = struct.unpack("<Q", console.call("FSFILE_GetSize", [integer(handle, 4)])[0])
        print(f"{title:016X} media={media} icon size={size}", flush=True)
        if size > 65536:
            raise ProtocolError("Unexpected icon size")
        for length in (4, 0x200, 0x400, size):
            try:
                data = console.call("FSFILE_Read", [integer(handle, 4), integer(0, 8), integer(length, 4)]).get(0, b"")
                print(f"  length={length}: received={len(data)}, SMDH={data[:4] == b'SMDH'}", flush=True)
            except ProtocolError as error:
                print(f"  length={length}: {error}", flush=True)
    finally:
        console.call("FSFILE_Close", [integer(handle, 4)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    args = parser.parse_args()
    with Console(args.address) as console:
        active, = struct.unpack("<Q", console.call("Process_GetTitleID")[0])
        for title, media in ((active, 2), (0x0004000000055D00, 1)):
            try:
                check(console, title, media)
            except ProtocolError as error:
                print(error)
