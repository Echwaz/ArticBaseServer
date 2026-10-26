"""Compare self and title-based RomFS opens without reading filesystem contents."""
import argparse
import json
import struct

from dock_probe import Console, ProtocolError, integer, small_buffer


def inspect(console, archive_id, archive_path, file_path, separate=False):
    archive = None
    try:
        if separate:
            archive, = struct.unpack("<q", console.call("FSUSER_OpenArchive", [
                integer(archive_id, 4), small_buffer(archive_path)])[0])
            opened = console.call("FSUSER_OpenFile", [integer(archive, 8),
                small_buffer(file_path), integer(1, 4), integer(0, 4)])
        else:
            opened = console.call("FSUSER_OpenFileDirectly", [integer(archive_id, 4),
                small_buffer(archive_path), small_buffer(file_path), integer(1, 4), integer(0, 4)])
        handle, = struct.unpack("<i", opened[0])
        try:
            size, = struct.unpack("<Q", console.call("FSFILE_GetSize", [integer(handle, 4)])[0])
            return {"opened": True, "size": size}
        finally:
            console.call("FSFILE_Close", [integer(handle, 4)])
    except ProtocolError as error:
        return {"opened": False, "error": str(error)}
    finally:
        if archive is not None:
            console.call("FSUSER_CloseArchive", [integer(archive, 8)])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    args = parser.parse_args()
    report = {"contents_read": False}
    with Console(args.address) as console:
        current, = struct.unpack("<Q", console.call("Process_GetTitleID")[0])
        report["active_title"] = f"{current:016X}"
        report["self"] = inspect(console, 3, struct.pack("<II", 1, 1) + b"\0",
                                 struct.pack("<IIIII", 2, 12, 0, 0, 0))
        titles = [("HOME", 0x0004003000008202, 0)]
        if current == 0x000400000FFABC00:
            titles.append(("own_installed_title", current, 1))
        for label, title, media in titles:
            archive_path = struct.pack("<IIQII", 2, 16, title, media, 0)
            file_path = struct.pack("<IIIII8s", 2, 20, 0, 0, 0, b"")
            for separate in (False, True):
                report[f"{label}_{'archive_then_file' if separate else 'direct'}"] = inspect(
                    console, 0x2345678A, archive_path, file_path, separate)
    print(json.dumps(report, indent=2))
