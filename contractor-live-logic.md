# Contractor Live Logic — Reference Spec

*For any app that needs to determine whether a contractor is currently live, count headcount, or track contractor movement over time.*

*Source: Saragossa Client Dashboard, confirmed against live Dataverse data June 2026.*

---

## Core Rule

A contractor is **live at a given point in time** when:

```
startDate <= point AND effectiveEndDate >= point
```

Where:

| Concept | Dataverse Field | Notes |
|---|---|---|
| Start date | `crimson_startdate` | When the contractor begins on site |
| Original end date | `crimson_enddate` | The end date given at start of contract |
| Actual end date | `crimson_actualenddate` | When the contract actually ended (early leaver, conversion to perm, etc). Null if still running on original terms |
| **Effective end date** | `min(crimson_actualenddate, crimson_enddate)` | **Whichever is earliest.** If actual is null, use original. If both are set, take the earlier one — the contractor left before the original end |

### Placement types included

Only contract and temporary placements count as contractors:

| Type | `crimson_type` value |
|---|---|
| Contract | `143570001` |
| Temporary | `143570002` |

Permanent placements (`143570000`) are never contractors.

### Status exclusions

The live check is **date-based, not status-based**. Status is ignored for determining liveness, with one exception:

| Excluded status | `statuscode` value | Reason |
|---|---|---|
| Cancelled — Candidate did not start | `143570009` | The contractor never arrived on site. Exclude from all counts |

All other statuses (Live, Ending Soon, Complete, Awaiting Start, Paperwork Sent, Awaiting Paperwork) are **not filtered** — the dates tell the truth.

### No other exclusions

Every contractor counts regardless of:

- Consultant (including Amy Blackmore)
- Client (including Saragossa House Deploy / Component)
- Territory or region
- Whether the placement has a solution set

Headcount is bodies on site. Ownership splits (CRO/Consultant/AO/CONRO) do not apply.

---

## Extensions and Deduplication

A contractor can have an original placement plus one or more extensions. These are separate records in `crimson_placement` that represent the same person continuing on site. They must be **deduped to one body**.

### Identifying extensions

A placement is an extension if:

```
_mercury_parentplacementid_value IS NOT NULL
OR crimson_extension > 0
```

Secondary check via `crimson_placementidcode`:

```
Format: 004701/00/02
         ^^^^^^ ^^ ^^
         │      │  └─ version
         │      └──── extension segment (00 = original, 01/02/03 = extension)
         └─────────── root placement number
```

Middle segment `00` = new placement. Anything else = extension.

### Dedupe key

Group all records by the **root placement number** — the first segment of `crimson_placementidcode`:

```
004701/00/00  ─┐
004701/01/00   ├─ same body, root = "004701"
004701/02/00  ─┘
```

If `crimson_placementidcode` is null, fall back to `crimson_placementid` (the record GUID) as the group key.

### Live check across a group

A contractor (root group) is live at a point if **any record** in the group is live at that point:

```
rootIsLive(records, point) =
  records.ANY(r =>
    r.startDate <= point
    AND min(r.actualEndDate, r.originalEndDate) >= point
  )
```

This handles overlapping or back-to-back extensions correctly.

---

## Solution Bucketing

Each contractor is assigned to a solution bucket based on the `mxconsul_solution` field on the placement record.

| Dataverse field | `_mxconsul_solution_value` (Lookup to Product table) |
|---|---|
| Display value | `_mxconsul_solution_value@OData.Community.Display.V1.FormattedValue` |
| Possible values | `Connect`, `Consult`, `Deploy`, or null |

### Bucket assignment for a root group

Use the **most recent record** that has a solution set (walk newest → oldest by extension segment). This is important because original placements created before solutions were being set may have no value, while their extensions do.

```
rootSolution(records) =
  sort records by extension segment descending
  for each record:
    if solution IN ('Connect', 'Consult', 'Deploy'): return solution
  return 'Unassigned'
```

| Bucket | Rule |
|---|---|
| Connect | `solution = 'Connect'` |
| Consult | `solution = 'Consult'` |
| Deploy | `solution = 'Deploy'` (both contract and temporary types combined) |
| Unassigned | No record in the group has a solution set |

---

## Period Metrics

For any given period (month, week, year), four numbers per bucket:

| Metric | Definition | Extensions included? |
|---|---|---|
| **Opening** | Count of root groups live at period start date | Yes — any record covering the date counts |
| **Starters** | Count of **new placements only** starting in the period | **No** — extensions are the same person continuing |
| **Finishers** | Count of root groups whose latest effective end falls in the period **AND who are NOT live at period end** | Yes — but only if no extension keeps them going |
| **Closing** | Count of root groups live at period end date | Yes |

### Starter detection

A placement is a new start (not an extension) when the middle segment of `crimson_placementidcode` is `00`:

```
isNewPlacement = placementIdCode.split('/')[1] === '00'
```

### Finisher detection

A root group is a finisher in a period when:

```
latestEffectiveEnd(records) >= periodStart
AND latestEffectiveEnd(records) <= periodEnd
AND NOT rootIsLive(records, periodEnd)
```

The `NOT rootIsLive` check ensures contractors with extensions that continue past the period are not counted as finishers.

### Reconciliation

```
Opening + Starters − Finishers ≈ Closing
```

This will be exact in most cases. The only scenario where it won't reconcile is an "extension reviver" — a contractor whose previous record ended before the period start but receives an extension starting mid-period, making them live at period end without being counted as a starter. This is rare in practice.

---

## Key Dataverse Fields Summary

All fields are on the `crimson_placement` entity (`crimson_placements` in OData plural).

| Field | OData name in `$select` | Purpose |
|---|---|---|
| Placement ID | `crimson_placementid` | Primary key (GUID) |
| Placement ID code | `crimson_placementidcode` | Human-readable code, e.g. `004701/00/02`. Used for root grouping and extension detection |
| Job title | `crimson_name` | Display name of the placement |
| Type | `crimson_type` | `143570000` = Permanent, `143570001` = Contract, `143570002` = Temporary |
| Status | `statuscode` | Used only for exclusion of `143570009` (Cancelled — did not start) |
| State | `statecode` | Filter to `0` (active records only) |
| Start date | `crimson_startdate` | Contract start |
| Original end date | `crimson_enddate` | Originally agreed end |
| Actual end date | `crimson_actualenddate` | Actual end (early leaver / conversion). Null if running to plan |
| Extension flag | `crimson_extension` | `> 0` = extension record |
| Parent placement | `_mercury_parentplacementid_value` | GUID of the original placement this extends. Null on originals |
| Solution | `_mxconsul_solution_value` | Lookup to Product table. Use formatted value annotation for label |
| Client | `_crimson_clientname_value` | Lookup to account |
| Consultant | `_crimson_consultant_value` | Lookup to systemuser |
| CRO | `mercury_clientrelationshipowner` | Lookup to systemuser (expand for fullname) |
| AO | `mercury_assignmentowner` | Lookup to systemuser (expand for fullname) |
| Candidate | `recruit_candidatecontact` | Lookup to contact (expand for fullname) |
| Pay rate | `mercury_pay_mc` | Contractor pay rate (raw, in placement currency) |
| Charge rate | `mercury_charge_mc` | Client charge rate (raw, in placement currency) |
| WNF | `recruit_trueweeklygrossprofit` | Weekly net fee |
| GP currency | `_recruit_truegrossprofitcurrency_value` | Lookup to transactioncurrency |

### OData query pattern

```
crimson_placements?
  $select=crimson_placementid,crimson_name,crimson_placementidcode,
    crimson_type,_mercury_parentplacementid_value,crimson_extension,
    crimson_startdate,crimson_enddate,crimson_actualenddate,
    statuscode,statecode,_mxconsul_solution_value,
    _crimson_clientname_value,_crimson_consultant_value,
    mercury_pay_mc,mercury_charge_mc,recruit_trueweeklygrossprofit
  &$filter=statecode eq 0
  &$expand=
    crimson_consultant($select=fullname),
    crimson_clientname($select=name),
    recruit_candidatecontact($select=fullname),
    mercury_clientrelationshipowner($select=fullname),
    mercury_assignmentowner($select=fullname)
```

Note: use `Prefer: odata.include-annotations="*"` header to get formatted value annotations (solution label, currency name, etc) automatically.

---

## Status Code Reference (for display, not filtering)

| `statuscode` | Label | Notes |
|---|---|---|
| `1` | Live | Active on site |
| `939310010` | Ending Soon | Contract approaching end |
| `939310009` | Awaiting Start | Not yet started |
| `939310005` | Awaiting Paperwork | Pre-start admin |
| `143570000` | Paperwork Sent | Pre-start admin |
| `143570002` | Complete | Contract finished |
| `143570009` | Cancelled — Candidate did not start | **Excluded from all counts** |

---

*Saragossa · Internal use only*
