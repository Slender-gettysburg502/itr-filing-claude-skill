# Tax rules, FY 2025-26 / AY 2026-27

Everything here applies to the full financial year. Where FY 2024-25 differed,
that is called out — those are the errors that carry over from last year's
filing habits.

## Contents
1. Regimes and slabs
2. Rebate, surcharge, cess
3. Capital gains: rates and holding periods
4. Capital gains: classification by asset
5. Grandfathering under s.112A
6. Loss set-off and carry-forward
7. Interest and other sources
8. Advance tax, 234A/B/C
9. Deadlines
10. What changed from FY 2024-25

---

## 1. Regimes and slabs

The **new regime under s.115BAC(1A) is the default.** Opting out is done inside
the return, before the due date, and can be done afresh each year. **Form 10-IEA
is not required** for a filer with no business or professional income — it
applies only to business filers, for whom the switch is effectively
once-in-a-lifetime.

### New regime slabs

| Income | Rate |
|---|---|
| Up to 4,00,000 | Nil |
| 4,00,001 – 8,00,000 | 5% |
| 8,00,001 – 12,00,000 | 10% |
| 12,00,001 – 16,00,000 | 15% |
| 16,00,001 – 20,00,000 | 20% |
| 20,00,001 – 24,00,000 | 25% |
| Above 24,00,000 | 30% |

Basic exemption 4,00,000 for all ages — no higher senior-citizen band.
Standard deduction on salary: **75,000**.

### Old regime slabs

Nil to 2,50,000; 5% to 5,00,000; 20% to 10,00,000; 30% above.
Basic exemption 3,00,000 for age 60+, 5,00,000 for 80+.
Standard deduction on salary: 50,000.

### Deductions by regime

| | Old | New |
|---|---|---|
| 80C (1.5 lakh) | yes | no |
| 80D health insurance | yes | no |
| 80TTA savings interest (10,000) | yes | no |
| 80TTB seniors (50,000) | yes | no |
| 24(b) home loan interest, self-occupied | yes | no |
| HRA 10(13A), LTA | yes | no |
| Standard deduction | 50,000 | 75,000 |
| 80CCD(2) employer NPS | yes | yes |
| 80CCH Agniveer | yes | yes |

Chapter VI-A deductions cannot be set against special-rate capital gains.

## 2. Rebate, surcharge, cess

**s.87A rebate, new regime: up to 60,000**, where total income does not exceed
12,00,000 — so 12,75,000 of salary after the standard deduction.

The rebate does **not** apply to tax on s.112A LTCG; that bar is statutory. The
e-filing utility has also been declining to allow it against s.111A STCG, so the
conservative position — and what `compute_tax.py` implements — is to grant the
rebate only against normal-rate tax. This is the single most misunderstood rule
of the year: someone earning under 12 lakh with capital gains still owes tax.

Confirmed against the AY 2026-27 utility: on a total income in the 9 lakh range
with a small s.111A gain, it granted the full rebate against the slab tax and
left the 20% on the gain standing, plus cess. Expect to explain this. The
headline "no tax under 12 lakh" was never written to cover capital gains, and
small investors meet the difference as an unexpected demand of a few thousand
rupees.

**Marginal relief** applies just above 12,00,000 so that the tax does not exceed
the income over the threshold.

**Old regime rebate: 12,500**, total income up to 5,00,000. Barred against 112A,
allowed against 111A.

**Surcharge** on total income: 10% above 50 lakh, 15% above 1 crore, 25% above
2 crore. The new regime caps at 25%; the old regime goes to 37% above 5 crore.
Surcharge on tax attributable to 111A, 112A and dividends is capped at 15%.

**Cess: 4%** on tax plus surcharge.

## 3. Capital gains: rates and holding periods

| | Rate |
|---|---|
| STCG on listed equity / equity MF (s.111A) | **20%** |
| LTCG on listed equity / equity MF (s.112A) | **12.5%** above 1,25,000 |
| LTCG on other assets | 12.5%, **no indexation** |
| STCG on other assets | slab rates |
| Specified mutual funds (s.50AA) | slab rates, always short-term |

Holding period for long-term:
- **listed securities and equity-oriented MF units: more than 12 months**
- **everything else: more than 24 months** — unlisted shares, property, gold,
  and non-equity MF units (which are not "listed securities")

The 1,25,000 s.112A exemption is **per taxpayer per year**, not per broker.
Aggregate across every broker and AMC before applying it once.

Regime choice does not affect these rates.

### Basic-exemption shortfall

A **resident** whose normal income falls below the basic exemption limit may set
the unused portion against 111A and 112A gains (first proviso to each section).
Available in both regimes. **Not available to non-residents.** Consume it
against the highest-taxed bucket first — 111A at 20% before 112A at 12.5%.

## 4. Capital gains: classification by asset

This drives the `asset_class` column in the ledger.

**equity_listed / equity_mf** — listed shares and equity-oriented mutual funds.
More than 12 months is 112A; otherwise 111A.

**debt_mf** — a "specified mutual fund" under s.50AA. Units bought **on or after
1 April 2023** are always STCG at slab rates regardless of holding period. Units
bought before that date fall under the earlier framework, so more than 24 months
gets 12.5% LTCG treatment.

The s.50AA definition **changed for FY 2025-26**. It now means a fund investing
more than 65% in debt and money-market instruments, or a fund investing 65% or
more in units of such a fund. The old test — not more than 35% in domestic
equity shares — applied for FY 2023-24 and FY 2024-25 only.

**gold_intl_mf** — gold ETFs, silver ETFs, international and overseas funds.
The old 35%-equity test caught these; the new >65%-debt test usually does not.
So from FY 2025-26 they are typically **outside 50AA** and get normal treatment:
more than 24 months at 12.5%, otherwise slab. Confirm the actual allocation
rather than assuming — the script warns on every row of this class.

**hybrid_other** — depends entirely on the split. 65% or more equity behaves as
equity-oriented (111A/112A). More than 65% debt falls under 50AA. Anything in
between gets normal non-equity treatment. Resolve against the scheme's AMFI
category; do not guess.

**unlisted / property** — more than 24 months at 12.5% without indexation,
otherwise slab.

**buyback** — from **1 October 2024**, buyback proceeds of a domestic listed
company are a **deemed dividend under s.2(22)(f)**, taxable under Income from
Other Sources at slab rates. The company no longer pays s.115QA tax. In Schedule
CG the sale consideration is **nil**, so the entire cost of acquisition becomes
a capital loss — short-term or long-term by holding period, carried forward 8
years. That loss is only allowed **if the deemed dividend is actually disclosed
in Schedule OS.** Zerodha's Tax P&L shows buyback trades separately so they can
be pulled out of the ordinary STCG figure.

## 5. Grandfathering under s.112A

For equity and equity-MF units acquired **on or before 31 January 2018**:

```
cost = max( actual cost, min( FMV on 31-Jan-2018, sale consideration ) )
```

The FMV is the highest quoted price on 31-Jan-2018, or the nearest preceding
trading day. For bonus and rights shares issued before that date, the
31-Jan-2018 FMV becomes the deemed cost even though the actual cost was nil.

Zerodha Console and the CAMS/KFintech consolidated statements already apply
grandfathering per scrip. Trust their per-row computation, but recompute the
aggregates and apply the 1,25,000 exemption at taxpayer level — no single
statement can see the others.

## 6. Loss set-off and carry-forward

- STCL sets off against both STCG and LTCG
- LTCL sets off only against LTCG
- Unabsorbed losses carry forward **8 assessment years**
- **Carry-forward requires filing on or before the s.139(1) due date.** A
  belated return forfeits it. House-property loss is the exception that survives.

This is often the strongest argument for filing on time. A 2 lakh carried
capital loss is worth more than the 5,000 late fee.

## 7. Interest and other sources

**Recurring deposits** — fully taxable, no exemption. Report on accrual or on
receipt, but be consistent year to year. AIS reports on an accrual basis, so
someone reporting only at maturity will show a mismatch every year; reporting
accrued interest annually is the practical fix.

**TDS under s.194A** at 10%. Thresholds rose with effect from 1 April 2025:
40,000 to **50,000** for banks, co-operative banks and post offices; 50,000 to
**1,00,000** for senior citizens; 5,000 to 10,000 for other payers. The
threshold only triggers withholding — the interest is taxable regardless, and
once crossed, TDS applies to the whole amount, not just the excess.

**Savings interest** — taxable. 80TTA up to 10,000, old regime only. 80TTB up to
50,000 for seniors, old regime only.

**Dividends** — fully taxable at slab rates. TDS under s.194 at 10% above
**10,000** per company or AMC (raised from 5,000 on 1 April 2025).

**Schedule EI** — exempt income: PPF interest under 10(11), EPF under 10(12),
agricultural income up to 5,000. Dividends are **not** exempt and belong in
Schedule OS. The AY 2026-27 Schedule EI was redesigned and some sub-categories
moved, so re-check placement rather than copying last year's.

## 8. Advance tax, 234A/B/C

Advance tax is payable when the liability after TDS reaches **10,000**.
Instalments: 15% by 15 Jun, 45% by 15 Sep, 75% by 15 Dec, 100% by 15 Mar.

- **234A** — 1% per month on unpaid tax for late filing
- **234B** — 1% per month where advance tax paid is under 90% of assessed tax
- **234C** — 1% per month for deferment of instalments

Capital gains get a carve-out from 234C: the liability attaches only from the
instalment falling due **after** the gain arose. That is the entire reason
Schedule CG Table F asks for a quarter-wise split. Let the utility compute 234C
and compare — it depends on the dates of actual advance-tax payments, which the
script cannot see.

## 9. Deadlines

| | |
|---|---|
| Original return, non-audit individual | **31 July 2026** |
| Belated return (s.139(4)) | 31 December 2026 — forfeits loss carry-forward |
| Revised return (s.139(5)) | 31 March 2027 |
| Updated return (ITR-U, s.139(8A)) | 31 March 2031, 48-month window |
| E-verification | **30 days** from upload |

Late fee under s.234F: 5,000 where total income exceeds 5 lakh, 1,000 where it
does not, nil below the basic exemption.

Verification methods: Aadhaar OTP, net banking, demat, bank EVC, or a signed
ITR-V posted to CPC Bengaluru 560500. Verifying after 30 days makes the
verification date the filing date, with the late consequences that implies. An
unverified return is invalid.

## 10. What changed from FY 2024-25

The list that catches people out:

| | FY 2024-25 | FY 2025-26 |
|---|---|---|
| Basic exemption, new regime | 3,00,000 | **4,00,000** |
| s.87A rebate, new regime | 25,000 at 7 lakh | **60,000 at 12 lakh** |
| s.111A STCG | 15% then 20% mid-year | **20% throughout** |
| s.112A LTCG | 10% then 12.5% mid-year | **12.5% throughout** |
| s.112A exemption | 1,00,000 then 1,25,000 | **1,25,000** |
| s.50AA "specified MF" | ≤35% domestic equity | **>65% debt** |
| s.194A TDS threshold | 40,000 / 50,000 seniors | **50,000 / 1,00,000** |
| s.194 dividend threshold | 5,000 | **10,000** |
| Schedule AL threshold | 50 lakh (to AY 2024-25) | **1 crore** |
| ITR-U window | 24 months | **48 months** |
| Revised return deadline | 31 December | **31 March** |
| Pre/post 23-Jul-2024 CG split | required | **removed** |

The mid-year rate split is gone, which simplifies reporting considerably —
AY 2025-26 was the only year that needed it.

---

Rates and thresholds here were compiled for AY 2026-27. Utilities and schemas
get revised mid-season. Where a figure drives a filed number, confirm it against
the current e-filing utility rather than against this file.
