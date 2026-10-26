"""Prepare an isolated local emulator profile from existing system files and HOME extdata."""
import argparse
import json
from pathlib import Path
import shutil
import struct

from dock_probe import Console, ProtocolError, integer, small_buffer
from plugin_transfer import RemoteSD


class HomeExtdata(RemoteSD):
    def __enter__(self):
        path = small_buffer(struct.pack("<IIIII", 2, 12, 1, 0x82, 0))
        self.archive, = struct.unpack("<q", self.console.call(
            "FSUSER_OpenArchive", [integer(6, 4), path])[0])
        return self

    def read_home(self, name):
        with self.opened("/" + name, 1) as handle:
            size, = struct.unpack("<Q", self.console.call(
                "FSFILE_GetSize", [integer(handle, 4)])[0])
            if size > 16 * 1024 * 1024:
                raise ProtocolError("HOME extdata file exceeds local import limit")
            result = bytearray()
            while len(result) < size:
                amount = min(65536, size - len(result))
                part = self.console.call("FSFILE_Read", [
                    integer(handle, 4), integer(len(result), 8), integer(amount, 4)]).get(0, b"")
                if len(part) != amount:
                    raise ProtocolError("Incomplete HOME extdata read")
                result.extend(part)
            return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--destination", type=Path, required=True)
    args = parser.parse_args()
    if args.destination.exists():
        parser.error("Destination already exists; refusing to overwrite a profile")
    zero = "0" * 32
    relative_ext = Path("sdmc") / "Nintendo 3DS" / zero / zero / "extdata/00000000/00000082"
    if not (args.source / relative_ext / "metadata").is_file():
        parser.error("Existing Japanese HOME extdata metadata is required")
    files = {}
    skipped = []
    with Console(args.address) as console, HomeExtdata(console) as archive:
        files["SaveData.dat"] = archive.read_home("SaveData.dat")
        for name in ("Cache.dat", "CacheD.dat"):
            try:
                files[name] = archive.read_home(name)
            except ProtocolError as error:
                if "0xC92044E6" not in str(error):
                    raise
                skipped.append(name)
    args.destination.mkdir(parents=True)
    for name in ("nand", "sysdata"):
        shutil.copytree(args.source / name, args.destination / name)
    extdata = args.destination / relative_ext
    shutil.copytree(args.source / relative_ext, extdata,
                    ignore=shutil.ignore_patterns("Cache.dat", "CacheD.dat"))
    for name, data in files.items():
        (extdata / "user" / name).write_bytes(data)
    sizes = {name: len(data) for name, data in files.items()}
    config = args.destination / "config"
    config.mkdir()
    (config / "qt-config.ini").write_text(
        "[UI]\nfirstStart=false\nconfirm_before_closing=false\n"
        "[System]\nis_new_3ds=false\nregion_value=0\n", encoding="utf-8")
    print(json.dumps({"profile_prepared": True, "console_files_read_only": sizes,
                      "locked_optional_caches_skipped": skipped,
                      "assets_in_deliverables": False}))
