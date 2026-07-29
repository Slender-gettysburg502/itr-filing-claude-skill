# Source documents and reconciliation

## Contents
1. What each document is for
2. Where to download, and passwords
3. AIS structure
4. Why AIS never matches the broker statement
5. Broker and RTA statements
6. Common mismatches
7. AIS feedback

---

## 1. What each document is for

Using each document for the wrong purpose is the root of most filing errors.

| Document | Use it for | Do not use it for |
|---|---|---|
| Form 16 | salary figures, employer TDS | anything else |
| Form 26AS | **TDS credit — authoritative** | income figures |
| AIS | completeness check, spotting missed income | computing capital gains |
| TIS | seeing what the portal will pre-fill | filing positions |
| Broker/RTA CG statement | **computing capital gains** | TDS |
| Bank interest certificate | accrued RD/FD interest | — |

Where 26AS and AIS disagree on a TDS figure, **26AS wins**.

## 2. Where to download, and passwords

**Form 16** — from the employer. Part A comes from TRACES, Part B from payroll.
Part A carries the TDS section code, which decides the form (see SKILL.md).

**Form 26AS** — e-filing portal, e-File menu, which redirects to TRACES.
PDF or text.

**AIS and TIS** — e-filing portal, Services > Annual Information Statement.
Also available in the AIS mobile app and the AIS offline utility. AIS downloads
as PDF or JSON; individual categories export to CSV, which is much easier to
work with than the PDF.

Passwords, which trip everyone up:

- **AIS PDF**: PAN in **lowercase** + date of birth as DDMMYYYY, no spaces.
  PAN `AAAAA1234A` with DOB 21 Jan 1991 gives `aaaaa1234a21011991`.
- **AIS JSON**, importing into the AIS utility: PAN in **uppercase**, same date.
  `AAAAA1234A21011991`.

**Pre-filled ITR JSON** — e-filing portal, under the ITR filing flow. Only
needed for the JSON route.

## 3. AIS structure

**Part A** — general information: PAN, masked Aadhaar, name, date of birth,
contact details.

**Part B** —
1. TDS/TCS information
2. SFT information (statement of financial transactions)
3. Payment of taxes
4. Demand and refund
5. Other information

The categories that matter for a salaried investor:

- Salary
- Interest from deposits (FD and RD)
- Interest from savings bank
- Dividend
- **Sale of securities and units of mutual fund**
- Purchase of securities and units of mutual fund
- Off-market credit and debit transactions

TIS collapses all of this into a category-wise summary with a "processed value"
and a "derived value" — the derived value is what feeds the pre-fill.

## 4. Why AIS never matches the broker statement

**AIS reports sale consideration. It does not report gains.** It carries no cost
of acquisition, no holding period, and no grandfathered FMV, so it cannot
compute a profit and does not try to.

This means the reconciliation is not "make AIS match the P&L" — that will never
happen and chasing it wastes hours. The correct check is:

```
sum of sale_value across all broker/RTA rows  ==  AIS "Sale of securities
                                                   and units of mutual fund"
```

`build_worksheet.py` prints that total for exactly this purpose. If it falls
short, a broker or RTA statement is missing. If it overshoots, look for
duplicate reporting.

## 5. Broker and RTA statements

**Zerodha** — console.zerodha.com, Tax P&L. Not the Kite app. Select FY 2025-26
and download CSV per segment. Mutual funds held through Coin appear separately.
Zerodha applies s.112A grandfathering for holdings from on or before
31 Jan 2018, and lists buyback trades separately so they can be excluded from
ordinary STCG. Note that it is not a government document — the underlying
references remain the contract notes and AIS.

**Groww** — Profile > Reports > Tax.
**Upstox** — Reports > P&L.
**ICICI Direct** — My Account > Reports > Tax Reports.
**HDFC Securities** — Reports / Tax P&L.

**CAMS and KFintech** — consolidated mutual-fund capital-gains statements, each
covering the AMCs it services. CAMS handles HDFC, ICICI Prudential, SBI, Nippon,
Axis and others; KFintech covers the rest. **Both are needed**, or funds go
missing. **MF Central** gives a combined view. KFintech's main sheet is spelt
`Trasaction_Details` — that typo is theirs and is stable, so scripts can key on
it.

Typical columns across all of these: ISIN, scrip or scheme name, quantity, buy
date, buy value, sale date, sale value, STT, brokerage and charges, FMV as on
31-Jan-2018 where relevant, realised profit or loss, and an STCG/LTCG label with
holding period. Excel and CSV are processable; PDF is not, and asking for the
Excel version saves an hour of transcription.

The consolidated statements already apply grandfathering and label asset types.
What they cannot do is aggregate across providers, so three things stay the
filer's job: verifying the 50AA classification for debt and hybrid funds,
applying the 1,25,000 s.112A exemption once across everything, and summing
across all brokers and both RTAs.

## 6. Common mismatches

Expected, not alarming. Flag them and ask rather than silently adjusting:

- **Duplicate reporting** — the broker and the depository (NSDL or CDSL) both
  report the same trade
- **Gross versus net** — some feeds report before charges, others after
- **Corporate actions** — bonus issues, splits and mergers generate entries that
  look like trades but are not
- **Off-market transfers** — gifts and inter-demat moves show as credits and
  debits, not sales
- **Buyback** — reported separately since 1 October 2024, and now a deemed
  dividend rather than a capital receipt
- **RD interest** — AIS shows accrued interest annually; the bank may have
  credited nothing yet

## 7. AIS feedback

AIS accepts online feedback per transaction: information is duplicate, relates
to another PAN or year, amount is incorrect, or denied. The reported and
modified values are shown separately and the TIS derived value updates.

Practical advice: **do not hold up the return waiting for the reporting entity
to respond.** File with the correct figure from the taxpayer's own records and
submit the feedback in parallel. Keep the supporting statement in case of a
later query.
