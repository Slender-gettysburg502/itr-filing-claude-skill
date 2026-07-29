# ITR-2 schedules and the JSON schema, AY 2026-27

## Contents
1. Schedules this profile touches
2. Schedule CG in detail
3. Schedule 112A columns
4. Table F, quarter-wise
5. Schedule OS and the buyback split
6. JSON structure and node names
7. Validation failures
8. Pre-filing checklist

---

## 1. Schedules this profile touches

| Schedule | Contents | Notes |
|---|---|---|
| Part A General | PAN, Aadhaar, address, regime option | 12-digit Aadhaar now mandatory; enrolment ID no longer accepted |
| Schedule S | Salary from Form 16 | standard deduction 75,000 new / 50,000 old |
| Schedule HP | House property | only if applicable |
| Schedule CG | Capital gains, plus Schedule 112A and Table F | the bulk of the work |
| Schedule OS | Interest, dividends, buyback deemed dividend | |
| Schedule CYLA / BFLA / CFL | Loss set-off and carry-forward | |
| Schedule VI-A | Chapter VI-A deductions | 80CCD(2) and 80CCH in both regimes |
| Schedule 80G / 80GGA | Donations | now needs IFSC and transaction reference |
| Schedule AL | Assets and liabilities | **only where total income exceeds 1 crore** |
| Schedule FA / FSI / TR | Foreign assets, income, tax relief | hand off to a CA |
| Schedule SI | Special-rate income | auto-populated |
| Schedule EI | Exempt income | redesigned for AY 2026-27 |
| Schedule TDS1 / TDS2 / TDS3 | Salary TDS, other TDS, 26QB | TDS2 now carries a section column |
| Schedule IT | Advance and self-assessment tax | |
| Part B-TI, Part B-TTI | Total income, tax liability | |
| Verification | | |

Schedule AL moved to a 1 crore threshold — it was 50 lakh through AY 2024-25.
Most salaried filers no longer complete it.

## 2. Schedule CG in detail

Short-term section, with the s.111A equity item (item A3 in recent layouts) for
listed equity and equity mutual funds sold within 12 months.

Long-term section, with the s.112A item (item B4) for the same assets held
beyond 12 months, backed by the Schedule 112A scrip-wise table.

Other buckets: s.50AA specified mutual funds at slab rates, non-equity long-term
at 12.5%, unlisted, property.

The buyback field takes nil consideration against the cost of acquisition,
producing the capital loss described below.

**The pre-/post-23-July-2024 split has been removed for AY 2026-27.** It was
required in AY 2025-26 only, when rates changed mid-year. Anyone reusing last
year's approach will look for fields that no longer exist.

Item letters and numbers shift between utility versions. Match on the field
description in the utility rather than trusting a letter from any document,
including this one.

## 3. Schedule 112A columns

Required per scrip, for holdings eligible for grandfathering:

- whether acquired before or after 01-02-2018
- ISIN
- name of the share or unit
- number of shares or units
- sale price per unit
- full value of consideration (quantity times sale price)
- cost of acquisition without indexation
- FMV per unit as on 31-01-2018
- total FMV
- expenditure on transfer
- resulting cost of acquisition after grandfathering

Scrip-wise entry is required for grandfathering-eligible holdings. The
department has clarified that scrip-wise detail is needed *only* to report gains
on shares eligible for grandfathering — that is, acquired on or before
31 January 2018. The utility accepts a CSV upload against its own Schedule 112A
template, which is far faster than typing rows.

`build_worksheet.py` emits `schedule_112a.csv` with these columns already
computed, using the JSON field names below.

**The row total must roll up to the aggregate 112A figure in Schedule CG**, or
the utility raises a total-mismatch error.

## 4. Table F, quarter-wise

Schedule CG asks for capital gains split across five periods, because s.234C
only attaches advance-tax liability from the instalment after the gain arose:

| | |
|---|---|
| Q1 | 1 April to 15 June |
| Q2 | 16 June to 15 September |
| Q3 | 16 September to 15 December |
| Q4 | 16 December to 15 March |
| Q5 | 16 March to 31 March |

Two mechanical constraints:

- **The utility rejects negative quarter values.** A quarter with a net loss
  must be entered as zero, with the positives redistributed so the annual total
  still matches Schedule CG. `build_worksheet.py` clamps and warns when the
  clamped sum diverges from the true net.
- **The quarters must sum to the computed gain exactly.** A one-rupee rounding
  difference triggers a validation error.

## 5. Schedule OS and the buyback split

Buyback proceeds from 1 October 2024 are a deemed dividend under s.2(22)(f) and
go into Schedule OS at slab rates. Schedule CG then shows nil consideration
against the cost, generating a capital loss.

The two halves are linked: **the capital loss is only allowed if the deemed
dividend is disclosed.** Reporting one without the other is an error the
department can see from AIS.

Also in Schedule OS: RD and FD interest, savings interest, dividends. Dividends
belong here, not in Schedule EI — exempt-dividend reporting ended with
AY 2021-22.

## 6. JSON structure and node names

The department publishes the ITR-2 JSON schema and a schema-change document
under incometax.gov.in, Downloads, Income Tax Returns. For AY 2026-27 the
utility and schema were released 26 May 2026, with change document V1.1 dated
30 June 2026 — whose only logged changes so far are to the `OthersIncDtlEI`
node, reflecting the Schedule EI redesign.

Observed top-level shape:

```
ITR
└── ITR2
    ├── CreationInfo      SWVersionNo, SWCreatedBy, JSONCreatedBy,
    │                     JSONCreationDate, IntermediaryCity, Digest
    ├── Form_ITR2         FormName, FormVer, SchemaVer, AssessmentYear
    ├── PersonalInfo      AssesseeName{FirstName, SurNameOrOrgName}, PAN, ...
    ├── FilingStatus      ReturnFileSec, NewTaxRegime, ...
    ├── ScheduleS
    ├── ScheduleCGFor23   LongTermCapGain23, Schedule112A, ...
    ├── ScheduleOS
    ├── PartB-TI          hyphen
    ├── PartB_TTI         underscore
    └── Verification
```

Inside `ScheduleCGFor23`, the long-term container is `LongTermCapGain23`, and
within it `SaleOfEquityShareUs112A` holds the 112A figure
(`NRISaleOfEquityShareUs112A` for non-residents). The 111A equity item appears
as `EquityMFonSTT`, with `NRISecur115AD` as the non-resident counterpart.

`Schedule112A` is an array; each row uses these field names:

```
ShareOnOrBefore            "BE" before 01-02-2018, "AE" after
ISINCode
NameofShareUnit
NumSharesUnits
SalePricePerShareUnit
TotSaleValue
CostAcqWithoutIndx
AcquisitionCost
FairMktValuePerShareunit
TotFairMktValueCapAst
ExpExclCnctTransfer
Balance
```

The above is confirmed against the published AY 2026-27 schema, a copy of which
is in `schema/ITR-2_2026_Main_V1.1.json`. Read that file rather than trusting
any prose, including this. `scripts/build_itr2_json.py` builds against it and
validates locally, which is far faster than learning node names from rejection
messages.

Structural points that cost the most time to discover:

- The short-term s.111A item is `ShortTermCapGainFor23.EquityMFonSTT`, an array
  of at most two rows, each `{MFSectionCode, EquityMFonSTTDtls}` with
  `MFSectionCode` of `"1A"` for s.111A and `"5AD1biip"` for FIIs.
- The schema demands several containers this profile never uses, and they must
  be present with zeros: `NRITransacSec48Dtl`, `NRISecur115AD`,
  `SaleOnOtherAssets`, `NRISaleofForeignAsset`, `SaleofAssetNADtls`.
- Table F is `AccruOrRecOfCG`, whose five quarters are `Upto15Of6`, `Upto15Of9`,
  `Up16Of9To15Of12`, `Up16Of12To15Of3` and `Up16Of3To31Of3`.
- Schedule SI rows are `{SecCode, SplRatePercent, SplRateInc, SplRateIncTax}`,
  with `"1A"` for s.111A at 20% and `"2A"` for s.112A at 12.5%.
- `CreationInfo.Digest` accepts a literal `"-"`, so no hash is needed. But
  `SWCreatedBy` and `JSONCreatedBy` must be a registered Software Provider ID
  for the portal to accept a direct upload, which is why a self-built JSON goes
  through the offline utility instead.
- Row types differ between rows that look identical. Schedule CYLA's
  other-sources row omits the other-sources setoff column that the salary and
  capital-gains rows carry. Schedule BFLA's salary and other-sources rows have
  two columns where its capital-gains rows have three. `additionalProperties` is
  false everywhere, so getting this wrong is an error rather than a spare key.
- An employer address with no PIN code serialises as `0` and fails against the
  minimum of 100000. Supply the real PIN or leave the field out entirely.

## 7. Validation failures

The usual causes, roughly in order of frequency:

- Schedule 112A row total does not equal the Schedule CG 112A figure
- Table F quarters do not sum to the computed gain, or a quarter is negative
- `PartB-TI` written with an underscore, or `PartB_TTI` with a hyphen
- wrong or missing `SchemaVer` / `FormVer`
- invalid ISIN — must be 12 characters
- `ShareOnOrBefore` not exactly "BE" or "AE"
- decimal and rounding mismatches; total income and tax round to the nearest 10
- missing mandatory personal-info or bank fields
- an IFSC that does not match the RBI database
- PAN not linked to Aadhaar

Validating locally against `schema/ITR-2_2026_Main_V1.1.json` catches every
structural one of these before an upload attempt. It cannot catch a wrong
figure, and a file that validates is not thereby correct. The arithmetic rules
in `schema/CBDT-ITR2-Validation-Rules-AY2026-27-V1.0.pdf` are the other half:
they are stated as plain equations between fields, so they can be checked
directly, and Category A defects block the upload outright.

## 8. Pre-filing checklist

- [ ] Form correct — ITR-2, not ITR-1, and salary not professional income
- [ ] Every broker and both RTAs accounted for
- [ ] Total sale consideration ties to the AIS figure
- [ ] Debt, gold and hybrid funds classified under the **FY 2025-26** 50AA test
- [ ] 1,25,000 s.112A exemption applied once, not per statement
- [ ] Schedule 112A rows roll up to Schedule CG
- [ ] Table F sums exactly, no negatives
- [ ] Buyback appears in both Schedule OS and Schedule CG
- [ ] Every TDS entry traced to Form 26AS
- [ ] Regime chosen deliberately; no Form 10-IEA filed unnecessarily
- [ ] Tax matches the utility's own computation
- [ ] Bank account pre-validated for refund
- [ ] Filed by 31 July 2026 if any loss is being carried forward
- [ ] E-verified within 30 days
