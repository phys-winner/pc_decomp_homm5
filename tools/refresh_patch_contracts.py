"""Review/refresh shared-source pins in the three engine contracts, never build receipts.

Dry-run is the default. --apply is an explicit maintainer acknowledgement of the listed
source changes. Only identity layout anchors (old == new) spanning one whole C function
can be refreshed automatically: a real edition-specific ABI patch must be reviewed by hand.
"""
import argparse
import copy
import json
from pathlib import Path
import re

from editions import ROOT
from port_patches import contract_path, legacy_ui_branch, load_contract, source_digest


def refresh_identity_anchors(source, patches):
    """Keep all real ABI replacements fail-closed; refresh only a unique, complete identity body."""
    text = legacy_ui_branch(source.replace(b"\r\n", b"\n"), True).decode("utf-8")
    result = copy.deepcopy(patches)
    for index, patch in enumerate(result):
        before = patch["old"]
        marker = "/* REFRESH_LAYOUT_" + str(index) + " */"
        if text.count(before) == patch["count"]:
            text = text.replace(before, marker)
            continue
        declaration = before.split("\n", 1)[0]
        if (before != patch["new"] or patch["count"] != 1 or
                not re.fullmatch(r"(?:static )?(?:void|int|float|uint32_t) \w+\([^\n;{}]*\)", declaration) or
                not before.startswith(declaration + "\n{\n") or before.count("\n}") != 1):
            raise ValueError("Changed non-identity/partial layout anchor: " + declaration)
        start_marker = declaration + "\n{\n"
        if text.count(start_marker) != 1:
            raise ValueError("Missing or ambiguous layout function: " + declaration)
        start = text.index(start_marker)
        end = text.find("\n}", start)
        if end < 0:
            raise ValueError("Missing layout function end: " + declaration)
        end += 2
        if before.endswith("\n"):
            end += 1
        patch["old"] = patch["new"] = text[start:end]
        text = text.replace(patch["old"], marker)
    return result


def refresh(root=ROOT, apply=False, additions=()):
    root = Path(root)
    pending = []
    for edition in ("toe", "vanilla", "hof"):
        data = load_contract(edition, root)
        before = copy.deepcopy(data)
        for feature, relative in additions:
            if feature not in data["features"] or not (root / relative).is_file():
                raise ValueError("Invalid feature/source: " + feature + "=" + relative)
            data["sources"].setdefault(relative, "")
            if relative not in data["features"][feature]:
                data["features"][feature].append(relative)
        for relative in data["sources"]:
            data["sources"][relative] = source_digest(root / relative)
        if edition != "toe":
            for relative, patches in data.get("layout_patches", {}).items():
                data["layout_patches"][relative] = refresh_identity_anchors((root / relative).read_bytes(), patches)
        changed = [p for p, digest in data["sources"].items() if before["sources"].get(p) != digest]
        anchors = sum(a != b for p, patches in data.get("layout_patches", {}).items()
                      for a, b in zip(patches, before.get("layout_patches", {}).get(p, ())))
        print(edition + ": " + str(len(changed)) + " changed source pins; " + str(anchors) + " refreshed identity anchors")
        for path in changed:
            print("  " + path)
        if data != before:
            pending.append((contract_path(edition, root), json.dumps(data, indent=2) + "\n"))
    # Validate every contract first. A later ABI-anchor failure cannot partially update earlier editions.
    if apply:
        for path, contents in pending:
            part = path.with_suffix(path.suffix + ".tmp")
            part.write_text(contents, encoding="utf-8", newline="\n")
            part.replace(path)
    elif pending:
        print("Dry run only. Review the diff, then use --apply. Rebuild every engine normally for new receipts.")
    return len(pending)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--add-source", action="append", default=[], metavar="FEATURE=RELATIVE_PATH")
    args = parser.parse_args()
    additions = []
    for item in args.add_source:
        if "=" not in item:
            parser.error("--add-source expects FEATURE=RELATIVE_PATH")
        additions.append(tuple(item.split("=", 1)))
    refresh(apply=args.apply, additions=additions)


if __name__ == "__main__":
    main()
