#!/usr/bin/env python3
"""
patch_prefill_json.py -- inspect and edit the pre-filled ITR-2 JSON downloaded
from the e-filing portal.

Why this exists: hand-building an ITR JSON from scratch fails validation far
more often than it works, because the schema changes every assessment year and
the node names are inconsistent (PartB-TI has a hyphen, PartB_TTI an
underscore). Starting from the portal's own pre-filled JSON inherits a correct
CreationInfo, Form_ITR2 and SchemaVer, so only the values need changing.

Because node names shift between utility versions, this tool DISCOVERS the
paths in your actual file rather than assuming them.

    # 1. See what schedules and keys your file actually contains
    python patch_prefill_json.py prefill.json --inspect

    # 2. Find where a value lives, by key name or by current value
    python patch_prefill_json.py prefill.json --find 112A
    python patch_prefill_json.py prefill.json --find-value 50880

    # 3. Set values, with a dry run first
    python patch_prefill_json.py prefill.json \\
        --set ITR.ITR2.ScheduleCGFor23.LongTermCapGain23.SaleOfEquityShareUs112A.LTCGWithoutBenefit=50880 \\
        --dry-run

    # 4. Write the result
    python patch_prefill_json.py prefill.json --set <path>=<value> -o filled.json

    # 5. Load a Schedule 112A table produced by build_worksheet.py
    python patch_prefill_json.py prefill.json \\
        --set-112a work/schedule_112a.csv -o filled.json

ALWAYS import the result into the official offline utility, let it validate and
recompute, and fix whatever it flags. This script does not validate against the
schema; only the utility can do that.
"""

import argparse
import copy
import csv
import json
import sys


def walk(node, path=""):
    """Yield (path, value) for every leaf and container in the tree."""
    if isinstance(node, dict):
        for k, v in node.items():
            p = f"{path}.{k}" if path else k
            yield p, v
            yield from walk(v, p)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            p = f"{path}[{i}]"
            yield p, v
            yield from walk(v, p)


def get_path(doc, path):
    cur = doc
    for part in split_path(path):
        cur = cur[part]
    return cur


def split_path(path):
    parts = []
    for chunk in path.split("."):
        while "[" in chunk:
            head, rest = chunk.split("[", 1)
            if head:
                parts.append(head)
            idx, chunk = rest.split("]", 1)
            parts.append(int(idx))
        if chunk:
            parts.append(chunk)
    return parts


def set_path(doc, path, value):
    parts = split_path(path)
    cur = doc
    for part in parts[:-1]:
        if isinstance(part, int):
            cur = cur[part]
        else:
            if part not in cur:
                raise KeyError(
                    f"{part!r} does not exist in the pre-filled JSON. "
                    f"Run --inspect or --find to see the real node names; do "
                    f"not invent them.")
            cur = cur[part]
    last = parts[-1]
    old = cur[last] if (isinstance(cur, dict) and last in cur) or \
        (isinstance(cur, list) and isinstance(last, int)) else None
    cur[last] = value
    return old


def coerce(s):
    try:
        return int(s)
    except ValueError:
        pass
    try:
        return float(s)
    except ValueError:
        pass
    if s.lower() in ("true", "false"):
        return s.lower() == "true"
    return s


def inspect(doc):
    print("Top-level structure:")
    root = doc
    for p, v in walk(doc):
        depth = p.count(".") + p.count("[")
        if depth > 2:
            continue
        kind = type(v).__name__
        size = f" ({len(v)} keys)" if isinstance(v, dict) else \
               f" ({len(v)} items)" if isinstance(v, list) else f" = {v!r}"
        print(f"  {'  ' * depth}{p.split('.')[-1]:<32} {kind}{size}")
    print("\nSchedules present:")
    for p, v in walk(doc):
        leaf = p.split(".")[-1]
        if leaf.startswith(("Schedule", "PartB", "Part_B", "Verification",
                            "FilingStatus", "PersonalInfo", "CreationInfo",
                            "Form_ITR")):
            n = f"{len(v)} keys" if isinstance(v, dict) else \
                f"{len(v)} rows" if isinstance(v, list) else str(v)
            print(f"  {p:<56} {n}")


def find(doc, needle):
    needle = needle.lower()
    hits = 0
    for p, v in walk(doc):
        if needle in p.split(".")[-1].lower():
            preview = v if not isinstance(v, (dict, list)) else \
                f"<{type(v).__name__}, {len(v)}>"
            print(f"  {p} = {preview}")
            hits += 1
    if not hits:
        print(f"  no key matching {needle!r}")


def find_value(doc, target):
    t = coerce(target)
    hits = 0
    for p, v in walk(doc):
        if isinstance(v, (int, float, str)) and v == t:
            print(f"  {p} = {v!r}")
            hits += 1
    if not hits:
        print(f"  no field currently holds {target!r}")


def load_112a(csv_path):
    rows = []
    with open(csv_path, newline="") as f:
        for r in csv.DictReader(f):
            out = {}
            for k, v in r.items():
                out[k] = coerce(v) if v not in ("", None) else 0
            rows.append(out)
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("prefill")
    ap.add_argument("--inspect", action="store_true")
    ap.add_argument("--find", metavar="KEY")
    ap.add_argument("--find-value", metavar="VALUE")
    ap.add_argument("--set", action="append", default=[], metavar="PATH=VALUE")
    ap.add_argument("--set-112a", metavar="CSV",
                    help="load a schedule_112a.csv into the Schedule112A array")
    ap.add_argument("--112a-path", default=None,
                    help="override the discovered Schedule112A node path")
    ap.add_argument("-o", "--output")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    with open(args.prefill) as f:
        doc = json.load(f)
    original = copy.deepcopy(doc)

    if args.inspect:
        inspect(doc)
        return
    if args.find:
        find(doc, args.find)
        return
    if args.find_value:
        find_value(doc, args.find_value)
        return

    changes = []
    for assignment in args.set:
        if "=" not in assignment:
            sys.exit(f"--set expects PATH=VALUE, got {assignment!r}")
        path, raw = assignment.split("=", 1)
        try:
            old = set_path(doc, path, coerce(raw))
        except (KeyError, IndexError, TypeError) as e:
            sys.exit(f"could not set {path}: {e}")
        changes.append((path, old, coerce(raw)))

    if args.set_112a:
        rows = load_112a(args.set_112a)
        path = args.__dict__["112a_path"]
        if not path:
            candidates = [p for p, v in walk(doc)
                          if p.split(".")[-1] == "Schedule112A"]
            if not candidates:
                sys.exit("No Schedule112A node found in the pre-filled JSON. "
                         "Enter one row in the utility first so the node "
                         "exists, re-download, then retry -- or pass "
                         "--112a-path explicitly.")
            path = candidates[0]
        old = set_path(doc, path, rows)
        changes.append((path, f"<{len(old) if isinstance(old, list) else 0} rows>",
                        f"<{len(rows)} rows>"))

    if not changes:
        print("Nothing to do. Try --inspect.")
        return

    print("Changes:")
    for path, old, new in changes:
        print(f"  {path}")
        print(f"      {old!r}  ->  {new!r}")

    if args.dry_run:
        print("\n(dry run -- nothing written)")
        return

    out = args.output or args.prefill.replace(".json", "_filled.json")
    if out == args.prefill:
        sys.exit("refusing to overwrite the original pre-fill; pass -o")
    with open(out, "w") as f:
        json.dump(doc, f, separators=(",", ":"))
    print(f"\nWritten to {out}")
    print("Next: import this into the official ITR-2 offline utility, let it "
          "validate and recompute, and fix anything it flags. Do not upload "
          "without that step.")


if __name__ == "__main__":
    main()
