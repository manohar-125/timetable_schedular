"""
timetable_scheduler.engine.export

Export timetable to various formats:
- CSV
- Printable HTML
- Real PDF
"""

from __future__ import annotations

import csv
import io
from datetime import datetime
from typing import Any

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, A4
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import (
    SimpleDocTemplate,
    Table,
    TableStyle,
    Paragraph,
    Spacer,
)
from reportlab.platypus.flowables import PageBreak

from .models import (
    DAYS,
    PERIODS,
    SLOTS_PER_DAY,
    EngineResult,
)

TIME_LABELS = [
    "09:00-10:00",
    "10:00-11:00",
    "11:00-12:00",
    "12:00-13:00",
    "LUNCH",
    "14:00-15:00",
    "15:00-16:00",
    "16:00-17:00",
    "17:00-18:00",
]


# =========================================================
# CSV EXPORT
# =========================================================

def export_to_csv(result: EngineResult) -> str:
    if not result.semester_timetables:
        return ""

    output = io.StringIO()
    writer = csv.writer(output)

    header = [
        "DAY",
        "PROGRAM",
        "P1",
        "P2",
        "P3",
        "P4",
        "P5",
        "P6",
        "P7",
        "P8",
    ]

    writer.writerow(header)

    for day_idx, day_name in enumerate(DAYS):
        for sem, grid in result.semester_timetables.items():
            row = [day_name, sem]

            for p in range(8):
                cell = grid[day_idx][p]

                if not cell:
                    row.append("")
                else:
                    row.append(_csv_cell(cell))

            writer.writerow(row)

    return output.getvalue()


def _csv_cell(cell):
    if isinstance(cell, list):
        return " | ".join(
            f"{x.name} ({x.faculty})"
            for x in cell
        )

    return f"{cell.name} ({cell.faculty})"


# =========================================================
# HTML EXPORT
# =========================================================

def export_to_html(result: EngineResult) -> str:
    semester_timetables = getattr(result, "semester_timetables", None)

    if not semester_timetables:
        return "<html><body><h2>No timetable available</h2></body></html>"

    html = []

    html.append("""
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">

<style>
body{
    font-family: Arial;
    margin:20px;
}

h1,h2,h3{
    text-align:center;
    margin:2px;
}

table{
    border-collapse:collapse;
    width:100%;
    table-layout:fixed;
    font-size:11px;
}

th,td{
    border:1px solid black;
    text-align:center;
    padding:4px;
    height:42px;
    word-wrap:break-word;
}

th{
    background:#f0f0f0;
}

.day{
    background:#f5f5f5;
    font-weight:bold;
}

.program{
    background:#fafafa;
    font-weight:bold;
}

.lunch{
    background:#ffe5e5;
    font-weight:bold;
}

.free{
    background:#fff5f5;
    color:#cc0000;
    font-size:10px;
}

.lab{
    background:#fff3cd;
}

.core{
    background:#e7f3ff;
}

@media print{
    @page{
        size:A4 landscape;
        margin:8mm;
    }

    body{
        margin:0;
    }
}
</style>
</head>

<body>

<h2>UNIVERSITY OF HYDERABAD</h2>
<h3>SCHOOL OF COMPUTER AND INFORMATION SCIENCES</h3>
<h3>SEMESTER TIMETABLE</h3>
<p style="text-align:center;">
Generated: """ + datetime.now().strftime("%d %b %Y %H:%M") + """
</p>

<table>
""")

    # header row
    html.append("<tr>")
    html.append("<th>DAY</th>")
    html.append("<th>PROGRAM</th>")

    for t in TIME_LABELS[:4]:
        html.append(f"<th>{t}</th>")

    html.append('<th class="lunch">LUNCH</th>')

    for t in TIME_LABELS[5:]:
        html.append(f"<th>{t}</th>")

    html.append("</tr>")

    # body
    for day_idx, day_name in enumerate(DAYS):

        first_row = True
        total_rows = len(semester_timetables)

        for sem, grid in semester_timetables.items():

            html.append("<tr>")

            if first_row:
                html.append(
                    f'<td rowspan="{total_rows}" class="day">{day_name}</td>'
                )
                first_row = False

            html.append(f'<td class="program">{sem}</td>')

            for p in range(4):
                html.append(_html_cell(grid[day_idx][p]))

            html.append('<td class="lunch">BREAK</td>')

            for p in range(4, 8):
                html.append(_html_cell(grid[day_idx][p]))

            html.append("</tr>")

    html.append("</table></body></html>")

    return "".join(html)


def _html_cell(cell):

    if not cell:
        return '<td class="free"></td>'

    if isinstance(cell, list):
        cell = cell[0]

    cls = "lab" if "Lab" in cell.name else "core"

    return f"""
    <td class="{cls}">
        <div><b>{cell.name}</b></div>
        <div>{cell.faculty}</div>
    </td>
    """


# =========================================================
# PDF EXPORT
# =========================================================

def export_to_pdf(result: EngineResult) -> bytes:

    buffer = io.BytesIO()

    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        rightMargin=10,
        leftMargin=10,
        topMargin=10,
        bottomMargin=10,
    )

    styles = getSampleStyleSheet()
    elements = []

    title = Paragraph(
        """
        <b>UNIVERSITY OF HYDERABAD</b><br/>
        SCHOOL OF COMPUTER AND INFORMATION SCIENCES<br/>
        SEMESTER TIMETABLE
        """,
        styles["Title"],
    )

    elements.append(title)
    elements.append(Spacer(1, 12))

    data = []

    header = [
        "DAY",
        "PROGRAM",
        "P1",
        "P2",
        "P3",
        "P4",
        "LUNCH",
        "P5",
        "P6",
        "P7",
        "P8",
    ]

    data.append(header)

    semester_timetables = result.semester_timetables

    for day_idx, day_name in enumerate(DAYS):

        first = True
        total_rows = len(semester_timetables)

        for sem, grid in semester_timetables.items():

            row = []

            if first:
                row.append(day_name)
                first = False
            else:
                row.append("")

            row.append(sem)

            for p in range(4):

                row.append(_pdf_text(grid[day_idx][p]))

            row.append("BREAK")

            for p in range(4, 8):

                row.append(_pdf_text(grid[day_idx][p]))

            data.append(row)

    table = Table(data, repeatRows=1)

    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 1, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, 0), 8),

        ("BACKGROUND", (6, 1), (6, -1), colors.HexColor("#ffe5e5")),

        ("BACKGROUND", (1, 1), (1, -1), colors.HexColor("#f5f5f5")),
    ]))

    elements.append(table)

    doc.build(elements)

    pdf = buffer.getvalue()
    buffer.close()

    return pdf


def _pdf_text(cell):

    if not cell:
        return ""

    if isinstance(cell, list):
        cell = cell[0]

    return f"{cell.name}\n{cell.faculty}"


# =========================================================
# JSON EXPORT
# =========================================================

def export_to_json(result: EngineResult) -> dict[str, Any]:

    return {
        "success": result.success,
        "errors": result.errors,
        "debug": result.debug,
    }