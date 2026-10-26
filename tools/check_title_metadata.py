"""Validate the experimental server's title-specific ExHeader endpoint."""
import argparse
import json
import struct

from dock_probe import Console, ProtocolError, integer


def inspect(console, title, media):
    data = console.call("Title_GetExheader", [integer(title, 8), integer(media, 1)]).get(0, b"")
    if len(data) != 0x400:
        raise ProtocolError("Title metadata has an unexpected size")
    returned_title, = struct.unpack_from("<Q", data, 0x200)
    if returned_title != title:
        raise ProtocolError(f"Wrong title metadata: {returned_title:016X}")
    return {"title_id": f"{title:016X}", "media": media, "size": len(data), "identity_verified": True}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    parser.add_argument("--title", type=lambda value: int(value, 16), required=True)
    parser.add_argument("--media", type=int, choices=(0, 1, 2), required=True)
    args = parser.parse_args()
    with Console(args.address) as console:
        try:
            result = inspect(console, args.title, args.media)
        except ProtocolError as error:
            result = {"error": str(error)}
        print(json.dumps(result, indent=2))
