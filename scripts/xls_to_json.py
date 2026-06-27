#!/usr/bin/env python3
"""Convert the Abbots Langley tithe-award .xls into plots.json keyed by plot number.

Source sheet 'Occupiers_pp19-57'. Column map (0-based), confirmed from the file:
  0 Landowners | 1 Occupiers | 2 Numbers referring to the Plan
  3 Name/Description | 4 State of Cultivation | 5/6/7 Acres/Roods/Perches
  14 Remarks
Owners/occupiers carry down: a blank means "same as the row above".

Usage: python3 scripts/xls_to_json.py award.xls data/plots.json
"""
import json
import sys

import xlrd  # ponytail: .xls is BIFF, openpyxl can't read it; xlrd 2.x is the stdlib-grade choice


def num(cell):
    """Excel stores integers as floats ('402.0'). Render whole numbers cleanly, keep text as-is."""
    s = str(cell).strip()
    if s.endswith(".0"):
        s = s[:-2]
    return s


def parse(xls_path):
    book = xlrd.open_workbook(xls_path)
    sh = book.sheet_by_name("Occupiers_pp19-57")
    plots = {}
    owner = occupier = ""
    for r in range(3, sh.nrows):  # rows 0-2 are header/units
        row = [sh.cell_value(r, c) for c in range(sh.ncols)]
        if str(row[0]).strip():
            owner = str(row[0]).strip()
        if str(row[1]).strip():
            occupier = str(row[1]).strip()
        plot = num(row[2])
        name = str(row[3]).strip()
        if not plot or plot == " " or not name:
            continue
        plots[plot] = {
            "owner": owner,
            "occupier": occupier,
            "name": name,
            "use": str(row[4]).strip(),
            "acres": num(row[5]),
            "roods": num(row[6]),
            "perches": num(row[7]),
            "remarks": str(row[14]).strip() if sh.ncols > 14 else "",
        }
    return plots


def _selfcheck():
    """Smallest check that fails if parsing breaks. Needs the .xls in scratchpad."""
    import os
    sample = os.path.join(os.path.dirname(__file__), "..", "award.xls")
    if not os.path.exists(sample):
        print("selfcheck skipped: award.xls not found next to repo root")
        return
    p = parse(sample)
    assert 1000 < len(p) < 1300, f"unexpected plot count {len(p)}"
    assert p["402"]["name"] == "Spurr Field", p["402"]
    assert p["595"]["name"] == "Meadow", p["595"]
    print(f"selfcheck OK: {len(p)} plots")


if __name__ == "__main__":
    if len(sys.argv) == 1:
        _selfcheck()
    elif len(sys.argv) == 3:
        plots = parse(sys.argv[1])
        with open(sys.argv[2], "w") as f:
            json.dump(plots, f, ensure_ascii=False, separators=(",", ":"))
        print(f"wrote {len(plots)} plots to {sys.argv[2]}")
    else:
        print(__doc__)
        sys.exit(1)
