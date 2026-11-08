#!/usr/bin/env python3
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.
"""Write AceOffice's starter templates (aceoffice/templates/*.fodt, *.fods).

Flat OpenDocument files, so they're plain text in git. Run this after editing:
    tools/make-templates.py
Fonts: Noto Sans and Noto Serif ship with most Linux distributions (the Flatpak
bundles them); LibreOffice substitutes something close where they're missing.
"""
import os
from xml.sax.saxutils import escape

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "aceoffice", "templates")

NS = ('xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0" '
      'xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0" '
      'xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0" '
      'xmlns:table="urn:oasis:names:tc:opendocument:xmlns:table:1.0" '
      'xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0" '
      'xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0" '
      'xmlns:number="urn:oasis:names:tc:opendocument:xmlns:datastyle:1.0" '
      'xmlns:of="urn:oasis:names:tc:opendocument:xmlns:of:1.2" '
      'xmlns:loext="urn:org:documentfoundation:names:experimental:office:xmlns:loext:1.0"')

FONTS = ('<office:font-face-decls>'
         '<style:font-face style:name="Noto Sans" svg:font-family="\'Noto Sans\'" style:font-family-generic="swiss"/>'
         '<style:font-face style:name="Noto Serif" svg:font-family="\'Noto Serif\'" style:font-family-generic="roman"/>'
         '</office:font-face-decls>')

ACCENT = "#2a6fdb"
INK = "#1d1d1f"
GREY = "#6e6e73"


def pstyle(name, display=None, parent="Standard", font=None, size=None, weight=None, color=None,
           above=None, below=None, align=None, line=None, indent=None, border_bottom=None, italic=False,
           keep_next=False, cls="text", outline=None):
    text_props = []
    if font:
        text_props.append(f'style:font-name="{font}"')
    if size:
        text_props.append(f'fo:font-size="{size}"')
    if weight:
        text_props.append(f'fo:font-weight="{weight}"')
    if italic:
        text_props.append('fo:font-style="italic"')
    if color:
        text_props.append(f'fo:color="{color}"')
    para = []
    if above is not None:
        para.append(f'fo:margin-top="{above}"')
    if below is not None:
        para.append(f'fo:margin-bottom="{below}"')
    if align:
        para.append(f'fo:text-align="{align}"')
    if line:
        para.append(f'fo:line-height="{line}"')
    if indent:
        para.append(f'fo:text-indent="{indent}"')
    if border_bottom:
        para.append(f'fo:border-bottom="{border_bottom}" fo:padding-bottom="0.04in"')
    if keep_next:
        para.append('fo:keep-with-next="always"')
    disp = f' style:display-name="{display}"' if display else ""
    par = f' style:parent-style-name="{parent}"' if parent else ""
    lvl = f' style:default-outline-level="{outline}"' if outline else ""
    return (f'<style:style style:name="{name}"{disp} style:family="paragraph"{par} style:class="{cls}"{lvl}>'
            f'<style:paragraph-properties {" ".join(para)}/>'
            f'<style:text-properties {" ".join(text_props)}/></style:style>')


def text_doc(name, extra_styles, body, body_font="Noto Sans", body_size="11pt", line="135%",
             margins="1in", first_indent=None):
    styles = "".join([
        '<style:default-style style:family="paragraph"><style:paragraph-properties fo:hyphenation-ladder-count="no-limit"/>'
        f'<style:text-properties style:font-name="{body_font}" fo:font-size="{body_size}" fo:language="en" fo:country="US" '
        f'fo:color="{INK}"/></style:default-style>',
        pstyle("Standard", parent=None, line=line, below="0.08in", indent=first_indent),
        pstyle("Title", font="Noto Sans", size="28pt", weight="bold", below="0.06in", line="110%",
               cls="chapter", keep_next=True),
        pstyle("Subtitle", font="Noto Sans", size="14pt", color=GREY, below="0.3in", cls="chapter", keep_next=True),
        pstyle("Heading_20_1", "Heading 1", font="Noto Sans", size="16pt", weight="bold", above="0.25in",
               below="0.08in", keep_next=True, outline=1),
        pstyle("Heading_20_2", "Heading 2", font="Noto Sans", size="12.5pt", weight="bold", above="0.18in",
               below="0.05in", keep_next=True, outline=2),
        pstyle("Heading_20_3", "Heading 3", font="Noto Sans", size="11pt", weight="bold", color=GREY,
               above="0.14in", below="0.04in", keep_next=True, outline=3),
        pstyle("Quotations", font="Noto Serif", italic=True, color=GREY, above="0.08in", below="0.12in"),
        extra_styles,
    ])
    page = (f'<office:automatic-styles><style:page-layout style:name="pm1"><style:page-layout-properties '
            f'fo:page-width="8.5in" fo:page-height="11in" fo:margin-top="{margins}" fo:margin-bottom="{margins}" '
            f'fo:margin-left="{margins}" fo:margin-right="{margins}"/></style:page-layout></office:automatic-styles>'
            '<office:master-styles><style:master-page style:name="Standard" style:page-layout-name="pm1"/>'
            '</office:master-styles>')
    doc = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document {NS} office:version="1.3" '
           f'office:mimetype="application/vnd.oasis.opendocument.text">{FONTS}<office:styles>{styles}</office:styles>'
           f'{page}<office:body><office:text>{body}</office:text></office:body></office:document>\n')
    with open(os.path.join(OUT, name + ".fodt"), "w", encoding="utf-8") as f:
        f.write(doc)


def p(text, style="Standard"):
    return f'<text:p text:style-name="{style}">{escape(text)}</text:p>'


def h(text, level=1):
    return f'<text:h text:style-name="Heading_20_{level}" text:outline-level="{level}">{escape(text)}</text:h>'


LOREM = ("Start typing to replace this text. Use the Format sidebar to change fonts and spacing, "
         "and the Insert, Table and Chart buttons to add more.")


def documents():
    text_doc("blank", "", p(""))

    text_doc("report",
             pstyle("Kicker", font="Noto Sans", size="10pt", weight="bold", color=ACCENT, below="0.1in")
             + pstyle("Byline", size="10pt", color=GREY, below="0.4in", border_bottom=f"0.5pt solid {GREY}"),
             p("QUARTERLY REPORT", "Kicker") + p("Project Overview", "Title")
             + p("A short summary of where things stand and what comes next", "Subtitle")
             + p("Prepared by Your Name  ·  November 2026", "Byline")
             + h("Summary") + p(LOREM)
             + p("Keep the summary to a paragraph or two: what happened, what it means, and what you need "
                 "from the reader.")
             + h("Highlights") + h("What went well", 2) + p(LOREM) + h("What we learned", 2) + p(LOREM)
             + h("Next steps") + p(LOREM)
             + p("“A quotation or a key figure can sit here, set apart from the body text.”", "Quotations"))

    text_doc("letter",
             pstyle("Sender", size="10pt", color=GREY, align="end", below="0in", line="130%")
             + pstyle("SenderName", font="Noto Sans", size="18pt", weight="bold", align="end", below="0.04in")
             + pstyle("Date", above="0.5in", below="0.3in")
             + pstyle("Address", below="0in", line="130%")
             + pstyle("Signature", above="0.5in", below="0in"),
             p("Your Name", "SenderName") + p("123 Main Street", "Sender") + p("Toronto, ON  M5V 2T6", "Sender")
             + p("you@example.com  ·  (416) 555-0123", "Sender")
             + p("November 7, 2026", "Date")
             + p("Recipient Name", "Address") + p("Company", "Address") + p("456 Market Street", "Address")
             + p("City, Province  A1B 2C3", "Address") + p("")
             + p("Dear Recipient,")
             + p("Start your letter here. Say why you're writing in the first sentence, then give the "
                 "details the reader needs.")
             + p("Close with what you'd like to happen next, and how to reach you.")
             + p("Sincerely,", "Signature") + p("") + p("Your Name"))

    text_doc("resume",
             pstyle("Name", font="Noto Sans", size="26pt", weight="bold", below="0.02in", line="110%")
             + pstyle("Contact", size="9.5pt", color=GREY, below="0.25in")
             + pstyle("Section", font="Noto Sans", size="10pt", weight="bold", color=ACCENT, above="0.22in",
                      below="0.08in", border_bottom=f"0.5pt solid {ACCENT}", keep_next=True)
             + pstyle("Role", font="Noto Sans", size="11pt", weight="bold", above="0.08in", below="0in",
                      keep_next=True)
             + pstyle("When", size="9.5pt", color=GREY, below="0.04in", keep_next=True),
             p("Your Name", "Name") + p("Toronto, ON  ·  you@example.com  ·  (416) 555-0123  ·  linkedin.com/in/you",
                                        "Contact")
             + p("A sentence or two about who you are and the kind of work you're looking for.")
             + p("EXPERIENCE", "Section")
             + p("Job Title, Company", "Role") + p("2023 – Present", "When")
             + p("What you were responsible for, and one result you're proud of, with a number if you have one.")
             + p("Job Title, Company", "Role") + p("2019 – 2023", "When")
             + p("What you were responsible for, and one result you're proud of.")
             + p("EDUCATION", "Section")
             + p("Degree, School", "Role") + p("2015 – 2019", "When")
             + p("SKILLS", "Section")
             + p("Skill one  ·  Skill two  ·  Skill three  ·  Skill four"),
             margins="0.75in")

    text_doc("essay",
             pstyle("EssayTitle", font="Noto Serif", size="16pt", weight="bold", align="center", below="0.06in",
                    indent="0in")
             + pstyle("EssayMeta", font="Noto Serif", size="11pt", color=GREY, align="center", below="0.35in",
                      indent="0in"),
             p("The Title of Your Essay", "EssayTitle") + p("Your Name  ·  Course  ·  November 7, 2026", "EssayMeta")
             + p("Begin with a sentence that makes the reader want to keep going. Then set out the question "
                 "your essay answers, and the answer you'll argue for.")
             + p("Each paragraph after this one should make one point, support it, and connect it back to "
                 "your argument. Lines are double spaced and each paragraph starts with an indent, as most "
                 "teachers expect.")
             + p("Finish by drawing the threads together, and say why the answer matters."),
             body_font="Noto Serif", body_size="12pt", line="200%", first_indent="0.5in")


# --- spreadsheets ----------------------------------------------------------------

def sheet_doc(name, columns, rows, extra_cell_styles="", col_widths=None, title=None):
    """rows: lists of cells; a cell is a str/number, or (value, style) or ('=formula', style)."""
    cell_styles = "".join([
        '<number:currency-style style:name="N1P0" style:volatile="true"><number:currency-symbol>$</number:currency-symbol>'
        '<number:number number:decimal-places="2" number:min-decimal-places="2" number:min-integer-digits="1" '
        'number:grouping="true"/></number:currency-style>'
        '<number:currency-style style:name="N1"><style:text-properties fo:color="#c01c28"/><number:text>-</number:text>'
        '<number:currency-symbol>$</number:currency-symbol><number:number number:decimal-places="2" '
        'number:min-decimal-places="2" number:min-integer-digits="1" number:grouping="true"/>'
        '<style:map style:condition="value()&gt;=0" style:apply-style-name="N1P0"/></number:currency-style>',
        '<number:date-style style:name="N2"><number:month number:textual="true"/><number:text> </number:text>'
        '<number:day/><number:text>, </number:text><number:year number:style="long"/></number:date-style>',
    ])
    styles = ('<style:default-style style:family="table-cell"><style:table-cell-properties fo:padding="0.03in"/>'
              f'<style:text-properties style:font-name="Noto Sans" fo:font-size="10.5pt" fo:color="{INK}" '
              'fo:language="en" fo:country="US"/></style:default-style>'
              '<style:style style:name="Default" style:family="table-cell"/>')
    auto = "".join([
        '<style:style style:name="co" style:family="table-column"><style:table-column-properties style:column-width="1.2in"/></style:style>',
        *(f'<style:style style:name="co{i}" style:family="table-column"><style:table-column-properties '
          f'style:column-width="{w}"/></style:style>' for i, w in enumerate(col_widths or [])),
        '<style:style style:name="ro" style:family="table-row"><style:table-row-properties style:row-height="0.26in" '
        'style:use-optimal-row-height="false"/></style:style>',
        '<style:style style:name="rot" style:family="table-row"><style:table-row-properties style:row-height="0.5in" '
        'style:use-optimal-row-height="false"/></style:style>',
        '<style:style style:name="ta1" style:family="table" style:master-page-name="Default"><style:table-properties '
        'table:display="true"/></style:style>',
        cell("title", size="20pt", weight="bold"),
        cell("sub", color=GREY),
        cell("head", weight="bold", color="#ffffff", bg=ACCENT, align="start"),
        cell("headr", weight="bold", color="#ffffff", bg=ACCENT, align="end"),
        cell("money", num="N1"),
        cell("moneyb", num="N1", weight="bold", top=f"1pt solid {INK}"),
        cell("bold", weight="bold", top=f"1pt solid {INK}"),
        cell("band", bg="#f2f5fa"),
        cell("bandmoney", bg="#f2f5fa", num="N1"),
        cell("date", num="N2"),
        cell("banddate", bg="#f2f5fa", num="N2"),
        cell("done", color="#2e7d32", weight="bold", align="center"),
        cell("pct", num="N3"),
        extra_cell_styles,
    ])
    auto = ('<number:percentage-style style:name="N3"><number:number number:decimal-places="0" '
            'number:min-integer-digits="1"/><number:text>%</number:text></number:percentage-style>') + auto
    cols = "".join(f'<table:table-column table:style-name="co{i}"/>' for i in range(len(col_widths or []))) \
        or f'<table:table-column table:style-name="co" table:number-columns-repeated="{columns}"/>'
    body_rows = []
    for r in rows:
        style = "rot" if r and isinstance(r[0], tuple) and r[0][1] == "title" else "ro"
        body_rows.append(f'<table:table-row table:style-name="{style}">' + "".join(cell_xml(c) for c in r)
                         + '</table:table-row>')
    doc = (f'<?xml version="1.0" encoding="UTF-8"?>\n<office:document {NS} office:version="1.3" '
           f'office:mimetype="application/vnd.oasis.opendocument.spreadsheet">{FONTS}'
           f'<office:styles>{styles}{cell_styles}</office:styles>'
           f'<office:automatic-styles>{auto}</office:automatic-styles>'
           f'<office:body><office:spreadsheet><table:table table:name="{escape(title or "Sheet1")}" '
           f'table:style-name="ta1">{cols}{"".join(body_rows)}</table:table></office:spreadsheet></office:body>'
           '</office:document>\n')
    with open(os.path.join(OUT, name + ".fods"), "w", encoding="utf-8") as f:
        f.write(doc)


def cell(name, size=None, weight=None, color=None, bg=None, align=None, num=None, top=None):
    props = []
    if bg:
        props.append(f'fo:background-color="{bg}"')
    if top:
        props.append(f'fo:border-top="{top}"')
    tp = []
    if size:
        tp.append(f'fo:font-size="{size}"')
    if weight:
        tp.append(f'fo:font-weight="{weight}"')
    if color:
        tp.append(f'fo:color="{color}"')
    pp = f'<style:paragraph-properties fo:text-align="{align}"/>' if align else ""
    dn = f' style:data-style-name="{num}"' if num else ""
    return (f'<style:style style:name="{name}" style:family="table-cell" style:parent-style-name="Default"{dn}>'
            f'<style:table-cell-properties {" ".join(props)}/>{pp}<style:text-properties {" ".join(tp)}/></style:style>')


def cell_xml(c):
    style = None
    if isinstance(c, tuple):
        c, style = c
    st = f' table:style-name="{style}"' if style else ""
    if c is None or c == "":
        return f'<table:table-cell{st}/>'
    if isinstance(c, str) and c.startswith("="):
        # No cached result: LibreOffice then calculates the formula when the file opens.
        return f'<table:table-cell{st} table:formula="of:{escape(c, {chr(34): '&quot;'})}"/>'
    if isinstance(c, (int, float)):
        if style and "money" in style:
            return (f'<table:table-cell{st} office:value-type="currency" office:currency="USD" office:value="{c}">'
                    f'<text:p>${c:,.2f}</text:p></table:table-cell>')
        return f'<table:table-cell{st} office:value-type="float" office:value="{c}"><text:p>{c}</text:p></table:table-cell>'
    if isinstance(c, str) and c[:4].isdigit() and c[4:5] == "-":     # an ISO date
        return (f'<table:table-cell{st} office:value-type="date" office:date-value="{c}">'
                f'<text:p>{c}</text:p></table:table-cell>')
    return f'<table:table-cell{st} office:value-type="string"><text:p>{escape(c)}</text:p></table:table-cell>'


def spreadsheets():
    sheet_doc("blank-sheet", 8, [[""]])

    items = [("Rent", 1800, 1800), ("Groceries", 600, 642), ("Utilities", 180, 165), ("Phone & internet", 110, 110),
             ("Transportation", 250, 231), ("Eating out", 200, 264), ("Savings", 500, 500), ("Other", 150, 98)]
    rows = [[("Monthly Budget", "title")], [("November 2026", "sub")], [],
            [("Category", "head"), ("Budget", "headr"), ("Actual", "headr"), ("Difference", "headr")]]
    for i, (name, budget, actual) in enumerate(items):
        r = 5 + i
        band = i % 2 == 1
        rows.append([(name, "band" if band else None), (budget, "bandmoney" if band else "money"),
                     (actual, "bandmoney" if band else "money"),
                     (f"=[.B{r}]-[.C{r}]", "bandmoney" if band else "money")])
    last = 4 + len(items)
    rows.append([("Total", "bold"), (f"=SUM([.B5:.B{last}])", "moneyb"), (f"=SUM([.C5:.C{last}])", "moneyb"),
                 (f"=SUM([.D5:.D{last}])", "moneyb")])
    sheet_doc("budget", 4, rows, col_widths=["2.2in", "1.3in", "1.3in", "1.3in"], title="Budget")

    tasks = [("Book movers", "2026-11-10", "✓"), ("Forward mail", "2026-11-12", ""), ("Change address with bank", "2026-11-14", ""),
             ("Cancel old internet", "2026-11-20", ""), ("Pack the kitchen", "2026-11-25", "")]
    rows = [[("Checklist", "title")], [("Tick a task by typing ✓ in the Done column", "sub")], [],
            [("Task", "head"), ("Due", "head"), ("Done", "head"), ("Notes", "head")]]
    for i, (t, due, done) in enumerate(tasks):
        band = i % 2 == 1
        rows.append([(t, "band" if band else None), (due, "banddate" if band else "date"),
                     (done, "done"), ("", "band" if band else None)])
    n = 4 + len(tasks)
    rows += [[], [("Done", "bold"), (f'=COUNTIF([.C5:.C{n}];"✓")/COUNTA([.A5:.A{n}])', "pct")]]
    sheet_doc("checklist", 4, rows, col_widths=["2.6in", "1.3in", "0.8in", "2.4in"], title="Checklist")

    lines = [("Consulting (hours)", 12, 150), ("Design review", 1, 600), ("Travel", 1, 220)]
    rows = [[("Invoice", "title"), "", ("Invoice #", "sub"), "0001"],
            [("Your Business Name", "sub"), "", ("Date", "sub"), ("2026-11-07", "date")],
            [("you@example.com", "sub"), "", ("Due", "sub"), ("2026-12-07", "date")], [],
            [("Bill to", "bold")], ["Client Name"], ["Client address"], [],
            [("Description", "head"), ("Quantity", "headr"), ("Rate", "headr"), ("Amount", "headr")]]
    start = len(rows) + 1
    for i, (d, q, rate) in enumerate(lines):
        r = start + i
        band = i % 2 == 1
        rows.append([(d, "band" if band else None), (q, "band" if band else None),
                     (rate, "bandmoney" if band else "money"), (f"=[.B{r}]*[.C{r}]", "bandmoney" if band else "money")])
    end = start + len(lines) - 1
    rows += [[], ["", "", ("Subtotal", "sub"), (f"=SUM([.D{start}:.D{end}])", "money")],
             ["", "", ("Tax (13%)", "sub"), (f"=[.D{end + 2}]*0.13", "money")],
             ["", "", ("Total", "bold"), (f"=[.D{end + 2}]+[.D{end + 3}]", "moneyb")]]
    sheet_doc("invoice", 4, rows, col_widths=["2.8in", "1in", "1.3in", "1.4in"], title="Invoice")


if __name__ == "__main__":
    os.makedirs(OUT, exist_ok=True)
    documents()
    spreadsheets()
    print("Templates written to", os.path.normpath(OUT))
