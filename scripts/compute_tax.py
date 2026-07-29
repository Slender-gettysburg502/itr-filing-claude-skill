#!/usr/bin/env python3
"""
compute_tax.py -- FY 2025-26 (AY 2026-27) tax computation for an individual
with salary, capital gains and other-sources income.

Computes both regimes side by side and reports which is cheaper.

Usage:
    python compute_tax.py input.json                 # human-readable summary
    python compute_tax.py input.json --json out.json # machine-readable too

See assets/taxpayer_input_template.json for the input shape.

Everything here follows the rules in references/tax-rules-fy2025-26.md.
If you change a rate, change it there too.
"""

import json
import sys
from datetime import date

# ---------------------------------------------------------------- constants

NEW_SLABS = [(400000, 0.00), (800000, 0.05), (1200000, 0.10),
             (1600000, 0.15), (2000000, 0.20), (2400000, 0.25),
             (float("inf"), 0.30)]

OLD_SLABS_BASE = [(500000, 0.05), (1000000, 0.20), (float("inf"), 0.30)]

RATE_111A = 0.20      # STCG on listed equity / equity MF (from 23-Jul-2024)
RATE_112A = 0.125     # LTCG on listed equity / equity MF
RATE_LTCG_OTHER = 0.125
EXEMPT_112A = 125000  # per-year exemption, applied once across all sources
CESS = 0.04

NEW_BEL = 400000
NEW_STD_DED = 75000
OLD_STD_DED = 50000
NEW_REBATE_LIMIT = 1200000
NEW_REBATE_MAX = 60000
OLD_REBATE_LIMIT = 500000
OLD_REBATE_MAX = 12500

DUE_DATE = date(2026, 7, 31)


def old_bel(age):
    if age >= 80:
        return 500000
    if age >= 60:
        return 300000
    return 250000


def slab_tax(income, slabs, bel):
    """Progressive tax. `bel` is the nil band; slabs are (upper_limit, rate)."""
    tax, prev = 0.0, bel
    for upper, rate in slabs:
        if income <= prev:
            break
        tax += (min(income, upper) - prev) * rate
        prev = upper
    return tax


def new_regime_slab_tax(income):
    tax, prev = 0.0, 0.0
    for upper, rate in NEW_SLABS:
        if income <= prev:
            break
        tax += (min(income, upper) - prev) * rate
        prev = upper
    return tax


# ------------------------------------------------------- exemption shortfall

def apply_bel_shortfall(normal_income, bel, special, resident):
    """
    A *resident* whose normal income falls short of the basic exemption limit
    may set the unused slice against special-rate capital gains (first proviso
    to s.111A / s.112A). Available in BOTH regimes. NRIs cannot.

    We consume the shortfall against the highest-taxed bucket first, which is
    what a taxpayer would rationally elect.
    """
    special = dict(special)
    if not resident:
        return special, 0.0
    shortfall = max(0.0, bel - normal_income)
    if shortfall <= 0:
        return special, 0.0
    used = 0.0
    for key in ("stcg_111a", "ltcg_112a_taxable", "ltcg_other"):
        if shortfall <= 0:
            break
        take = min(shortfall, special.get(key, 0.0))
        special[key] = special.get(key, 0.0) - take
        shortfall -= take
        used += take
    return special, used


# -------------------------------------------------------------- surcharge

def surcharge(total_income, tax_normal, tax_special, regime):
    """
    Slab surcharge on total income. Surcharge on the tax attributable to
    111A/112A gains and dividends is capped at 15%; the new regime caps the
    top rate at 25%.
    Returns (surcharge_amount, rate_applied).
    """
    if total_income <= 5000000:
        return 0.0, 0.0
    if total_income <= 10000000:
        r = 0.10
    elif total_income <= 20000000:
        r = 0.15
    else:
        r = 0.25 if regime == "new" else (0.25 if total_income <= 50000000 else 0.37)
    r_special = min(r, 0.15)
    return tax_normal * r + tax_special * r_special, r


# ------------------------------------------------------------- core compute

def compute(data, regime):
    resident = data.get("resident", True)
    age = data.get("age", 30)

    salary_gross = float(data.get("salary_gross", 0))
    exempt_allow = float(data.get("exempt_allowances_old", 0))
    prof_tax = float(data.get("professional_tax", 0))

    os_items = data.get("income_other_sources", {})
    os_total = sum(float(v) for v in os_items.values())
    hp = float(data.get("house_property_income", 0))

    cg = data.get("capital_gains", {})
    stcg_111a = float(cg.get("stcg_111a", 0))
    ltcg_112a_gross = float(cg.get("ltcg_112a", 0))
    stcg_slab = float(cg.get("stcg_slab", 0))     # 50AA / debt MF / unlisted STCG
    ltcg_other = float(cg.get("ltcg_other_12_5", 0))

    ltcg_112a_taxable = max(0.0, ltcg_112a_gross - EXEMPT_112A)

    notes = []

    # --- salary head
    if regime == "new":
        std_ded = min(NEW_STD_DED, salary_gross)
        salary_net = max(0.0, salary_gross - std_ded)
        if exempt_allow:
            notes.append("HRA/LTA and other exempt allowances are NOT available "
                         "in the new regime; ignored here.")
    else:
        std_ded = min(OLD_STD_DED, salary_gross)
        salary_net = max(0.0, salary_gross - exempt_allow - std_ded - prof_tax)

    # --- gross total income
    gti_normal = salary_net + hp + os_total + stcg_slab
    gti = gti_normal + stcg_111a + ltcg_112a_taxable + ltcg_other

    # --- Chapter VI-A
    ded_both = data.get("deductions_both", {})       # 80CCD(2), 80CCH
    ded_old = data.get("deductions_old", {})         # 80C, 80D, 80TTA...
    if regime == "new":
        vi_a = sum(float(v) for v in ded_both.values())
    else:
        vi_a = sum(float(v) for v in ded_both.values()) + \
               sum(float(v) for v in ded_old.values())
    # Chapter VI-A cannot be set against special-rate capital gains.
    vi_a = min(vi_a, gti_normal)

    normal_income = max(0.0, gti_normal - vi_a)
    total_income = normal_income + stcg_111a + ltcg_112a_taxable + ltcg_other
    total_income_rounded = round(total_income / 10) * 10

    # --- basic exemption shortfall against special-rate gains
    bel = NEW_BEL if regime == "new" else old_bel(age)
    special, shortfall_used = apply_bel_shortfall(
        normal_income, bel,
        {"stcg_111a": stcg_111a,
         "ltcg_112a_taxable": ltcg_112a_taxable,
         "ltcg_other": ltcg_other},
        resident)
    if shortfall_used:
        notes.append(f"Unused basic exemption of Rs {shortfall_used:,.0f} set "
                     f"against special-rate gains (resident, both regimes).")
    elif not resident:
        notes.append("Non-resident: basic-exemption shortfall CANNOT be set "
                     "against 111A/112A gains.")

    # --- tax on each bucket
    if regime == "new":
        tax_normal = new_regime_slab_tax(normal_income)
    else:
        tax_normal = slab_tax(normal_income, OLD_SLABS_BASE, bel)

    tax_111a = special["stcg_111a"] * RATE_111A
    tax_112a = special["ltcg_112a_taxable"] * RATE_112A
    tax_ltcg_other = special["ltcg_other"] * RATE_LTCG_OTHER
    tax_special = tax_111a + tax_112a + tax_ltcg_other

    # --- s.87A rebate
    rebate = 0.0
    rebate_note = ""
    if regime == "new":
        if total_income <= NEW_REBATE_LIMIT:
            # Rebate is NOT allowed against tax on 112A LTCG. The e-filing
            # utility has also been disallowing it against 111A STCG, so we
            # take the conservative view and grant it only on normal-rate tax.
            rebate = min(NEW_REBATE_MAX, tax_normal)
            if tax_special > 0:
                rebate_note = ("Rebate applied to normal-rate tax only. Tax on "
                               "111A/112A gains is NOT rebated -- this is the "
                               "conservative reading the utility enforces.")
    else:
        if total_income <= OLD_REBATE_LIMIT:
            # Old regime: rebate barred against 112A, allowed against 111A.
            rebate = min(OLD_REBATE_MAX, tax_normal + tax_111a)
            if tax_112a > 0:
                rebate_note = "Rebate not allowed against 112A LTCG."

    tax_after_rebate = max(0.0, tax_normal + tax_special - rebate)

    # --- marginal relief at the 12 lakh rebate cliff (new regime)
    marginal_relief = 0.0
    if regime == "new" and NEW_REBATE_LIMIT < total_income:
        excess = total_income - NEW_REBATE_LIMIT
        # Only the normal-rate tax participates in the rebate, so relief is
        # measured against that component.
        if tax_normal > excess and total_income - stcg_111a - \
                special["ltcg_112a_taxable"] - special["ltcg_other"] <= \
                NEW_REBATE_LIMIT + excess:
            marginal_relief = max(0.0, tax_normal - excess)
            marginal_relief = min(marginal_relief, tax_normal)
            tax_after_rebate = max(0.0, tax_after_rebate - marginal_relief)
            notes.append(f"Marginal relief of Rs {marginal_relief:,.0f} applied "
                         f"just above the Rs 12,00,000 rebate threshold.")

    # --- surcharge + cess
    sur, sur_rate = surcharge(total_income, max(0.0, tax_normal - rebate),
                              tax_special, regime)
    if total_income > 5000000:
        notes.append(f"Surcharge at {sur_rate:.0%} applies (capped at 15% on "
                     f"111A/112A). Income above Rs 50 lakh -- have a CA review.")
    cess_amt = (tax_after_rebate + sur) * CESS
    total_tax = tax_after_rebate + sur + cess_amt

    paid = data.get("taxes_paid", {})
    tds = sum(float(v) for v in paid.values())

    return {
        "regime": regime,
        "salary_net": salary_net,
        "standard_deduction": std_ded,
        "other_sources": os_total,
        "house_property": hp,
        "stcg_slab_rate": stcg_slab,
        "chapter_via": vi_a,
        "normal_income": normal_income,
        "stcg_111a": stcg_111a,
        "ltcg_112a_gross": ltcg_112a_gross,
        "ltcg_112a_exempt": min(ltcg_112a_gross, EXEMPT_112A),
        "ltcg_112a_taxable": ltcg_112a_taxable,
        "ltcg_other": ltcg_other,
        "total_income": total_income,
        "total_income_rounded": total_income_rounded,
        "basic_exemption": bel,
        "bel_shortfall_used": shortfall_used,
        "tax_normal": tax_normal,
        "tax_111a": tax_111a,
        "tax_112a": tax_112a,
        "tax_ltcg_other": tax_ltcg_other,
        "rebate_87a": rebate,
        "rebate_note": rebate_note,
        "marginal_relief": marginal_relief,
        "surcharge": sur,
        "cess": cess_amt,
        "total_tax": round(total_tax / 10) * 10,
        "taxes_paid": tds,
        "balance": round((total_tax - tds) / 10) * 10,
        "notes": notes,
    }


# ------------------------------------------------------- 234B / 234C interest

def interest_234(result, data):
    """
    234B: 1%/month from 1-Apr on the shortfall, if advance tax paid < 90% of
          assessed tax.
    234C: 1%/month for deferment of each installment. Capital gains are
          exempted from earlier installments -- the liability attaches only
          from the installment falling due after the gain arose, which is why
          Schedule CG Table F exists.
    """
    assessed = result["total_tax"]
    paid = data.get("taxes_paid", {})
    tds = float(paid.get("tds", 0))
    advance = float(paid.get("advance_tax", 0))
    assessed_net = max(0.0, assessed - tds)

    out = {"234B": 0.0, "234C": 0.0, "detail": []}
    if assessed_net < 10000:
        out["detail"].append("Advance tax not payable (liability after TDS "
                             "below Rs 10,000). No 234B/234C.")
        return out

    # 234B
    if advance < 0.9 * assessed_net:
        shortfall = (assessed_net - advance)
        shortfall = int(shortfall / 100) * 100
        filing = data.get("filing_date")
        months = 4  # Apr -> Jul, the usual case for a 31-Jul filing
        if filing:
            fd = date.fromisoformat(filing)
            months = max(1, (fd.year - 2026) * 12 + fd.month - 4 + 1)
        out["234B"] = shortfall * 0.01 * months
        out["detail"].append(
            f"234B: advance tax Rs {advance:,.0f} is below 90% of "
            f"Rs {assessed_net:,.0f}. 1% x {months} months on Rs {shortfall:,.0f}.")

    # 234C -- capital-gains carve-out
    q = data.get("cg_quarters", {})
    cg_total = sum(float(v) for v in q.values()) if q else 0.0
    if cg_total:
        out["detail"].append(
            "234C: capital gains are excluded from installments falling due "
            "BEFORE the gain arose. Feed the quarter-wise split from "
            "build_worksheet.py so the deferment is computed on the right base.")
    out["detail"].append(
        "234C is installment-specific and depends on dates of actual advance-tax "
        "payments. Let the e-filing utility compute it and compare.")
    return out


# ----------------------------------------------------------------- reporting

def rupees(x):
    return f"{x:>14,.0f}"


def report(new, old, data, interest_new, interest_old):
    lines = []
    a = lines.append
    a("=" * 68)
    a("  ITR-2 TAX COMPUTATION -- FY 2025-26 / AY 2026-27")
    a("=" * 68)
    a("")
    a(f"{'':38}{'NEW regime':>14}{'OLD regime':>14}")
    a("-" * 68)

    rows = [
        ("Salary (net of standard deduction)", "salary_net"),
        ("House property", "house_property"),
        ("Other sources (interest, dividend)", "other_sources"),
        ("STCG taxed at slab (debt MF etc.)", "stcg_slab_rate"),
        ("Less: Chapter VI-A deductions", "chapter_via"),
        ("= Normal-rate income", "normal_income"),
        ("STCG u/s 111A @ 20%", "stcg_111a"),
        ("LTCG u/s 112A (gross)", "ltcg_112a_gross"),
        ("  less exemption", "ltcg_112a_exempt"),
        ("LTCG u/s 112A (taxable)", "ltcg_112a_taxable"),
        ("Other LTCG @ 12.5%", "ltcg_other"),
        ("= TOTAL INCOME", "total_income_rounded"),
    ]
    for label, key in rows:
        a(f"{label:38}{rupees(new[key])}{rupees(old[key])}")
    a("-" * 68)
    tax_rows = [
        ("Tax on normal income", "tax_normal"),
        ("Tax on 111A STCG", "tax_111a"),
        ("Tax on 112A LTCG", "tax_112a"),
        ("Tax on other LTCG", "tax_ltcg_other"),
        ("Less: rebate u/s 87A", "rebate_87a"),
        ("Less: marginal relief", "marginal_relief"),
        ("Surcharge", "surcharge"),
        ("Health & education cess @ 4%", "cess"),
        ("= TOTAL TAX", "total_tax"),
        ("Less: TDS / advance / self-assessment", "taxes_paid"),
        ("= BALANCE PAYABLE / (REFUND)", "balance"),
    ]
    for label, key in tax_rows:
        a(f"{label:38}{rupees(new[key])}{rupees(old[key])}")
    a("=" * 68)

    cheaper = "NEW" if new["total_tax"] <= old["total_tax"] else "OLD"
    diff = abs(new["total_tax"] - old["total_tax"])
    a(f"  RECOMMENDED: {cheaper} regime  (saves Rs {diff:,.0f})")
    if cheaper == "OLD":
        a("  The old regime is not the default. Choose it inside the ITR before")
        a("  the 31-Jul-2026 due date. Form 10-IEA is NOT required for a filer")
        a("  with only salary, capital gains and interest.")
    a("=" * 68)

    for label, res, intr in (("NEW", new, interest_new), ("OLD", old, interest_old)):
        msgs = res["notes"] + ([res["rebate_note"]] if res["rebate_note"] else []) \
               + intr["detail"]
        if msgs:
            a("")
            a(f"Notes -- {label} regime:")
            for m in msgs:
                a(f"  * {m}")
        if intr["234B"]:
            a(f"  * Estimated 234B interest: Rs {intr['234B']:,.0f}")

    a("")
    a("Cross-check the final numbers against the e-filing utility's own")
    a("computation before you upload. If they differ, the input classification")
    a("is wrong somewhere -- do not override the utility.")
    return "\n".join(lines)


def main():
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    with open(sys.argv[1]) as f:
        data = json.load(f)

    new = compute(data, "new")
    old = compute(data, "old")
    i_new = interest_234(new, data)
    i_old = interest_234(old, data)

    print(report(new, old, data, i_new, i_old))

    if "--json" in sys.argv:
        out = sys.argv[sys.argv.index("--json") + 1]
        with open(out, "w") as f:
            json.dump({"new_regime": new, "old_regime": old,
                       "interest_new": i_new, "interest_old": i_old}, f, indent=2)
        print(f"\nMachine-readable output written to {out}")


if __name__ == "__main__":
    main()
