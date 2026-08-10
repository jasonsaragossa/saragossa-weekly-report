"""
New-business target drill-in (currently Charlie Smith's £1m).

Rules (agreed with Jason, Jul 2026):
- New client = a client whose FIRST-EVER placement (start-date basis, across
  all owners, non-cancelled) started on/after 1 Jan 2025 with the tracked
  person as Client Relationship Owner on that first placement.
- Once a client qualifies, ALL placements at the client count, whoever owns them.
- Revenue = the FULL placement GP (this section only — not the split share),
  converted to GBP.
- Rolling 12 months on start date. Contract/temp placements are initial
  contracts only (extensions excluded) and reported in their own column.
"""
from datetime import date

from shared.calc import (TO_GBP, _build_fx_tables, _is_extension, parse_date,
                         _PERM_TYPE_CODE, rebate_of)
from shared.dataverse import (REBATE_FIELDS, active_or_rebated_filter,
                              get_fx_rates, odata_get_all)

NEW_CLIENT_SINCE = date(2025, 1, 1)
TARGET_GBP = 1_000_000

_CRO = "_mercury_clientrelationshipowner_value"
_CLIENT = "_crimson_clientname_value"


def _fetch_candidate_client_ids(uid: str) -> list[str]:
    """Clients where the tracked person is CRO on a placement started since the cutoff."""
    rows = odata_get_all(
        "crimson_placements",
        params={
            "$select": _CLIENT,
            "$filter": (
                f"{_CRO} eq '{uid}'"
                f" and crimson_startdate ge {NEW_CLIENT_SINCE.isoformat()}"
                f" and {active_or_rebated_filter()}"
            ),
        },
    )
    return sorted({r.get(_CLIENT) for r in rows if r.get(_CLIENT)})


def _fetch_client_placements(client_ids: list[str]) -> list[dict]:
    """ALL non-cancelled placements (any owner) at the given clients."""
    out = []
    for i in range(0, len(client_ids), 20):
        chunk = client_ids[i:i + 20]
        or_f = " or ".join(f"{_CLIENT} eq '{cid}'" for cid in chunk)
        out.extend(odata_get_all(
            "crimson_placements",
            params={
                "$select": (
                    f"crimson_placementid,{_CLIENT},crimson_startdate,crimson_name,"
                    f"crimson_type,recruit_truegrossprofit,crimson_extension,"
                    f"crimson_placementidcode,_mercury_parentplacementid_value,{_CRO},"
                    f"{REBATE_FIELDS}"
                ),
                "$filter": f"({or_f}) and {active_or_rebated_filter()}",
                "$expand": (
                    "recruit_truegrossprofitcurrency($select=isocurrencycode),"
                    "crimson_clientname($select=name),"
                    "recruit_candidatecontact($select=fullname)"
                ),
            },
        ))
    return out


def build_nb_target(uid: str, today: date = None) -> dict:
    today = today or date.today()
    roll12_start = date(today.year - 1, today.month,
                        today.day + 1 if today.day < 28 else today.day)

    try:
        fx_rates = get_fx_rates()
        to_gbp, _ = _build_fx_tables(fx_rates)
    except Exception:
        to_gbp = TO_GBP

    by_client: dict[str, list] = {}
    for p in _fetch_client_placements(_fetch_candidate_client_ids(uid)):
        if p.get("crimson_startdate"):
            by_client.setdefault(p[_CLIENT], []).append(p)

    clients = []
    for cid, rows in by_client.items():
        first_date = min(parse_date(p["crimson_startdate"]) for p in rows)
        if first_date < NEW_CLIENT_SINCE:
            continue  # existing client — not new business
        # The tracked person must be CRO on the client's first placement
        if not any(p.get(_CRO) == uid for p in rows
                   if parse_date(p["crimson_startdate"]) == first_date):
            continue

        perm12 = contract12 = 0.0
        placements = []
        for p in rows:
            d = parse_date(p["crimson_startdate"])
            # The client still counts (rebates are money-only) but the £1m
            # total credits the fee actually kept.
            reb = rebate_of(p)[0]
            gp = (p.get("recruit_truegrossprofit") or 0.0) - reb
            ccy = (p.get("recruit_truegrossprofitcurrency") or {}).get("isocurrencycode") or "GBP"
            val = gp * to_gbp.get(ccy, 1.0)
            is_perm = p.get("crimson_type") == _PERM_TYPE_CODE
            extension = (not is_perm) and _is_extension(p)
            counts = (roll12_start <= d <= today) and not extension
            if counts:
                if is_perm:
                    perm12 += val
                else:
                    contract12 += val
            placements.append({
                "job_title": p.get("crimson_name") or "(no job title)",
                "candidate": (p.get("recruit_candidatecontact") or {}).get("fullname") or "(no candidate)",
                "start_date": d.isoformat(),
                "fee": round(gp, 2),
                "currency": ccy,
                "fee_gbp": round(val, 2),
                "rebated": round(reb, 2),
                "kind": "Perm" if is_perm else ("Extension" if extension else "Contract"),
                "counts": counts,
            })
        placements.sort(key=lambda x: x["start_date"], reverse=True)

        clients.append({
            "name": (rows[0].get("crimson_clientname") or {}).get("name") or "(client)",
            "first_date": first_date.isoformat(),
            "perm12": round(perm12, 2),
            "contract12": round(contract12, 2),
            "total12": round(perm12 + contract12, 2),
            "placements": placements,
        })

    clients.sort(key=lambda c: (-c["total12"], c["name"].lower()))
    return {
        "target": TARGET_GBP,
        "since": NEW_CLIENT_SINCE.isoformat(),
        "as_of": today.isoformat(),
        "roll12_start": roll12_start.isoformat(),
        "perm_total": round(sum(c["perm12"] for c in clients), 2),
        "contract_total": round(sum(c["contract12"] for c in clients), 2),
        "clients": clients,
    }
