#!/usr/bin/env python3
"""
build_itr2_json.py -- build an ITR-2 upload JSON (AY 2026-27) from a plain
input file, and validate it against the department's published schema.

    python scripts/build_itr2_json.py my_return.json -o filled.json

Start from assets/itr2_json_input_template.json. Every figure in the input is
yours to supply; nothing about a taxpayer is baked into this script.

Scope, stated plainly so you do not discover it at the wrong moment:

  * NEW regime only (s.115BAC(1A)). The old regime needs Schedule VI-A and a
    different rebate, neither of which is built here. The script refuses
    rather than guessing.
  * Salary, interest, dividends, s.111A STCG and s.112A LTCG. No house
    property, no foreign assets, no business income, no VDA, no buyback.
  * It computes tax the way references/tax-rules-fy2025-26.md describes, so
    the JSON carries a complete Part B-TTI. Treat that as a draft figure.

The output validates against schema/ITR-2_2026_Main_V1.1.json, which catches
structural errors. It cannot catch a wrong number, and passing validation is
not the same as being right. Import the result into the official offline
utility, let it recompute, and believe the utility over this script.

Note also that the portal's direct JSON upload only accepts files stamped with
a registered Software Provider ID, which this script does not have. The offline
utility is the route in. See the README.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SCHEMA = ROOT / "schema" / "ITR-2_2026_Main_V1.1.json"

EXEMPT_112A = 125000
RATE_111A = 0.20
RATE_112A = 0.125
NEW_BEL = 400000
NEW_STD_DED = 75000
REBATE_LIMIT = 1200000
REBATE_MAX = 60000
CESS = 0.04

QUARTER_KEYS = {"q1": "Upto15Of6", "q2": "Upto15Of9", "q3": "Up16Of9To15Of12",
                "q4": "Up16Of12To15Of3", "q5": "Up16Of3To31Of3"}


# ------------------------------------------------------------------ helpers

def rupees(x):
    """The schema wants integers everywhere. Round half away from zero."""
    return int(round(float(x or 0)))


def date_range(quarters=None):
    q = quarters or {}
    out = {v: rupees(q.get(k, 0)) for k, v in QUARTER_KEYS.items()}
    return {"DateRange": out}


def check_quarters(label, quarters, total, warnings):
    """Table F must sum to the schedule figure, and no quarter may be negative."""
    if not quarters:
        if total:
            warnings.append(
                f"{label}: no quarter split given, so the whole gain is parked "
                f"in Q4. Table F drives s.234C. Put it in the real quarters if "
                f"the liability is large enough for 234C to bite.")
        return {"q4": total} if total else {}
    if any(rupees(v) < 0 for v in quarters.values()):
        sys.exit(f"{label}: a negative quarter is rejected by the utility. "
                 f"Clamp losing quarters to zero and redistribute so the "
                 f"quarters still sum to {total}.")
    got = sum(rupees(v) for v in quarters.values())
    if got != rupees(total):
        sys.exit(f"{label}: quarters sum to {got}, but the schedule figure is "
                 f"{rupees(total)}. A one-rupee gap fails validation.")
    return quarters


def zero_sec94():
    """A capital-gains block the schema demands but this profile never uses."""
    return {"FullValueConsdRecvUnqshr": 0, "FairMrktValueUnqshr": 0,
            "FullValueConsdSec50CA": 0, "FullValueConsdOthUnqshr": 0,
            "FullConsideration": 0,
            "DeductSec48": {"AquisitCost": 0, "ImproveCost": 0,
                            "ExpOnTrans": 0, "TotalDedn": 0},
            "BalanceCG": 0, "LossSec94of7Or94of8": 0, "CapgainonAssets": 0}


def cyla_row(inc):
    return {"IncCYLA": {"IncOfCurYrUnderThatHead": rupees(inc),
                        "HPlossCurYrSetoff": 0,
                        "OthSrcLossNoRaceHorseSetoff": 0,
                        "IncOfCurYrAfterSetOff": rupees(inc)}}


def cyla_othsrc_row(inc):
    # Other sources uses its own row type, without the other-sources setoff
    # column. Reusing cyla_row here is an additionalProperties failure.
    return {"IncCYLA": {"IncOfCurYrUnderThatHead": rupees(inc),
                        "HPlossCurYrSetoff": 0,
                        "IncOfCurYrAfterSetOff": rupees(inc)}}


def bfla_cg_row(inc):
    return {"IncBFLA": {"IncOfCurYrUndHeadFromCYLA": rupees(inc),
                        "BFlossPrevYrUndSameHeadSetoff": 0,
                        "IncOfCurYrAfterSetOffBFLosses": rupees(inc)}}


def bfla_plain_row(inc):
    # Salary and other sources use the two-column variant.
    return {"IncBFLA": {"IncOfCurYrUndHeadFromCYLA": rupees(inc),
                        "IncOfCurYrAfterSetOffBFLosses": rupees(inc)}}


def slab_tax_new(income):
    tax, prev = 0.0, 0
    for upper, rate in ((400000, 0.00), (800000, 0.05), (1200000, 0.10),
                        (1600000, 0.15), (2000000, 0.20), (2400000, 0.25),
                        (float("inf"), 0.30)):
        if income <= prev:
            break
        tax += (min(income, upper) - prev) * rate
        prev = upper
    return tax


def load_112a_rows(path):
    rows = []
    with open(path, newline="") as f:
        for r in csv.DictReader(f):
            row = {}
            for k, v in r.items():
                if v in ("", None):
                    row[k] = 0
                    continue
                try:
                    row[k] = int(v)
                except ValueError:
                    try:
                        row[k] = float(v)
                    except ValueError:
                        row[k] = v
            rows.append(row)
    return rows


# -------------------------------------------------------------------- build

def build(cfg):
    warnings = []

    if cfg.get("regime", "new") != "new":
        sys.exit("This script builds new-regime returns only. For the old "
                 "regime, fill the return in the offline utility instead.")

    p = cfg["personal"]
    addr = p["address"]
    fil = cfg.get("filing", {})
    ver = cfg["verification"]

    # A dropped PIN is invisible in the output, so say it out loud here.
    if not addr.get("pin"):
        warnings.append(
            "No PIN code for the taxpayer's address, so the field is omitted "
            "rather than sent as 0. Add it before filing.")
    for employer in cfg.get("salary", {}).get("employers", []):
        if not employer.get("pin"):
            warnings.append(
                f"No PIN code for employer {employer.get('name', '?')!r}. The "
                f"utility rejects a blank one as \"0 is not greater or equal "
                f"to 100000\", so fill it in.")

    # --- salary
    employers = cfg.get("salary", {}).get("employers", [])
    gross_salary = sum(rupees(e.get("gross_salary", 0)) for e in employers)
    std_ded = min(NEW_STD_DED, gross_salary)
    salary_net = gross_salary - std_ded

    # --- other sources
    os_in = cfg.get("other_sources", {})
    sav = rupees(os_in.get("savings_interest", 0))
    term = rupees(os_in.get("term_deposit_interest", 0))
    oth_int = rupees(os_in.get("other_interest", 0))
    refund_int = rupees(os_in.get("income_tax_refund_interest", 0))
    dividend = rupees(os_in.get("dividend", 0))
    interest_gross = sav + term + oth_int + refund_int
    os_total = interest_gross + dividend

    div_q = os_in.get("dividend_quarters") or {}
    if dividend and div_q and sum(rupees(v) for v in div_q.values()) != dividend:
        sys.exit("Dividend quarters must sum to the gross dividend "
                 f"({dividend}); they sum to "
                 f"{sum(rupees(v) for v in div_q.values())}.")
    if dividend and not div_q:
        warnings.append("No dividend quarter split given, so it all sits in Q4. "
                        "The utility checks the quarters against gross dividend.")
        div_q = {"q4": dividend}

    # --- capital gains
    cg = cfg.get("capital_gains", {})
    st = cg.get("stcg_111a") or {}
    st_consid = rupees(st.get("consideration", 0))
    st_cost = rupees(st.get("cost", 0))
    st_exp = rupees(st.get("expenses", 0))
    stcg = st_consid - st_cost - st_exp

    lt = cg.get("ltcg_112a") or {}
    lt_gross = rupees(lt.get("gain", 0))
    lt_taxable = max(0, lt_gross - EXEMPT_112A)

    if stcg < 0 or lt_gross < 0:
        sys.exit("This script does not handle capital losses (set-off, "
                 "Schedule CYLA/CFL carry-forward). Use the offline utility.")

    st_q = check_quarters("Table F s.111A", st.get("quarters"), stcg, warnings)
    lt_q = check_quarters("Table F s.112A", lt.get("quarters"), lt_gross, warnings)

    # --- totals
    gti = salary_net + os_total + stcg + lt_taxable
    total_income = round(gti / 10) * 10               # s.288A
    normal_income = total_income - stcg - lt_taxable

    # --- basic exemption shortfall against special-rate gains (resident only)
    resident = fil.get("residential_status", "RES") in ("RES", "NOR")
    st_taxed, lt_taxed = stcg, lt_taxable
    if resident and normal_income < NEW_BEL:
        spare = NEW_BEL - normal_income
        used_st = min(spare, st_taxed)
        st_taxed -= used_st
        spare -= used_st
        lt_taxed -= min(spare, lt_taxed)
        warnings.append(
            "Unused basic exemption was set against the special-rate gains "
            "(first proviso to s.111A/112A). Residents only.")

    tax_normal = round(slab_tax_new(normal_income))
    tax_111a = round(st_taxed * RATE_111A)
    tax_112a = round(lt_taxed * RATE_112A)
    tax_special = tax_111a + tax_112a

    rebate = 0
    if total_income <= REBATE_LIMIT:
        # The rebate does not reach s.112A tax by statute, and the utility has
        # been declining it against s.111A too. Normal-rate tax only.
        rebate = min(REBATE_MAX, tax_normal)
        if tax_special:
            warnings.append(
                f"Total income is under {REBATE_LIMIT:,}, so the s.87A rebate "
                f"clears the normal-rate tax. It does NOT cover the "
                f"{tax_special:,} of tax on capital gains. That surprise is "
                f"the single most common question of this filing season.")
    elif total_income <= REBATE_LIMIT + 100000:
        warnings.append(
            "Total income is just above the 12,00,000 rebate threshold, where "
            "marginal relief applies. This script does not compute it. Let the "
            "utility work it out and expect a lower figure than shown here.")

    tax_after_rebate = tax_normal + tax_special - rebate
    cess = round(tax_after_rebate * CESS)
    gross_tax = tax_after_rebate + cess

    challans = cfg.get("challans") or []
    self_asmt = sum(rupees(c["Amt"]) for c in challans)
    tds = rupees(cfg.get("taxes_paid", {}).get("tds", 0))
    advance = rupees(cfg.get("taxes_paid", {}).get("advance_tax", 0))
    tcs = rupees(cfg.get("taxes_paid", {}).get("tcs", 0))
    paid = self_asmt + tds + advance + tcs
    balance = round(max(0, gross_tax - paid) / 10) * 10     # s.288B
    refund = round(max(0, paid - gross_tax) / 10) * 10

    # --- Schedule SI, special-rate rows that actually carry income
    si_rows = []
    if stcg:
        si_rows.append({"SecCode": "1A", "SplRatePercent": 20,
                        "SplRateInc": stcg, "SplRateIncTax": tax_111a})
    if lt_taxable:
        si_rows.append({"SecCode": "2A", "SplRatePercent": 12.5,
                        "SplRateInc": lt_taxable, "SplRateIncTax": tax_112a})

    itr2 = {
        "CreationInfo": {
            "SWVersionNo": "1.0",
            "SWCreatedBy": cfg.get("creation", {}).get("sw_provider_id", "SW00000001"),
            "JSONCreatedBy": cfg.get("creation", {}).get("sw_provider_id", "SW00000001"),
            "JSONCreationDate": ver["date"],
            "IntermediaryCity": cfg.get("creation", {}).get("city", ver["place"]),
            "Digest": "-",
        },
        "Form_ITR2": {
            "FormName": "ITR-2",
            "Description": "For Individuals and HUFs not having income from "
                           "profits and gains of business or profession",
            "AssessmentYear": "2026", "SchemaVer": "Ver1.0", "FormVer": "Ver1.0",
        },
        "PartA_GEN1": {
            "PersonalInfo": {
                "AssesseeName": {k: v for k, v in (
                    ("FirstName", p.get("first_name")),
                    ("MiddleName", p.get("middle_name")),
                    ("SurNameOrOrgName", p["surname"])) if v},
                "PAN": p["pan"],
                "Address": {k: v for k, v in (
                    ("ResidenceNo", addr["residence_no"]),
                    ("ResidenceName", addr.get("residence_name")),
                    ("RoadOrStreet", addr.get("road")),
                    ("LocalityOrArea", addr["locality"]),
                    ("CityOrTownOrDistrict", addr["city"]),
                    ("StateCode", addr["state_code"]),
                    ("CountryCode", addr.get("country_code", "91")),
                    # Same guard as the employer PIN below. Without it a blank
                    # PIN becomes 0, which the emit filter then drops, and the
                    # return goes out with no PIN and nothing said about it.
                    ("PinCode", rupees(addr["pin"]) if addr.get("pin") else None),
                    ("CountryCodeMobile", int(addr.get("mobile_country", 91))),
                    ("MobileNo", int(addr["mobile"])),
                    ("EmailAddress", addr["email"])) if v},
                "SecondaryAdd": "N",
                "DOB": p["dob"], "Status": p.get("status", "I"),
                **({"AadhaarCardNo": p["aadhaar"]} if p.get("aadhaar") else {}),
            },
            "FilingStatus": {
                "ReturnFileSec": int(fil.get("return_sec", 11)),
                "OptOutNewTaxRegime": "N",
                "SeventhProvisio139": fil.get("seventh_proviso", "N"),
                "ResidentialStatus": fil.get("residential_status", "RES"),
                "ConditionsResStatus": fil.get("conditions_res_status", "1"),
                "HeldUnlistedEqShrPrYrFlg": fil.get("held_unlisted", "N"),
                "FiiFpiFlag": fil.get("fii", "N"),
                "ItrFilingDueDate": fil.get("due_date", "2026-07-31"),
            },
        },
        "ScheduleS": {
            "Salaries": [{
                "NameOfEmployer": e["name"],
                "NatureOfEmployment": e.get("nature", "OTH"),
                "AddressDetail": {k: v for k, v in (
                    ("AddrDetail", e["address"]),
                    ("CityOrTownOrDistrict", e["city"]),
                    ("StateCode", e["state_code"]),
                    # A blank PIN serialises as 0 and fails validation with
                    # "0 is not greater or equal to 100000". Omit it instead.
                    ("PinCode", rupees(e["pin"]) if e.get("pin") else None))
                    if v},
                "Salarys": {
                    "GrossSalary": rupees(e["gross_salary"]),
                    "Salary": rupees(e["gross_salary"]),
                    "NatureOfSalary": {"OthersIncDtls": [
                        {"NatureDesc": "1",
                         "OthAmount": rupees(e["gross_salary"])}]},
                    "ValueOfPerquisites": 0, "ProfitsinLieuOfSalary": 0,
                    "IncomeNotified89A": 0, "IncomeNotifiedOther89A": 0,
                },
            } for e in employers],
            "TotalGrossSalary": gross_salary, "AllwncExtentExemptUs10": 0,
            "NetSalary": gross_salary, "DeductionUS16": std_ded,
            "DeductionUnderSection16ia": std_ded, "EntertainmntalwncUs16ii": 0,
            "ProfessionalTaxUs16iii": 0, "TotIncUnderHeadSalaries": salary_net,
        },
        "ScheduleCGFor23": {
            "ShortTermCapGainFor23": {
                **({"EquityMFonSTT": [{
                    "MFSectionCode": "1A",
                    "EquityMFonSTTDtls": {
                        "FullConsideration": st_consid,
                        "DeductSec48": {"AquisitCost": st_cost, "ImproveCost": 0,
                                        "ExpOnTrans": st_exp,
                                        "TotalDedn": st_cost + st_exp},
                        "BalanceCG": stcg, "LossSec94of7Or94of8": 0,
                        "CapgainonAssets": stcg,
                    }}]} if stcg else {}),
                "NRITransacSec48Dtl": {"NRItaxSTTPaid": 0, "NRItaxSTTNotPaid": 0},
                "NRISecur115AD": zero_sec94(),
                "SaleOnOtherAssets": zero_sec94(),
                "TotalAmtDeemedStcg": 0, "PassThrIncNatureSTCG": 0,
                "TotalAmtNotTaxUsDTAAStcg": 0, "TotalAmtTaxUsDTAAStcg": 0,
                "TotalSTCG": stcg,
            },
            "LongTermCapGain23": {
                "SaleOfEquityShareUs112A": {"BalanceCG": lt_gross,
                                            "DeductionUs54F": 0,
                                            "CapgainonAssets": lt_taxable},
                "NRISaleOfEquityShareUs112A": {"BalanceCG": 0,
                                               "DeductionUs54F": 0,
                                               "CapgainonAssets": 0},
                "NRISaleofForeignAsset": {"SaleonSpecAsset": 0,
                                          "DednSpecAssetus115": 0,
                                          "BalonSpeciAsset": 0},
                "SaleofAssetNADtls": {},
                "TotalAmtDeemedLtcg": 0, "PassThrIncNatureLTCG": 0,
                "TotalAmtNotTaxUsDTAALtcg": 0, "TotalAmtTaxUsDTAALtcg": 0,
                "TotalLTCG": lt_taxable,
            },
            "SumOfCGIncm": stcg + lt_taxable, "IncmFromVDATrnsf": 0,
            "TotScheduleCGFor23": stcg + lt_taxable,
            "CurrYrLosses": {
                "InLossSetOff": {"StclSetoff20Per": 0, "StclSetoff30Per": 0,
                                 "StclSetoffAppRate": 0, "StclSetoffDTAARate": 0,
                                 "LtclSetOff12_5Per": 0, "LtclSetOffDTAARate": 0},
                "InStcg20Per": {"CurrYearIncome": stcg, "StclSetoff30Per": 0,
                                "StclSetoffAppRate": 0, "StclSetoffDTAARate": 0,
                                "CurrYrCapGain": stcg},
                "InStcg30Per": {"CurrYearIncome": 0, "StclSetoff20Per": 0,
                                "StclSetoffAppRate": 0, "StclSetoffDTAARate": 0,
                                "CurrYrCapGain": 0},
                "InStcgAppRate": {"CurrYearIncome": 0, "StclSetoff20Per": 0,
                                  "StclSetoff30Per": 0, "StclSetoffDTAARate": 0,
                                  "CurrYrCapGain": 0},
                "InStcgDTAARate": {"CurrYearIncome": 0, "StclSetoff20Per": 0,
                                   "StclSetoff30Per": 0, "StclSetoffAppRate": 0,
                                   "CurrYrCapGain": 0},
                "InLtcg12_5Per": {"CurrYearIncome": lt_taxable,
                                  "StclSetoff20Per": 0, "StclSetoff30Per": 0,
                                  "StclSetoffAppRate": 0, "StclSetoffDTAARate": 0,
                                  "LtclSetOffDTAARate": 0,
                                  "CurrYrCapGain": lt_taxable},
                "InLtcgDTAARate": {"CurrYearIncome": 0, "StclSetoff20Per": 0,
                                   "StclSetoff30Per": 0, "StclSetoffAppRate": 0,
                                   "StclSetoffDTAARate": 0, "LtclSetOff12_5Per": 0,
                                   "CurrYrCapGain": 0},
                "TotLossSetOff": {"StclSetoff20Per": 0, "StclSetoff30Per": 0,
                                  "StclSetoffAppRate": 0, "StclSetoffDTAARate": 0,
                                  "LtclSetOff12_5Per": 0, "LtclSetOffDTAARate": 0},
                "LossRemainSetOff": {"StclSetoff20Per": 0, "StclSetoff30Per": 0,
                                     "StclSetoffAppRate": 0,
                                     "StclSetoffDTAARate": 0,
                                     "LtclSetOff12_5Per": 0,
                                     "LtclSetOffDTAARate": 0},
            },
            "AccruOrRecOfCG": {
                "ShortTermUnder20Per": date_range(st_q),
                "ShortTermUnder30Per": date_range(),
                "ShortTermUnderAppRate": date_range(),
                "ShortTermUnderDTAARate": date_range(),
                "LongTermUnder12_5Per": date_range(lt_q),
                "LongTermUnderDTAARate": date_range(),
            },
        },
        "ScheduleOS": {
            "IncOthThanOwnRaceHorse": {
                "GrossIncChrgblTaxAtAppRate": os_total,
                "DividendGross": dividend, "DividendOthThan22e": dividend,
                "InterestGross": interest_gross,
                "IntrstFrmSavingBank": sav, "IntrstFrmTermDeposit": term,
                "IntrstFrmIncmTaxRefund": refund_int, "IntrstFrmOthers": oth_int,
                "NatofPassThrghIncome": 0, "RentFromMachPlantBldgs": 0,
                "Tot562x": 0, "Aggrtvaluewithoutcons562x": 0,
                "Immovpropwithoutcons562x": 0, "Immovpropinadeqcons562x": 0,
                "Anyotherpropwithoutcons562x": 0, "Anyotherpropinadeqcons562x": 0,
                "FamilyPension": 0, "AnyOtherIncome": 0,
                "IncChargeableSpecialRates": 0, "LtryPzzlChrgblUs115BB": 0,
                "IncChrgblUs115BBE": 0, "CashCreditsUs68": 0,
                "UnExplndInvstmntsUs69": 0, "UnExplndMoneyUs69A": 0,
                "UnDsclsdInvstmntsUs69B": 0, "UnExplndExpndtrUs69C": 0,
                "AmtBrwdRepaidOnHundiUs69D": 0, "OthersGross": 0,
                "PassThrIncOSChrgblSplRate": 0,
                "Deductions": {"Expenses": 0, "DeductionUs57iia": 0,
                               "Depreciation": 0, "TotDeductions": 0},
                "IncomeNotified89AOS": 0,
                "TaxAccumulatedBalRecPF": {"TotalIncomeBenefit": 0,
                                           "TotalTaxBenefit": 0},
                "BalanceNoRaceHorse": os_total,
            },
            "TotOthSrcNoRaceHorse": os_total,
            "IncChargeable": os_total,
            "IncFrmLottery": date_range(),
            "DividendIncUs115BBDA": date_range(div_q),
            "DividendIncUs115BBDAaiii": date_range(),
            "DividendIncUs115A1ai": date_range(),
            "DividendIncUs115AC": date_range(),
            "DividendIncUs115ACA": date_range(),
            "DividendIncUs115AD1i": date_range(),
            "DividendDTAA": date_range(),
            "NOT89A": date_range(),
        },
        "ScheduleCYLA": {
            "Salary": cyla_row(salary_net),
            "STCG20Per": cyla_row(stcg),
            "STCG30Per": cyla_row(0), "STCGAppRate": cyla_row(0),
            "STCGDTAARate": cyla_row(0),
            "LTCG12_5Per": cyla_row(lt_taxable), "LTCGDTAARate": cyla_row(0),
            "OthSrcExclRaceHorse": cyla_othsrc_row(os_total),
            "TotalCurYr": {"TotHPlossCurYr": 0, "TotOthSrcLossNoRaceHorse": 0},
            "TotalLossSetOff": {"TotHPlossCurYrSetoff": 0,
                                "TotOthSrcLossNoRaceHorseSetoff": 0},
            "LossRemAftSetOff": {"BalHPlossCurYrAftSetoff": 0,
                                 "BalOthSrcLossNoRaceHorseAftSetoff": 0},
        },
        "ScheduleBFLA": {
            "Salary": bfla_plain_row(salary_net),
            "STCG20Per": bfla_cg_row(stcg),
            "STCG30Per": bfla_cg_row(0), "STCGAppRate": bfla_cg_row(0),
            "STCGDTAARate": bfla_cg_row(0),
            "LTCG12_5Per": bfla_cg_row(lt_taxable),
            "LTCGDTAARate": bfla_cg_row(0),
            "OthSrcExclRaceHorse": bfla_plain_row(os_total),
            "TotalBFLossSetOff": {"TotBFLossSetoff": 0},
            "IncomeOfCurrYrAftCYLABFLA": gti,
        },
        "PartB-TI": {
            "Salaries": salary_net, "IncomeFromHP": 0,
            "CapGain": {
                "ShortTerm": {"ShortTerm20Per": stcg, "ShortTerm30Per": 0,
                              "ShortTermAppRate": 0, "ShortTermSplRateDTAA": 0,
                              "TotalShortTerm": stcg},
                "LongTerm": {"LongTerm12_5Per": lt_taxable,
                             "LongTermSplRateDTAA": 0,
                             "TotalLongTerm": lt_taxable},
                "ShortTermLongTermTotal": stcg + lt_taxable,
                "CapGains30Per115BBH": 0,
                "TotalCapGains": stcg + lt_taxable,
            },
            "IncFromOS": {"OtherSrcThanOwnRaceHorse": os_total,
                          "IncChargblSplRate": 0, "FromOwnRaceHorse": 0,
                          "TotIncFromOS": os_total},
            "TotalTI": gti, "CurrentYearLoss": 0,
            "BalanceAfterSetoffLosses": gti, "BroughtFwdLossesSetoff": 0,
            "GrossTotalIncome": gti,
            "IncChargeTaxSplRate111A112": stcg + lt_taxable,
            "DeductionsUnderScheduleVIA": 0, "TotalIncome": total_income,
            "IncChargeableTaxSplRates": stcg + lt_taxable,
            "NetAgricultureIncomeOrOtherIncomeForRate": 0,
            "AggregateIncome": normal_income,
            "LossesOfCurrentYearCarriedFwd": 0, "DeemedIncomeUs115JC": 0,
        },
        "PartB_TTI": {
            "TaxPayDeemedTotIncUs115JC": 0, "Surcharge": 0, "HealthEduCess": 0,
            "TotalTaxPayablDeemedTotInc": 0,
            "ComputationOfTaxLiability": {
                "TaxPayableOnTI": {"TaxAtNormalRatesOnAggrInc": tax_normal,
                                   "TaxAtSpecialRates": tax_special,
                                   "RebateOnAgriInc": 0,
                                   "TaxPayableOnTotInc": tax_normal + tax_special},
                "Rebate87A": rebate, "TaxPayableOnRebate": tax_after_rebate,
                "Surcharge25ofSI": 0, "SurchargeOnAboveCrore": 0,
                "Surcharge25ofSIBeforeMarginal": 0,
                "SurchargeOnAboveCroreBeforeMarginal": 0, "TotalSurcharge": 0,
                "EducationCess": cess, "GrossTaxLiability": gross_tax,
                "GrossTaxPayable": gross_tax,
                "GrossTaxPay": {"TaxInc17": gross_tax, "TaxDeferred17": 0,
                                "TaxDeferredPayableCY": 0},
                "CreditUS115JD": 0, "TaxPayAfterCreditUs115JD": gross_tax,
                "TaxRelief": {"Section89": 0, "Section90": 0, "Section91": 0,
                              "TotTaxRelief": 0},
                "NetTaxLiability": gross_tax,
                "IntrstPay": {"IntrstPayUs234A": 0, "IntrstPayUs234B": 0,
                              "IntrstPayUs234C": 0, "LateFilingFee234F": 0,
                              "TotalIntrstPay": 0},
                "AggregateTaxInterestLiability": gross_tax,
            },
            "TaxPaid": {
                "TaxesPaid": {"AdvanceTax": advance, "TDS": tds, "TCS": tcs,
                              "SelfAssessmentTax": self_asmt,
                              "TotalTaxesPaid": paid},
                "BalTaxPayable": balance,
            },
            "Refund": {"RefundDue": refund,
                       "BankAccountDtls": {"BankDtlsFlag": "Y",
                                           "AddtnlBankDetails": cfg["banks"]}},
            "AssetOutIndiaFlag": cfg.get("assets_outside_india", "NO"),
        },
        "Verification": {
            "Declaration": {"AssesseeVerName": ver["name"],
                            "FatherName": ver["father_name"],
                            "AssesseeVerPAN": p["pan"]},
            "Capacity": ver.get("capacity", "S"),
            "Date": ver["date"], "Place": ver["place"],
        },
    }

    if si_rows:
        itr2["ScheduleSI"] = {"SplCodeRateTax": si_rows,
                              "TotSplRateInc": stcg + lt_taxable,
                              "TotSplRateIncTax": tax_special}

    if challans:
        itr2["ScheduleIT"] = {"TaxPayment": challans,
                              "TotalTaxPayments": self_asmt}
    elif balance:
        warnings.append(
            f"{balance:,} is payable and no challan is recorded. Pay the "
            f"self-assessment tax (e-Pay Tax, minor head 300), add the challan "
            f"to the input, and rebuild. Filing with tax outstanding invites a "
            f"demand notice.")

    if cfg.get("schedule_112a_csv"):
        rows = load_112a_rows(cfg["schedule_112a_csv"])
        itr2["Schedule112A"] = rows
        total = sum(rupees(r.get("Balance", 0)) for r in rows)
        if total != lt_gross:
            warnings.append(
                f"Schedule 112A rows total {total:,} but Schedule CG says "
                f"{lt_gross:,}. The utility rejects that mismatch.")
    elif lt_gross:
        warnings.append(
            "s.112A gains are present but no Schedule 112A CSV was given. "
            "Scrip-wise detail is required for grandfathering-eligible "
            "holdings. build_worksheet.py emits schedule_112a.csv.")

    summary = {
        "gross_salary": gross_salary, "salary_net": salary_net,
        "other_sources": os_total, "stcg_111a": stcg,
        "ltcg_112a_gross": lt_gross, "ltcg_112a_taxable": lt_taxable,
        "total_income": total_income, "tax_normal": tax_normal,
        "tax_special": tax_special, "rebate_87a": rebate, "cess": cess,
        "total_tax": gross_tax, "taxes_paid": paid,
        "balance_payable": balance, "refund_due": refund,
    }
    return {"ITR": {"ITR2": itr2}}, summary, warnings


def find_placeholders(node, path="", hits=None):
    """Catch template values that were never filled in."""
    if hits is None:
        hits = []
    if isinstance(node, dict):
        for k, v in node.items():
            find_placeholders(v, f"{path}.{k}" if path else k, hits)
    elif isinstance(node, list):
        for i, v in enumerate(node):
            find_placeholders(v, f"{path}[{i}]", hits)
    elif isinstance(node, str):
        upper = node.upper()
        if "REPLACE" in upper or "XXXX" in upper or upper.startswith("YOUR "):
            hits.append((path, node))
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="your return input JSON")
    ap.add_argument("-o", "--output", default="itr2_upload.json")
    args = ap.parse_args()

    cfg = json.loads(Path(args.input).read_text())
    doc, summary, warnings = build(cfg)

    def report(errors, validator_name, coverage=""):
        if errors:
            print(f"SCHEMA VALIDATION FAILED: {len(errors)} error(s)\n")
            for path, message in errors[:25]:
                print(f"  at {path}")
                print(f"     {message[:200]}")
            if len(errors) > 25:
                print(f"  ... and {len(errors) - 25} more")
            sys.exit(1)
        print(f"schema: PASS ({SCHEMA.name}, {validator_name}{coverage})")

    schema = json.loads(SCHEMA.read_text())
    try:
        from jsonschema import Draft4Validator
    except ImportError:
        # No jsonschema on this machine. Fall back to the bundled validator
        # rather than skipping, because a return built with no validation at
        # all is worse than one that fails here.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        try:
            import schema_validate
        except ImportError:
            print("schema: COULD NOT VALIDATE. Neither jsonschema nor "
                  "scripts/schema_validate.py is available, so nothing has "
                  "checked this file. Do not upload it.", file=sys.stderr)
            sys.exit(2)

        unimplemented = schema_validate.audit_keywords(schema)
        if unimplemented:
            # Say so loudly: a pass would not mean what it looks like.
            print(f"schema: PARTIAL COVERAGE. The builtin validator does not "
                  f"implement {', '.join(unimplemented)}, which this schema "
                  f"uses. A pass below does not cover those keywords.")
            coverage = f", partial keyword coverage ({len(unimplemented)} unchecked)"
        else:
            coverage = ", full keyword coverage"
        try:
            errors = schema_validate.validate(doc, schema)
        except schema_validate.SchemaError as exc:
            print(f"schema: COULD NOT VALIDATE ({exc})", file=sys.stderr)
            sys.exit(2)
        report(errors, "builtin validator", coverage)
    else:
        errors = [(".".join(str(x) for x in e.absolute_path) or "<root>",
                   e.message)
                  for e in sorted(Draft4Validator(schema).iter_errors(doc),
                                  key=lambda e: list(e.absolute_path))]
        report(errors, "jsonschema")

    print("\n  gross salary            {gross_salary:>12,}\n"
          "  less standard deduction {sd:>12,}\n"
          "  other sources           {other_sources:>12,}\n"
          "  STCG u/s 111A           {stcg_111a:>12,}\n"
          "  LTCG u/s 112A taxable   {ltcg_112a_taxable:>12,}\n"
          "  TOTAL INCOME            {total_income:>12,}\n"
          "  tax at slab rates       {tax_normal:>12,}\n"
          "  tax on capital gains    {tax_special:>12,}\n"
          "  less rebate u/s 87A     {rebate_87a:>12,}\n"
          "  cess                    {cess:>12,}\n"
          "  TOTAL TAX               {total_tax:>12,}\n"
          "  taxes paid              {taxes_paid:>12,}\n"
          "  BALANCE PAYABLE         {balance_payable:>12,}\n"
          "  refund due              {refund_due:>12,}"
          .format(sd=summary["gross_salary"] - summary["salary_net"], **summary))

    placeholders = find_placeholders(doc)
    for w in warnings:
        print(f"\n  note: {w}")
    if placeholders:
        print(f"\n  NOT READY: {len(placeholders)} template value(s) still in place:")
        for path, val in placeholders:
            print(f"    {path} = {val}")

    Path(args.output).write_text(json.dumps(doc, separators=(",", ":")))
    print(f"\nwritten: {args.output}")
    print("Next: import this into the official offline utility, let it validate "
          "and recompute, and fix whatever it flags. The utility is right and "
          "this script is not.")


if __name__ == "__main__":
    main()
