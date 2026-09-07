"""
Pull finance's monthly commission workbooks from SharePoint and load them.

Deanna publishes two workbooks a month into the Finance library, one per
ledger. This walks the year folder, picks the right file for each month, and
imports it the same way the manual upload does.

The folder is not tidy enough to import blindly, and every import replaces a
whole month, so the rules are deliberately conservative:

  * the month comes from the folder, but a filename that names a DIFFERENT
    month is treated as a conflict and skipped — the Apr-26 folder has held a
    file called "Deploy & Component Summary - May 26.xlsx" which really was
    May's data, so trusting either one alone files it under the wrong month;
  * a file marked "Actual" beats one without, which is how the two May deploy
    files differ;
  * anything still ambiguous — two candidate files, or a folder whose month
    cannot be read — is SKIPPED and reported, never guessed at.

Needs Microsoft Graph application permission to read the library (Sites.Selected
granted on the Finance site, or Sites.Read.All). Without it every call fails
with a clear message rather than importing nothing quietly.
"""
import logging
import os
import re
from datetime import date

import requests

from shared.commission_import import (match_to_users, month_from_filename,
                                      parse_workbook)
from shared.dataverse import (_graph_token, get_all_named_users,
                              get_all_territory_consultants, replace_month_entries)

GRAPH = "https://graph.microsoft.com/v1.0"
TIMEOUT = 60

# OneDrive syncs this library as "Finance - Documents", i.e. site "Finance",
# library "Documents". Both are overridable without a deploy.
SITE = os.environ.get("COMMISSION_SYNC_SITE", "saragossa.sharepoint.com:/sites/Finance")
ROOT = os.environ.get(
    "COMMISSION_SYNC_PATH",
    "Saragossa Ltd (UK)/Staff Payroll and Commission/Sales Commission and Incentives"
    "/Component and Contract Commission")

MONTHS = ("jan", "feb", "mar", "apr", "may", "jun",
          "jul", "aug", "sep", "oct", "nov", "dec")


class SyncError(RuntimeError):
    """Raised with a message meant to be read by a person."""


def _get(url: str, **kw):
    resp = requests.get(url, headers={"Authorization": f"Bearer {_graph_token()}"},
                        timeout=TIMEOUT, **kw)
    if resp.status_code in (401, 403):
        raise SyncError(
            "Microsoft Graph refused access to the Finance library. The app "
            "registration needs Sites.Selected on that site (or Sites.Read.All) "
            f"with admin consent. Graph said: {resp.status_code}.")
    if resp.status_code == 404:
        raise SyncError(f"Not found in SharePoint: {url.split('/root:')[-1][:120]}")
    if not resp.ok:
        raise SyncError(f"Graph {resp.status_code}: {resp.text[:300]}")
    return resp


def _drive_id() -> str:
    """
    The default document library of the Finance site.

    The site is resolved to its id first. Addressing it by path and appending
    a relation in one go ("/sites/host:/sites/X/drive") makes Graph read
    "/drive" as part of the site path and answer 404.
    """
    site_id = _get(f"{GRAPH}/sites/{SITE}").json()["id"]
    return _get(f"{GRAPH}/sites/{site_id}/drive").json()["id"]


def _children(drive: str, path: str) -> list:
    url = f"{GRAPH}/drives/{drive}/root:/{path}:/children"
    out, params = [], {"$top": "200"}
    while url:
        data = _get(url, params=params).json()
        out.extend(data.get("value", []))
        url, params = data.get("@odata.nextLink"), None
    return out


def folder_month(name: str):
    """Month number from a folder like '4. Apr-26' or '8. August-26', else None."""
    low = name.lower()
    for i, mon in enumerate(MONTHS, 1):
        if re.search(rf"\b{mon}", low):
            return i
    return None


def _kind_of(filename: str):
    low = filename.lower()
    if low.startswith("contract commission"):
        return "contract"
    if low.startswith("deploy"):
        return "solution"
    return None


def pick_files(entries: list) -> dict:
    """
    {kind: (name, download_url)} for one month folder.
    Returns a kind only when the choice is unambiguous; ties are left out so
    the caller can report them rather than import the wrong draft.
    """
    by_kind = {}
    for e in entries:
        if "file" not in e:
            continue
        kind = _kind_of(e["name"])
        if kind:
            by_kind.setdefault(kind, []).append(e)

    chosen, ambiguous = {}, {}
    for kind, files in by_kind.items():
        if len(files) > 1:
            # "…- Actual.xlsx" is finance's own marker for the final version.
            actual = [f for f in files if "actual" in f["name"].lower()]
            if len(actual) == 1:
                files = actual
            else:
                ambiguous[kind] = [f["name"] for f in files]
                continue
        chosen[kind] = files[0]
    return {"chosen": chosen, "ambiguous": ambiguous}


def sync_year(year: int, months: list = None, commit: bool = False) -> dict:
    """
    Walk the year folder and import each month's workbooks.

    months: restrict to these month numbers (default: every folder found).
    commit: False previews without writing.
    Returns {"imported": [...], "skipped": [...], "year": year}.
    """
    drive = _drive_id()
    users = get_all_named_users()
    shown = {c["systemuserid"] for c in get_all_territory_consultants()}

    imported, skipped = [], []
    for folder in _children(drive, f"{ROOT}/{year}"):
        if "folder" not in folder:
            continue
        month = folder_month(folder["name"])
        if not month:
            continue  # e.g. "Illustrations"
        if months and month not in months:
            continue

        entries = _children(drive, f"{ROOT}/{year}/{folder['name']}")
        picked = pick_files(entries)
        for kind, names in picked["ambiguous"].items():
            skipped.append({"month": month, "kind": kind, "folder": folder["name"],
                            "reason": f"more than one candidate: {', '.join(names)}"})

        for kind, entry in picked["chosen"].items():
            named = month_from_filename(entry["name"])
            if named and named[1] != month:
                skipped.append({
                    "month": month, "kind": kind, "file": entry["name"],
                    "reason": f"filed under {MONTHS[month - 1].title()} but named "
                              f"{MONTHS[named[1] - 1].title()} — check which month it is"})
                continue
            url = entry.get("@microsoft.graph.downloadUrl")
            if not url:
                skipped.append({"month": month, "kind": kind, "file": entry["name"],
                                "reason": "no download link from Graph"})
                continue
            try:
                data = requests.get(url, timeout=TIMEOUT).content
                parsed = parse_workbook(data)
            except (ValueError, requests.RequestException) as exc:
                skipped.append({"month": month, "kind": kind, "file": entry["name"],
                                "reason": str(exc)[:200]})
                continue
            if parsed["kind"] != kind:
                # Named like one ledger's workbook, shaped like the other's.
                skipped.append({"month": month, "kind": kind, "file": entry["name"],
                                "reason": f"contents look like the {parsed['kind']} workbook"})
                continue

            m = match_to_users(parsed["totals"], users)
            matched = [r for r in m["matched"] if r["uid"] in shown]
            amounts = {}
            for row in matched:
                amounts[row["uid"]] = amounts.get(row["uid"], 0) + row["amount"]

            entry_out = {
                "month": month, "kind": kind, "file": entry["name"],
                "people": len(amounts),
                "total": round(sum(amounts.values()), 2),
                "file_total": round(sum(parsed["totals"].values()), 2),
                "skipped_names": [u["name"] for u in m["unmatched"]],
            }
            if commit:
                entry_out.update(replace_month_entries(kind, year, month, amounts))
            imported.append(entry_out)

    imported.sort(key=lambda r: (r["month"], r["kind"]))
    skipped.sort(key=lambda r: r["month"])
    return {"year": year, "imported": imported, "skipped": skipped, "committed": commit}


def compose_report(result: dict) -> tuple:
    """(subject, text) summarising a sync run, for the notification email."""
    year = result["year"]
    did = "Imported" if result["committed"] else "Would import"
    lines = [f"Commission sync — {year}", ""]
    if result["imported"]:
        lines.append(f"{did}:")
        for r in result["imported"]:
            label = "Contract" if r["kind"] == "contract" else "Deploy & Consult"
            note = ""
            if r["file_total"] and abs(r["file_total"] - r["total"]) >= 1:
                note = f" ({r['file_total'] - r['total']:,.0f} skipped)"
            lines.append(f"  {MONTHS[r['month'] - 1].title()} {label}: "
                         f"{r['people']} people, {r['total']:,.0f}{note}  [{r['file']}]")
    else:
        lines.append("Nothing to import.")
    if result["skipped"]:
        lines += ["", "Skipped — needs a look:"]
        for r in result["skipped"]:
            label = "Contract" if r["kind"] == "contract" else "Deploy & Consult"
            lines.append(f"  {MONTHS[r['month'] - 1].title()} {label}: {r['reason']}")
    subject = (f"Commission sync {year}: {len(result['imported'])} imported"
               + (f", {len(result['skipped'])} skipped" if result["skipped"] else ""))
    return subject, "\n".join(lines)


def is_second_friday(day: date = None) -> bool:
    day = day or date.today()
    return day.weekday() == 4 and 8 <= day.day <= 14
