# PDF report generation service for the Log Aggregator dashboard.
#
# Builds a landscape letter-size PDF from a dashboard payload dict using
# the reportlab library.  The output contains:
#   - A title block with filter label and generation date.
#   - A summary metrics table (unique error types, total events, status codes, APIs).
#   - A detailed error table sorted by occurrence count descending, with page-repeating
#     header rows.
#
# This module is only functional when reportlab is installed.  The calling blueprint
# checks REPORTLAB_AVAILABLE before invoking build_dashboard_pdf.
#
# Public API:
#   REPORTLAB_AVAILABLE  — bool flag; False when reportlab is not installed.
#   build_dashboard_pdf(payload) → BytesIO

from datetime import date
from io import BytesIO

try:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib.units import inch
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle
    REPORTLAB_AVAILABLE = True
except Exception:
    REPORTLAB_AVAILABLE = False

# Import shared field-name constants so column lookups are consistent
# with the rest of the dashboard.
from .dashboard_data_service import (  # type: ignore[reportMissingImports]
    STATUS_CODE_KEY, ERROR_CODE_KEY, DESCRIPTION_KEY,
    API_KEY, COUNT_KEY, LAST_SEEN_KEY,
)


def build_dashboard_pdf(payload: dict) -> BytesIO:
    """Render the dashboard payload as a PDF and return an in-memory byte buffer.

    The buffer's seek position is reset to 0 before being returned so it is
    immediately ready for Flask's send_file helper.
    """
    buffer = BytesIO()
    document = SimpleDocTemplate(
        buffer,
        pagesize=landscape(letter),
        leftMargin=0.45 * inch,
        rightMargin=0.45 * inch,
        topMargin=0.45 * inch,
        bottomMargin=0.45 * inch,
    )
    styles = getSampleStyleSheet()

    # ── Header block ──────────────────────────────────────────────────────────
    elements = [
        Paragraph('Log Aggregation Intelligence Dashboard', styles['Title']),
        Spacer(1, 0.12 * inch),
        Paragraph(f"Filter: {payload['filter']['label']}", styles['Normal']),
        Paragraph(f"Generated: {date.today().isoformat()}",  styles['Normal']),
        Spacer(1, 0.18 * inch),
    ]

    # ── Summary metrics table ─────────────────────────────────────────────────
    summary = payload['summary']
    summary_table = Table(
        [
            ['Unique Error Types', 'Total Error Events', 'Status Codes', 'APIs Impacted'],
            [
                str(summary['uniqueErrorTypes']),
                str(summary['totalErrorEvents']),
                str(summary['statusCodeCount']),
                str(summary['apiCount']),
            ],
        ],
        colWidths=[2.2 * inch, 2.2 * inch, 2.0 * inch, 2.0 * inch],
    )
    summary_table.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0), (-1, 0), colors.HexColor('#121212')),
        ('TEXTCOLOR',     (0, 0), (-1, 0), colors.white),
        ('FONTNAME',      (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTNAME',      (0, 1), (-1, 1), 'Helvetica-Bold'),
        ('BACKGROUND',    (0, 1), (-1, 1), colors.HexColor('#f8f5f2')),
        ('GRID',          (0, 0), (-1, -1), 0.5, colors.HexColor('#e6ddd6')),
        ('ALIGN',         (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN',        (0, 0), (-1, -1), 'MIDDLE'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 8),
        ('TOPPADDING',    (0, 0), (-1, -1), 8),
    ]))
    elements.extend([
        summary_table,
        Spacer(1, 0.2 * inch),
        Paragraph('Error Details', styles['Heading2']),
    ])

    # ── Error detail table ────────────────────────────────────────────────────
    detail_rows = [['Status', 'Error Code', 'Description', 'API', 'Last Seen', 'Count']]
    normal_style = styles['BodyText']

    # Sort by count descending so the highest-frequency errors appear first.
    for row in sorted(payload['rows'], key=lambda item: item.get('Count', 0), reverse=True):
        detail_rows.append([
            str(row.get(STATUS_CODE_KEY, '')),
            str(row.get(ERROR_CODE_KEY,  '')),
            Paragraph(str(row.get(DESCRIPTION_KEY, '')), normal_style),
            Paragraph(str(row.get(API_KEY,          '')), normal_style),
            str(row.get(LAST_SEEN_KEY, '')),
            str(row.get(COUNT_KEY, 0)),
        ])

    details_table = Table(
        detail_rows,
        colWidths=[0.7 * inch, 1.2 * inch, 3.55 * inch, 2.3 * inch, 1.45 * inch, 0.65 * inch],
        repeatRows=1,  # Repeat header row on every page.
    )
    details_table.setStyle(TableStyle([
        ('BACKGROUND',    (0, 0),  (-1, 0),  colors.HexColor('#ff7a1a')),
        ('TEXTCOLOR',     (0, 0),  (-1, 0),  colors.white),
        ('FONTNAME',      (0, 0),  (-1, 0),  'Helvetica-Bold'),
        ('GRID',          (0, 0),  (-1, -1), 0.35, colors.HexColor('#e6ddd6')),
        ('ROWBACKGROUNDS',(0, 1),  (-1, -1), [colors.white, colors.HexColor('#f8f5f2')]),
        ('VALIGN',        (0, 0),  (-1, -1), 'TOP'),
        ('ALIGN',         (0, 0),  (1, -1),  'CENTER'),
        ('ALIGN',         (-1, 1), (-1, -1), 'RIGHT'),
        ('LEFTPADDING',   (0, 0),  (-1, -1), 6),
        ('RIGHTPADDING',  (0, 0),  (-1, -1), 6),
        ('TOPPADDING',    (0, 0),  (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0),  (-1, -1), 6),
    ]))
    elements.append(details_table)

    document.build(elements)
    buffer.seek(0)
    return buffer
