"""
Finish the look of a pandoc-generated .docx in place (called by build_docs.sh).

Pandoc applies the paragraph styles from reference.docx, but not table borders
or header shading, so this adds them:
  - tables: full width, light grey grid, shaded bold header row repeated on
    each page, 9.5 pt text
  - block quotes (style "BlockText", used for warnings and notes): a shaded
    callout with a blue left bar

Standard library only, so it runs anywhere pandoc does.
Usage: python3 docs/style_docx.py FILE.docx [FILE.docx ...]
"""
import re
import shutil
import sys
import tempfile
import zipfile

GRID = "BFBFBF"
HEADER_FILL = "DCE6F1"
CALLOUT_FILL = "F2F6FA"
CALLOUT_BAR = "1F4E79"
TABLE_TEXT_SIZE = "19"  # half-points: 9.5 pt

BORDERS = "<w:tblBorders>" + "".join(
    f'<w:{side} w:val="single" w:sz="4" w:space="0" w:color="{GRID}"/>'
    for side in ("top", "left", "bottom", "right", "insideH", "insideV")
) + "</w:tblBorders>"


def _size_runs(xml, bold=False):
    """Set the font size (and optionally bold) on every run in `xml`."""
    extra = "<w:b/>" if bold else ""
    sz = f'<w:sz w:val="{TABLE_TEXT_SIZE}"/>'

    def fix(m):
        rpr = m.group(1) or ""
        rpr = re.sub(r"<w:sz [^>]*/>", "", rpr)
        if bold and not re.search(r"<w:b\s*/>", rpr):
            rpr = rpr.replace("<w:rPr>", "<w:rPr>" + extra, 1) if rpr else ""
        if rpr:
            rpr = rpr.replace("</w:rPr>", sz + "</w:rPr>")
        else:
            rpr = f"<w:rPr>{extra}{sz}</w:rPr>"
        return "<w:r>" + rpr

    return re.sub(r"<w:r>(<w:rPr>.*?</w:rPr>)?", fix, xml, flags=re.S)


def _style_table(tbl):
    # Full width and grid borders on the table itself.
    tbl = re.sub(r"<w:tblW [^>]*/>", '<w:tblW w:type="pct" w:w="5000"/>', tbl, count=1)
    tbl = tbl.replace("</w:tblPr>", BORDERS + "</w:tblPr>", 1)

    rows = re.findall(r"<w:tr>.*?</w:tr>|<w:tr .*?</w:tr>", tbl, flags=re.S)
    if not rows:
        return tbl
    first = rows[0]
    header = first
    if "<w:tblHeader" not in header:  # pandoc usually marks it already
        header = re.sub(r"<w:tr( [^>]*)?>", lambda m: m.group(0) + '<w:trPr><w:tblHeader w:val="true"/></w:trPr>',
                        header, count=1)
    shade = f'<w:shd w:val="clear" w:color="auto" w:fill="{HEADER_FILL}"/>'
    header = re.sub(r"<w:tcPr>", "<w:tcPr>" + shade, header)
    header = re.sub(r"<w:tcPr\s*/>", f"<w:tcPr>{shade}</w:tcPr>", header)
    header = _size_runs(header, bold=True)
    tbl = tbl.replace(first, header, 1)
    for row in rows[1:]:
        tbl = tbl.replace(row, _size_runs(row), 1)
    return tbl


def _style_callouts(xml):
    ppr = ('<w:pBdr><w:left w:val="single" w:sz="18" w:space="8" w:color="%s"/></w:pBdr>'
           '<w:shd w:val="clear" w:color="auto" w:fill="%s"/>') % (CALLOUT_BAR, CALLOUT_FILL)
    # Pandoc writes self-closing tags with a space (`<w:pStyle ... />`).
    return re.sub(r'<w:pStyle w:val="BlockText"\s*/>', lambda m: m.group(0) + ppr, xml)


def _end_after_table(xml):
    # Word needs a paragraph after a final table and adds a full-height one,
    # which can spill onto a blank last page; add a 1-pt one instead.
    tiny = ('<w:p><w:pPr><w:spacing w:before="0" w:after="0" w:line="20" w:lineRule="exact"/>'
            '<w:rPr><w:sz w:val="2"/></w:rPr></w:pPr></w:p>')
    return re.sub(r'</w:tbl>((?:<w:bookmarkEnd[^>]*/>)*)(<w:sectPr)', r'</w:tbl>\1' + tiny + r'\2', xml)


def style(path):
    with zipfile.ZipFile(path) as z:
        items = [(info, z.read(info.filename)) for info in z.infolist()]
    out = []
    for info, data in items:
        if info.filename == "word/document.xml":
            xml = data.decode("utf-8")
            xml = re.sub(r"<w:tbl>.*?</w:tbl>", lambda m: _style_table(m.group(0)), xml, flags=re.S)
            xml = _style_callouts(xml)
            xml = _end_after_table(xml)
            data = xml.encode("utf-8")
        out.append((info, data))
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".docx")
    tmp.close()
    with zipfile.ZipFile(tmp.name, "w", zipfile.ZIP_DEFLATED) as z:
        for info, data in out:
            z.writestr(info, data)
    shutil.move(tmp.name, path)


if __name__ == "__main__":
    for p in sys.argv[1:]:
        style(p)
