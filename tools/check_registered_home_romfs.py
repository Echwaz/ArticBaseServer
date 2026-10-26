"""Probe the registered-program HOME RomFS path without reading its contents."""
import json
import struct

from dock_probe import Console, ProtocolError, integer


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    args = parser.parse_args()
    try:
        with Console(args.address) as console:
            response = console.call("Title_ProbeRomFS", [
                integer(0x0004003000008202, 8), integer(0, 1)])
            data = response.get(0, b"")
            if len(data) != 8:
                raise ProtocolError("Invalid RomFS size response")
            size, = struct.unpack("<Q", data)
        print(json.dumps({"opened": True, "size": size, "contents_read": False}))
    except (ProtocolError, OSError) as error:
        print(json.dumps({"opened": False, "error": str(error)}))
