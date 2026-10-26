"""Run the bounded PXI HOME RomFS probe; retain only size and format checks."""
import argparse
import json
import struct

from dock_probe import Console, ProtocolError


def decode(data):
    if len(data) != 32:
        raise ProtocolError("Invalid PXI probe report")
    stage, result, size, count, magic, file_close, archive_close = struct.unpack("<IiQI4sii", data)
    return {"stage": stage, "result": f"0x{result & 0xffffffff:08X}",
            "size": size, "bytes_read": count, "is_ivfc": magic == b"IVFC",
            "file_close": f"0x{file_close & 0xffffffff:08X}",
            "archive_close": f"0x{archive_close & 0xffffffff:08X}"}


def inspect(console):
    response = console.call("Title_ProbePXIRomFS")
    result = {"title_access": decode(response.get(0, b""))}
    if 1 in response:
        result["program_access"] = decode(response[1])
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    args = parser.parse_args()
    try:
        with Console(args.address) as console:
            report = inspect(console)
        print(json.dumps(report, indent=2))
    except (ProtocolError, OSError) as error:
        print(json.dumps({"error": str(error)}))
