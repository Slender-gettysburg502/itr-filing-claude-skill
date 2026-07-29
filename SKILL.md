---
name: itr2-india
description: End-to-end help filing an Indian ITR-2 for AY 2026-27 (FY 2025-26) for a salaried person with capital gains from shares and mutual funds, plus interest from RD/FD/savings. Parses Form 16, AIS, TIS, Form 26AS and broker/RTA capital-gains statements, reconciles them, classifies every gain under the current s.111A/112A/50AA rules, compares old vs new regime, and patches the portal's pre-filled JSON for upload. Use this whenever someone mentions ITR, ITR-2, income tax return, Form 16, AIS, 26AS, TIS, Schedule 112A, capital gains tax in India, LTCG or STCG on equity, debt mutual fund taxation, the new tax regime vs old regime, or asks for help with Indian tax filing, even if they do not name the form. Also use it for adjacent questions like "how much tax do I owe on my stock sales", "which regime should I pick", or "why does my AIS not match my broker statement".
---

# ITR-2 filing assistant (India, AY 2026-27)

Filing ITR-2 by hand is mostly a reconciliation problem, not a tax-law problem.
Four documents describe the same year from four angles and none of them agree.
The work is getting them to agree, classifying each capital gain correctly, and
then not fat-fingering the transfer into the form.

This skill covers a specific profile: **salaried, resident, with listed
equity/mutual-fund gains and deposit interest.** Everything below assumes
FY 2025-26 rules, which differ from FY 2024-25 in several ways that quietly
break carried-over habits.

## Before anything else: is ITR-2 even the right form?

Run this gate first. Getting it wrong wastes the entire downstream effort.

**Check how the employer paid them.** Look at the TDS section code in Form 26AS,
and at which certificate they hold:

| Evidence | Meaning | Form |
|---|---|---|
| Form 16, TDS under **section 192** | Salary | ITR-2 |
| Form 16A, TDS under **section 194J** | Professional fees | ITR-3 (or ITR-4 under 44ADA) |

This matters a lot for hospital doctors. Senior Residents and Junior Residents
are sometimes on payroll (192) and sometimes engaged as consultants (194J), and
the two go to different forms. If you see 194J, **stop and ask** whether they
have an employment contract or a consultancy arrangement. Do not auto-route.
The TDS section is strong evidence but not legally decisive — several ITAT
benches have held that 194J is a withholding mechanic and does not by itself
make income professional. When it is genuinely ambiguous, that is a
chartered-accountant question, not a thing to guess at.

**Then confirm ITR-2 over ITR-1.** ITR-1 now allows up to Rs 1,25,000 of bare
s.112A LTCG, which tempts people. But ITR-2 becomes mandatory the moment any of
these is true, and for anyone who actually trades, at least one always is:

- any STCG at all, even one rupee under s.111A
- s.112A LTCG above Rs 1,25,000
- any capital gain outside 112A — debt funds, gold, property, unlisted
- any capital loss to set off or carry forward
- income above Rs 50 lakh, foreign assets, unlisted shares, directorship, NRI/RNOR

Default to ITR-2 whenever in doubt. Filing ITR-1 wrongly gets the return marked
defective.

## Workflow

### 1. Gather

Ask for these. Tell them where each lives, because "download your AIS" is not
self-explanatory to most people:

- **Form 16** — from the employer (Part A from TRACES, Part B from payroll)
- **Form 26AS** — e-filing portal, redirects to TRACES. This is the authoritative
  record for TDS credit.
- **AIS and TIS** — e-filing portal, Services > Annual Information Statement.
  Download AIS as JSON if offered, PDF otherwise.
- **Capital gains statements** — Zerodha Console (Tax P&L, not the Kite app),
  Groww Reports, Upstox, ICICI Direct Tax Reports, and **CAMS + KFintech**
  consolidated statements for mutual funds. MF Central gives a combined view.
  They need *every* broker and both RTAs, or gains go missing.
- **Bank interest certificates** — for RD/FD accrued interest.
- **Pre-filled JSON** — e-filing portal, only if generating a JSON (step 5).

The AIS PDF is password-protected: **PAN in lowercase + date of birth as
DDMMYYYY**, no spaces. The AIS *JSON* uses PAN in uppercase with the same date.
Read `references/documents.md` for the full document map, AIS category
structure, and what each broker's statement contains.

### 2. Reconcile

The single most common error is treating AIS as a source of gains. **AIS reports
sale consideration, not profit.** It will never match a broker's realised P&L,
and that mismatch is expected, not a problem to solve.

Use each document for what it is actually good for:

- Broker/RTA statements → **compute the gains** (they carry cost, sale value,
  grandfathered FMV, holding period)
- AIS → **completeness check only**. Tie total sale consideration across all
  broker statements to the AIS "Sale of securities and units of mutual fund"
  figure. A gap means a missing statement.
- 26AS → **TDS credit**. Where 26AS and AIS disagree on TDS, 26AS wins.
- Interest certificates → cross-check AIS "Interest from deposits".

Flag mismatches rather than silently reconciling them. Duplicate reporting by
broker and depository, off-market transfers shown as sales, and corporate
actions creating phantom entries are all routine. If a genuine AIS error turns
up, file with the correct figure from their own records and submit AIS feedback
in parallel — waiting on the reporting entity is not a strategy.

### 3. Build the capital-gains worksheet

Consolidate every broker and RTA row into one CSV using
`assets/ledger_template.csv` as the shape, then:

```bash
python scripts/build_worksheet.py ledger.csv --outdir work/
```

This classifies each row, applies s.112A grandfathering against the 31-Jan-2018
FMV, applies the Rs 1,25,000 exemption **once across all sources** (a single
broker's statement cannot know about the others), and emits the Schedule 112A
table plus the Table F quarter-wise split.

The `asset_class` column is where judgement is required, and it is worth slowing
down on. The s.50AA definition of a "specified mutual fund" **changed for FY
2025-26**: it now means >65% in debt and money-market instruments, where it used
to mean ≤35% in domestic equity. Gold ETFs and international funds that were
caught by the old test are usually outside 50AA now and get normal treatment.
Anyone applying last year's classification will get this wrong. Hybrid funds
depend on their actual allocation and the script deliberately refuses to guess —
resolve them against the scheme's AMFI category.

Read `references/tax-rules-fy2025-26.md` for the full classification rules,
holding periods, and the grandfathering formula.

### 4. Compute tax under both regimes

Fill in `assets/taxpayer_input_template.json`, paste in the `capital_gains`
block from `work/worksheet.json`, then:

```bash
python scripts/compute_tax.py taxpayer.json --json work/computation.json
```

This prints both regimes side by side with a recommendation. A few things worth
explaining to the person rather than just showing them a number:

- **The Rs 60,000 rebate does not cover capital gains.** Under the new regime,
  income up to Rs 12,00,000 pays no tax — but that rebate applies to normal-rate
  income only. Tax on s.111A and s.112A gains is still payable. People find this
  surprising and it is the most common source of "why do I owe money when I earn
  under 12 lakh".
- **Capital-gains rates are identical in both regimes.** Regime choice only moves
  the salary and interest side of the calculation.
- If a resident's normal income falls below the basic exemption limit, the unused
  slice can be set against special-rate gains. This works in both regimes, and
  not for non-residents.
- The old regime is not the default. If it wins, the choice is made inside the
  return before the 31-Jul-2026 due date. **Form 10-IEA is not required** for
  someone with only salary, capital gains and interest — filing it anyway is a
  common and avoidable mistake.

### 5. Fill the return

Two routes. Recommend the first unless they specifically want a JSON.

**Route A — fill the portal directly.** Give them a schedule-by-schedule
mapping of the computed numbers, in the order the form asks for them. Read
`references/itr2-schedules.md` and produce it as a checklist they can work
through. This is the lower-risk path and it is what most people should do.

**Route B — build the JSON.** Two things make this work, and both are required.

First, get the department's own artefacts: the ITR-2 schema and the validation
rules, both from incometax.gov.in under Downloads. `schema/` holds the AY
2026-27 copies. Build against the schema and validate locally, and the guesswork
disappears. `scripts/build_itr2_json.py` does this from a plain input file:

```bash
cp assets/itr2_json_input_template.json my_return.json   # then edit it
python scripts/build_itr2_json.py my_return.json -o filled.json
```

It covers the profile in this skill and nothing else: new regime, salary,
interest, dividends, s.111A and s.112A. It refuses rather than guessing on the
old regime, capital losses, or anything needing a schedule it does not build.

Second, know how the file gets in. **The portal's direct JSON upload only
accepts files stamped with a registered Software Provider ID**, which is issued
to approved vendors. A self-built JSON is rejected with "Invalid Software
Provider ID" before any figure is looked at. So the JSON is not the upload, it
is the *input to the offline utility*: open the Common Offline Utility, choose
Import Draft ITR JSON, and file from there. That turns an hour of typing into a
few minutes of review.

If the pre-fill has values worth keeping, `patch_prefill_json.py` still edits it
in place, discovering paths with `--inspect` and `--find` rather than assuming
them. Be aware the pre-fill is a different shape from the return JSON, and for a
filer whose employer deducted no TDS it will carry no salary or capital-gains
nodes at all.

**Either way, the offline utility validates and recomputes, and it is the
authority.** If its tax differs from `compute_tax.py`, the utility is right and
something upstream is misclassified.

Three failures worth knowing before you meet them:

- A blank employer PIN code serialises as `0` and fails with "0 is not greater
  or equal to 100000". Supply a real PIN or omit the field.
- Schedule CYLA's other-sources row uses a different row type from the rest, and
  reusing the common one is an `additionalProperties` error.
- Schedule BFLA's salary and other-sources rows take two columns, while the
  capital-gains rows take three.

### 6. Verify before filing

Walk them through this. Read `references/itr2-schedules.md` for the full list.

- Schedule 112A row total rolls up to the Schedule CG 112A figure
- Table F quarters sum exactly to the computed gain, with no negative entries
  (the utility rejects them — clamp losing quarters to zero and redistribute)
- Every TDS entry traces to Form 26AS
- Buyback proceeds appear as deemed dividend in Schedule OS — the matching
  capital loss is only allowed if that disclosure is made
- Bank account pre-validated for the refund
- **File by 31 July 2026.** A belated return still gets filed, but capital-loss
  carry-forward is forfeited, which can be worth far more than the late fee.
- **E-verify within 30 days.** An unverified return is not a filed return.

## When to hand off to a chartered accountant

Say so plainly rather than pressing on. The threshold is lower than people
expect, and the cost of a wrong return exceeds a CA's fee:

- 194J income where the employment relationship is genuinely unclear
- F&O or intraday trading (business income, ITR-3, possibly audit)
- foreign assets, RSUs, ESOPs, or any Schedule FA trigger
- property sale with a s.54/54F exemption claim
- NRI or RNOR residential status
- total income near or above Rs 1 crore (Schedule AL, surcharge)
- debt or hybrid fund redemptions where 50AA classification stays unresolved

Be useful about the parts that are clear, and honest about the parts that are
not. Present computed figures as a working draft to be checked against the
utility, never as a filed position.

## Files

- `references/tax-rules-fy2025-26.md` — rates, regimes, capital-gains
  classification, interest income, deadlines, and what changed from FY 2024-25
- `references/documents.md` — AIS/TIS/26AS/Form 16/broker statements: where to
  get them, passwords, structure, reconciliation
- `references/itr2-schedules.md` — schedule-by-schedule mapping, Schedule 112A
  columns, JSON schema notes, validation failures
- `scripts/build_worksheet.py` — capital-gains ledger to ITR-2 figures
- `scripts/compute_tax.py` — both-regime computation with 234B/234C
- `scripts/build_itr2_json.py` — build and schema-validate the return JSON
- `scripts/schema_validate.py` — Draft-04 validator using only the standard
  library, so validation still runs where `jsonschema` is not installed. Also
  audits its own keyword coverage, so a pass cannot quietly mean nothing ran
- `scripts/package_for_claude_app.py` — package the skill as a ZIP the Claude
  app accepts, for claude.ai rather than Claude Code
- `scripts/patch_prefill_json.py` — inspect and edit the pre-filled JSON
- `schema/ITR-2_2026_Main_V1.1.json` — the department's published schema
- `schema/CBDT-ITR2-Validation-Rules-AY2026-27-V1.0.pdf` — the validation rules
- `assets/ledger_template.csv`, `assets/taxpayer_input_template.json`,
  `assets/itr2_json_input_template.json`
