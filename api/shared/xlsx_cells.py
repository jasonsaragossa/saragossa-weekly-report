"""
Write numbers into an existing .xlsx without disturbing anything else in it.

Jonny's MBR workbooks carry charts, colours and formulas that openpyxl would
quietly drop or rewrite on save. So the export edits the worksheet XML itself:
only the <c> elements for the cells being written change, and the rest of the
package is copied across byte for byte. Formulas keep their text but lose their
cached result, and the workbook is told to recalculate on open, so every total
and ratio is Excel's own, worked from the new figures.
"""
import io
import re
import zipfile

_ROW = re.compile(r'<row\b[^>]*\br="(\d+)"[^>]*?(?:/>|>(.*?)</row>)', re.S)
_CELL = re.compile(r'<c\b[^>]*\br="([A-Z]+)(\d+)"[^>]*?(?:/>|>.*?</c>)', re.S)


def col_index(letters: str) -> int:
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n


def _attrs(cell_xml: str) -> str:
    """The cell's style attribute, kept so the number looks as the sheet intends."""
    m = re.search(r'\bs="(\d+)"', cell_xml.split(">", 1)[0])
    return f' s="{m.group(1)}"' if m else ""


def _number(v) -> str:
    if isinstance(v, bool):
        v = int(v)
    if isinstance(v, float):
        return repr(round(v, 6))
    return str(v)


def _new_cell(ref: str, value, old: str = "") -> str:
    style = _attrs(old) if old else ""
    if value is None:
        return f'<c r="{ref}"{style}/>'
    if isinstance(value, str):                       # text, inline so no shared table is touched
        from xml.sax.saxutils import escape
        return f'<c r="{ref}"{style} t="inlineStr"><is><t>{escape(value)}</t></is></c>'
    return f'<c r="{ref}"{style}><v>{_number(value)}</v></c>'


def set_cells(sheet_xml: str, values: dict) -> str:
    """values: {"C5": 89.0, "D5": None, ...} — a number writes it, None empties it.
    A formula cell is never overwritten."""
    by_row = {}
    for ref, v in values.items():
        m = re.fullmatch(r"([A-Z]+)(\d+)", ref)
        by_row.setdefault(int(m.group(2)), {})[m.group(1)] = v

    def fix_row(m):
        r = int(m.group(1))
        if r not in by_row:
            return m.group(0)
        whole, inner = m.group(0), m.group(2) or ""
        if m.group(2) is None:                            # <row .../> — no cells yet
            open_tag = whole[:-2].rstrip() + ">"
        else:
            open_tag = whole[:whole.index(">") + 1]
        cells = {c.group(1): c.group(0) for c in _CELL.finditer(inner)}
        for col, v in by_row[r].items():
            old = cells.get(col, "")
            if "<f>" in old or "<f " in old:
                continue                                  # a formula stays a formula
            cells[col] = _new_cell(f"{col}{r}", v, old)
        body = "".join(cells[c] for c in sorted(cells, key=col_index))
        return f"{open_tag}{body}</row>"

    out = _ROW.sub(fix_row, sheet_xml)
    missing = set(by_row) - {int(m.group(1)) for m in _ROW.finditer(sheet_xml)}
    if missing:
        rows = "".join(f'<row r="{r}">' + "".join(
            _new_cell(f"{c}{r}", v) for c, v in sorted(by_row[r].items(), key=lambda kv: col_index(kv[0]))
            if v is not None) + "</row>" for r in sorted(missing))
        # Rows must stay in order: put each new row before the first later one
        for r in sorted(missing):
            row_xml = re.search(rf'<row r="{r}">.*?</row>', rows, re.S).group(0)
            later = next((m for m in _ROW.finditer(out) if int(m.group(1)) > r), None)
            if later:
                out = out[:later.start()] + row_xml + out[later.start():]
            else:
                out = out.replace("</sheetData>", row_xml + "</sheetData>")
    return out


def drop_cached_formula_results(sheet_xml: str) -> str:
    """Formulas keep their text; their old answers go, so nothing stale shows."""
    return re.sub(r"(<c\b[^>]*>\s*<f\b[^>]*(?:/>|>.*?</f>))\s*<v>.*?</v>", r"\1", sheet_xml, flags=re.S)


def recalc_on_open(workbook_xml: str) -> str:
    if "<calcPr" in workbook_xml:
        if "fullCalcOnLoad" in workbook_xml:
            return workbook_xml
        return re.sub(r"<calcPr\b", '<calcPr fullCalcOnLoad="1"', workbook_xml, count=1)
    return workbook_xml.replace("</workbook>", '<calcPr fullCalcOnLoad="1"/></workbook>')


def rewrite(xlsx: bytes, edits: dict) -> bytes:
    """edits: {"xl/worksheets/sheet1.xml": fn(xml) -> xml, ...}. Every other part
    of the package is copied unchanged."""
    src = zipfile.ZipFile(io.BytesIO(xlsx))
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as out:
        for item in src.infolist():
            data = src.read(item.filename)
            if item.filename in edits:
                data = edits[item.filename](data.decode("utf-8")).encode("utf-8")
            out.writestr(item, data)
    return buf.getvalue()
