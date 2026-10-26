"""Read names of console applications without saving their icon or game assets."""
import argparse
import json

from dock_probe import Console, ProtocolError


def catalog(console):
    entries = []
    for media, name in ((1, "SD"), (2, "GameCard")):
        for title in console.titles(media):
            if not title.startswith("00040000"):
                continue
            entry = {"media": name, "title_id": title}
            try:
                entry.update(console.inspect_icon(int(title, 16), media))
            except ProtocolError as error:
                entry["error"] = str(error)
            entries.append(entry)
    return {"source": "live console", "applications": entries}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("address")
    args = parser.parse_args()
    with Console(args.address) as console:
        print(json.dumps(catalog(console), indent=2))
