#!/usr/bin/env python3
"""
build_worksheet.py -- turn a consolidated capital-gains ledger into the exact
numbers ITR-2 asks for (FY 2025-26 / AY 2026-27).

Reads a normalised CSV, then:
  * classifies every row as 111A / 112A / 50AA slab STCG / other LTCG / buyback
  * applies s.112A grandfathering using the 31-Jan-2018 FMV
  * applies the Rs 1,25,000 s.112A exemption ONCE, across all sources
  * emits the Schedule 112A scrip-wise table
  * emits the Schedule CG Table F quarter-wise split (positives only)
  * emits a capital_gains block ready to paste into compute_tax.py's input

Usage:
    python build_worksheet.py ledger.csv --outdir work/

Input columns (see assets/ledger_template.csv):
    source, isin, name, asset_class, quantity, buy_date, sale_date,
    buy_value, sale_value, fmv_31jan2018_per_unit, expenses

asset_class must be one of:
    equity_listed  equity_mf  debt_mf  gold_intl_mf  hybrid_other
    unlisted  property  buyback

Dates are ISO (YYYY-MM-DD). Values are rupees, not lakhs.
"""

import argparse
import csv
import json
import sys
from datetime import date, datetime

EXEMPT_112A = 125000
GRANDFATHER_CUTOFF = date(2018, 1, 31)
SPECIFIED_MF_CUTOFF = date(2023, 4, 1)   # s.50AA applies to units bought on/after

VALID_CLASSES = {"equity_listed", "equity_mf", "debt_mf", "gold_intl_mf",
                 "hybrid_other", "unlisted", "property", "buyback"}

QUARTERS = [
    ("Q1  01-Apr to 15-Jun", (4, 1), (6, 15)),
    ("Q2  16-Jun to 15-Sep", (6, 16), (9, 15)),
    ("Q3  16-Sep to 15-Dec", (9, 16), (12, 15)),
    ("Q4  16-Dec to 15-Mar", (12, 16), (3, 15)),
    ("Q5  16-Mar to 31-Mar", (3, 16), (3, 31)),
]


def parse_date(s):
    s = (s or "").strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d-%b-%Y", "%d %b %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unparseable date: {s!r}")


def num(s):
    s = str(s or "0").replace(",", "").replace("\u20b9", "").strip()
    return float(s) if s else 0.0


def months_held(buy, sale):
    m = (sale.year - buy.year) * 12 + (sale.month - buy.month)
    if sale.day < buy.day:
        m -= 1
    return m


def quarter_of(d):
    """Map a sale date to the Schedule CG Table F quarter (0-indexed)."""
    md = (d.month, d.day)
    if (4, 1) <= md <= (6, 15):
        return 0
    if (6, 16) <= md <= (9, 15):
        return 1
    if (9, 16) <= md <= (12, 15):
        return 2
    if md >= (12, 16) or md <= (3, 15):
        return 3
    return 4  # 16-Mar to 31-Mar


def classify(row, warnings):
    """Return (bucket, gain, detail) for one ledger row."""
    cls = row["asset_class"]
    buy, sale = row["buy_date"], row["sale_date"]
    cost, proceeds, exp = row["buy_value"], row["sale_value"], row["expenses"]
    held = months_held(buy, sale)

    if cls == "buyback":
        # From 01-Oct-2024 the proceeds are a deemed dividend under s.2(22)(f)
        # and go to Schedule OS. Sale consideration in Schedule CG is NIL, so
        # the whole cost becomes a capital loss.
        bucket = "buyback_ltcl" if held > 12 else "buyback_stcl"
        warnings.append(
            f"{row['name']}: buyback -- Rs {proceeds:,.0f} must be reported as "
            f"deemed dividend in Schedule OS, and the loss of Rs {cost:,.0f} is "
            f"only allowed if you do report it.")
        return bucket, -cost, "buyback: nil consideration, cost = capital loss"

    if cls in ("equity_listed", "equity_mf"):
        gain = proceeds - cost - exp
        if held > 12:
            return "ltcg_112a", gain, f"LT ({held}m) -> s.112A @ 12.5%"
        return "stcg_111a", gain, f"ST ({held}m) -> s.111A @ 20%"

    if cls == "debt_mf":
        if buy >= SPECIFIED_MF_CUTOFF:
            return ("stcg_slab", proceeds - cost - exp,
                    "s.50AA specified MF bought on/after 01-Apr-2023 -> "
                    "always STCG at slab, whatever the holding period")
        gain = proceeds - cost - exp
        if held > 24:
            return "ltcg_other", gain, f"LT ({held}m), pre-Apr-2023 units -> 12.5%"
        return "stcg_slab", gain, f"ST ({held}m) -> slab"

    if cls == "gold_intl_mf":
        gain = proceeds - cost - exp
        warnings.append(
            f"{row['name']}: gold/international fund. From FY 2025-26 the s.50AA "
            f"definition changed to '>65% debt', so these funds are usually OUTSIDE "
            f"50AA now and get normal treatment. Confirm the scheme's actual asset "
            f"allocation before relying on this.")
        if held > 24:
            return "ltcg_other", gain, f"LT ({held}m) -> 12.5%"
        return "stcg_slab", gain, f"ST ({held}m) -> slab"

    if cls in ("unlisted", "property"):
        gain = proceeds - cost - exp
        if held > 24:
            return "ltcg_other", gain, f"LT ({held}m) -> 12.5%, no indexation"
        return "stcg_slab", gain, f"ST ({held}m) -> slab"

    if cls == "hybrid_other":
        warnings.append(
            f"{row['name']}: hybrid fund -- classification depends on the actual "
            f"equity/debt split. >=65% equity behaves like equity (111A/112A); "
            f">65% debt falls under 50AA; anything in between gets normal "
            f"treatment. Left as 'unclassified'. Resolve this before filing.")
        return "unclassified", proceeds - cost - exp, "NEEDS MANUAL CLASSIFICATION"

    raise ValueError(f"unknown asset_class {cls!r}")


def grandfather(row):
    """
    s.112A cost for units held on 31-Jan-2018:
        cost = higher of (actual cost, lower of (FMV on 31-Jan-2018, sale value))
    Returns (cost_to_use, applied?)
    """
    if row["buy_date"] > GRANDFATHER_CUTOFF:
        return row["buy_value"], False
    fmv_unit = row["fmv_31jan2018_per_unit"]
    if not fmv_unit:
        return row["buy_value"], False
    fmv_total = fmv_unit * row["quantity"]
    cost = max(row["buy_value"], min(fmv_total, row["sale_value"]))
    return cost, True


def load(path):
    rows = []
    with open(path, newline="") as f:
        for i, r in enumerate(csv.DictReader(f), start=2):
            if not (r.get("isin") or r.get("name")):
                continue
            cls = (r.get("asset_class") or "").strip().lower()
            if cls not in VALID_CLASSES:
                sys.exit(f"row {i}: asset_class {cls!r} not one of "
                         f"{sorted(VALID_CLASSES)}")
            rows.append({
                "source": (r.get("source") or "").strip(),
                "isin": (r.get("isin") or "").strip().upper(),
                "name": (r.get("name") or "").strip(),
                "asset_class": cls,
                "quantity": num(r.get("quantity")),
                "buy_date": parse_date(r.get("buy_date")),
                "sale_date": parse_date(r.get("sale_date")),
                "buy_value": num(r.get("buy_value")),
                "sale_value": num(r.get("sale_value")),
                "fmv_31jan2018_per_unit": num(r.get("fmv_31jan2018_per_unit")),
                "expenses": num(r.get("expenses")),
            })
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("ledger")
    ap.add_argument("--outdir", default=".")
    args = ap.parse_args()

    rows = load(args.ledger)
    warnings = []
    buckets = {k: 0.0 for k in ("stcg_111a", "ltcg_112a", "stcg_slab",
                                "ltcg_other", "buyback_stcl", "buyback_ltcl",
                                "unclassified")}
    sched112a = []
    quarters_111a = [0.0] * 5
    quarters_112a = [0.0] * 5
    detail = []
    total_consideration = 0.0

    for r in rows:
        # grandfathering only bites for 112A-eligible equity
        gf_applied = False
        if r["asset_class"] in ("equity_listed", "equity_mf"):
            cost, gf_applied = grandfather(r)
            r = dict(r, buy_value=cost)

        bucket, gain, why = classify(r, warnings)
        buckets[bucket] += gain
        total_consideration += r["sale_value"]
        q = quarter_of(r["sale_date"])
        if bucket == "stcg_111a":
            quarters_111a[q] += gain
        elif bucket == "ltcg_112a":
            quarters_112a[q] += gain
            sched112a.append({
                "ShareOnOrBefore": "BE" if r["buy_date"] <= GRANDFATHER_CUTOFF else "AE",
                "ISINCode": r["isin"],
                "NameofShareUnit": r["name"],
                "NumSharesUnits": r["quantity"],
                "SalePricePerShareUnit": round(r["sale_value"] / r["quantity"], 2)
                    if r["quantity"] else 0,
                "TotSaleValue": round(r["sale_value"], 2),
                "CostAcqWithoutIndx": round(r["buy_value"], 2),
                "AcquisitionCost": round(r["buy_value"], 2),
                "FairMktValuePerShareunit": r["fmv_31jan2018_per_unit"],
                "TotFairMktValueCapAst": round(
                    r["fmv_31jan2018_per_unit"] * r["quantity"], 2),
                "ExpExclCnctTransfer": round(r["expenses"], 2),
                "Balance": round(gain, 2),
            })
        detail.append({**{k: (v.isoformat() if isinstance(v, date) else v)
                          for k, v in r.items()},
                       "bucket": bucket, "gain": round(gain, 2),
                       "treatment": why, "grandfathered": gf_applied})

    # s.112A exemption -- applied once, across every broker and AMC
    ltcg_112a_gross = buckets["ltcg_112a"]
    exempt = min(max(0.0, ltcg_112a_gross), EXEMPT_112A)
    ltcg_112a_taxable = max(0.0, ltcg_112a_gross - EXEMPT_112A)

    cg_block = {
        "stcg_111a": round(buckets["stcg_111a"], 2),
        "ltcg_112a": round(ltcg_112a_gross, 2),
        "stcg_slab": round(buckets["stcg_slab"], 2),
        "ltcg_other_12_5": round(buckets["ltcg_other"], 2),
    }

    # Table F -- the utility rejects negatives, so clamp and note the difference
    def clamp(qs):
        out = [max(0.0, x) for x in qs]
        return out, round(sum(qs), 2), round(sum(out), 2)

    q111, t111, c111 = clamp(quarters_111a)
    q112, t112, c112 = clamp(quarters_112a)

    out = {
        "capital_gains": cg_block,
        "ltcg_112a_exemption_applied": round(exempt, 2),
        "ltcg_112a_taxable": round(ltcg_112a_taxable, 2),
        "buyback_capital_loss_stcl": round(-buckets["buyback_stcl"], 2) + 0.0,
        "buyback_capital_loss_ltcl": round(-buckets["buyback_ltcl"], 2) + 0.0,
        "unclassified_gain": round(buckets["unclassified"], 2),
        "total_sale_consideration": round(total_consideration, 2),
        "table_f_111a": {QUARTERS[i][0]: round(q111[i], 2) for i in range(5)},
        "table_f_112a": {QUARTERS[i][0]: round(q112[i], 2) for i in range(5)},
        "schedule_112a_rows": sched112a,
        "warnings": warnings,
    }

    import os
    os.makedirs(args.outdir, exist_ok=True)
    with open(os.path.join(args.outdir, "worksheet.json"), "w") as f:
        json.dump(out, f, indent=2)
    with open(os.path.join(args.outdir, "ledger_classified.csv"), "w",
              newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(detail[0].keys()))
        w.writeheader()
        w.writerows(detail)
    if sched112a:
        with open(os.path.join(args.outdir, "schedule_112a.csv"), "w",
                  newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(sched112a[0].keys()))
            w.writeheader()
            w.writerows(sched112a)

    # ---- console summary
    print("=" * 66)
    print("  CAPITAL GAINS WORKSHEET -- FY 2025-26 / AY 2026-27")
    print("=" * 66)
    print(f"  Rows processed                    {len(rows):>12}")
    print(f"  Total sale consideration          {total_consideration:>12,.0f}")
    print("    ^ tie this to AIS 'Sale of securities and units of mutual fund'.")
    print("      AIS reports consideration, NOT gain, so it will never match P&L.")
    print("-" * 66)
    print(f"  STCG u/s 111A (equity, 20%)       {cg_block['stcg_111a']:>12,.0f}")
    print(f"  LTCG u/s 112A gross               {cg_block['ltcg_112a']:>12,.0f}")
    print(f"    less exemption                  {exempt:>12,.0f}")
    print(f"    taxable at 12.5%                {ltcg_112a_taxable:>12,.0f}")
    print(f"  STCG at slab (50AA / debt / other){cg_block['stcg_slab']:>12,.0f}")
    print(f"  Other LTCG at 12.5%               {cg_block['ltcg_other_12_5']:>12,.0f}")
    if buckets["buyback_stcl"] or buckets["buyback_ltcl"]:
        print(f"  Buyback STCL                      {abs(buckets['buyback_stcl']):>12,.0f}")
        print(f"  Buyback LTCL                      {abs(buckets['buyback_ltcl']):>12,.0f}")
    if buckets["unclassified"]:
        print(f"  UNCLASSIFIED (resolve!)           {buckets['unclassified']:>12,.0f}")
    print("-" * 66)
    print("  Table F -- quarter-wise, s.111A")
    for i, (label, _, _) in enumerate(QUARTERS):
        print(f"    {label:26}{q111[i]:>12,.0f}")
    if abs(c111 - t111) > 0.5:
        print(f"    net across quarters {t111:,.0f} but negatives were clamped to 0;")
        print(f"    redistribute so the quarters sum to the Schedule CG figure.")
    print("  Table F -- quarter-wise, s.112A")
    for i, (label, _, _) in enumerate(QUARTERS):
        print(f"    {label:26}{q112[i]:>12,.0f}")
    print("=" * 66)
    if warnings:
        print("\nWarnings:")
        for w in warnings:
            print(f"  * {w}")
    print(f"\nWritten to {args.outdir}/: worksheet.json, ledger_classified.csv"
          + (", schedule_112a.csv" if sched112a else ""))


if __name__ == "__main__":
    main()
