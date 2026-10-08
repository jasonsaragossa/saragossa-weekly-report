"""
Build the blank Excel templates the Contract MBR export fills in.

    python scripts/build_mbr_templates.py <director.xlsx> <consultant.xlsx>

The sources are Jonny's own 2026 workbooks (the Director sheet, and a
consultant's — Louis's is the current layout). Their figures are emptied and
their other working sheets (deal trackers, people, customer review) cleared, so
the templates carry Jonny's layout, colours, formulas and charts, but none of
his data. Excel's shared-string table is rebuilt too, so no client or person
name from the source survives hidden inside the file.

Writes api/templates/mbr_director.xlsx and api/templates/mbr_consultant.xlsx.
"""
import io
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "api"))
from shared.xlsx_cells import _CELL, _ROW, col_index, drop_cached_formula_results  # noqa: E402

FIGURE_COLS = set("CDEFGHIJKLMNOPQRSTU")


def clear_numbers(xml: str, cols=None, from_row=2, keep_cols=()) -> str:
    """Empty every typed number (not formulas, not text) from `from_row` down."""
    def fix(c):
        cell, col, row = c.group(0), c.group(1), int(c.group(2))
        if row < from_row or col in keep_cols or (cols and col not in cols):
            return cell
        if "<f>" in cell or "<f " in cell or 't="s"' in cell or 't="inlineStr"' in cell or 't="str"' in cell:
            return cell
        if "<v>" not in cell:
            return cell
        s = re.search(r'\bs="\d+"', cell.split(">", 1)[0])
        return f'<c r="{col}{row}"{(" " + s.group(0)) if s else ""}/>'
    return _CELL.sub(fix, xml)


def drop_rows(xml: str, from_row: int) -> str:
    """Empty every cell from `from_row` down, keeping the rows and cell styles —
    deleting the rows themselves breaks sheets laid out as Excel tables."""
    def fix(c):
        col, row = c.group(1), int(c.group(2))
        if row < from_row:
            return c.group(0)
        s = re.search(r'\bs="\d+"', c.group(0).split(">", 1)[0])
        return f'<c r="{col}{row}"{(" " + s.group(0)) if s else ""}/>'
    return _CELL.sub(fix, xml)


def rebuild_shared_strings(parts: dict) -> None:
    """Keep only the strings still used, renumbered, across every sheet."""
    sst = parts["xl/sharedStrings.xml"].decode("utf-8")
    items = re.findall(r"<si>.*?</si>|<si/>", sst, re.S)
    sheets = [n for n in parts if re.match(r"xl/worksheets/sheet\d+\.xml$", n)]
    used = []
    pat = re.compile(r'(<c\b[^>]*\bt="s"[^>]*>(?:(?!</c>).)*?<v>)(\d+)(</v>)', re.S)
    for n in sheets:
        for m in pat.finditer(parts[n].decode("utf-8")):
            i = int(m.group(2))
            if i not in used:
                used.append(i)
    new_index = {old: new for new, old in enumerate(used)}
    for n in sheets:
        xml = parts[n].decode("utf-8")
        xml = pat.sub(lambda m: f"{m.group(1)}{new_index[int(m.group(2))]}{m.group(3)}", xml)
        parts[n] = xml.encode("utf-8")
    head = sst[:sst.index("<si")] if "<si" in sst else sst.replace("</sst>", "")
    head = re.sub(r'\bcount="\d+"', f'count="{len(used)}"', head)
    head = re.sub(r'\buniqueCount="\d+"', f'uniqueCount="{len(used)}"', head)
    parts["xl/sharedStrings.xml"] = (head + "".join(items[i] for i in used) + "</sst>").encode("utf-8")


def sheet_paths(parts: dict) -> dict:
    wb = parts["xl/workbook.xml"].decode("utf-8")
    rels = parts["xl/_rels/workbook.xml.rels"].decode("utf-8")
    targets = {}
    for rel in re.findall(r"<Relationship\b[^>]*/>", rels):
        rid = re.search(r'Id="([^"]+)"', rel).group(1)
        targets[rid] = "xl/" + re.search(r'Target="([^"]+)"', rel).group(1).lstrip("/").replace("xl/", "")
    return {name: targets[rid] for name, rid in
            re.findall(r'<sheet\b[^>]*name="([^"]+)"[^>]*r:id="([^"]+)"', wb)}


def build(src: str, dst: pathlib.Path, plan: dict) -> None:
    z = zipfile.ZipFile(src)
    parts = {i.filename: z.read(i.filename) for i in z.infolist()}
    paths = sheet_paths(parts)
    for sheet, fn in plan.items():
        p = paths[sheet]
        parts[p] = drop_cached_formula_results(fn(parts[p].decode("utf-8"))).encode("utf-8")
    rebuild_shared_strings(parts)
    # Excel's index of formula cells still lists the formulas just emptied, and
    # it won't open a file whose index is wrong. Excel rebuilds it on opening.
    if "xl/calcChain.xml" in parts:
        del parts["xl/calcChain.xml"]
        parts["[Content_Types].xml"] = re.sub(
            rb'<Override[^>]*PartName="/xl/calcChain\.xml"[^>]*/>', b"", parts["[Content_Types].xml"])
        parts["xl/_rels/workbook.xml.rels"] = re.sub(
            rb'<Relationship[^>]*Target="[^"]*calcChain\.xml"[^>]*/>', b"", parts["xl/_rels/workbook.xml.rels"])
    # Nothing of the source's author or edit history either
    for meta in ("docProps/core.xml", "docProps/app.xml"):
        if meta in parts and meta.endswith("core.xml"):
            parts[meta] = re.sub(rb"<dc:creator>.*?</dc:creator>|<cp:lastModifiedBy>.*?</cp:lastModifiedBy>",
                                 b"", parts[meta])
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for info in z.infolist():
            if info.filename in parts:
                out.writestr(info, parts[info.filename])
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_bytes(buf.getvalue())
    print("wrote", dst)


def main(director_src: str, consultant_src: str) -> None:
    out = ROOT / "api" / "templates"
    build(director_src, out / "mbr_director.xlsx", {
        # Figures go; labels and the 2025 averages column stay
        "Contract Performance": lambda x: clear_numbers(x, keep_cols=("A", "B")),
        "Perm Performance":     lambda x: clear_numbers(x),
        "WNF Tracker":          lambda x: drop_rows(x, 4),          # filled per consultant
        "People":               lambda x: drop_rows(x, 2),
        "Deal Tracker":         lambda x: drop_rows(x, 2),
        "Deal Tracker Perm":    lambda x: drop_rows(x, 2),
        "Customer Review":      lambda x: drop_rows(x, 2),
    })
    build(consultant_src, out / "mbr_consultant.xlsx", {
        "Performance":   lambda x: clear_numbers(x, FIGURE_COLS | {"B"}),
        "WNF Tracker":   lambda x: clear_numbers(x, from_row=4),
        # Jonny's own scoring sheet: his targets (P, V) stay, results go
        "% Performance - Jonny use only": lambda x: clear_numbers(x, from_row=4, keep_cols=("P", "V")),
    })


if __name__ == "__main__":
    main(*sys.argv[1:3])
