from io import BytesIO

import Dashboard.dashboard_pdf_service as pdf_service


def test_build_dashboard_pdf_returns_buffer_when_reportlab_available():
    if not pdf_service.REPORTLAB_AVAILABLE:
        return

    payload = {
        "filter": {"label": "All Time"},
        "summary": {
            "uniqueErrorTypes": 1,
            "totalErrorEvents": 2,
            "statusCodeCount": 1,
            "apiCount": 1,
        },
        "rows": [
            {
                "Status Code": "504",
                "Error Code": "9002",
                "Description": "Upstream recommendation timeout",
                "API": "GET /api/recommendations",
                "Last Seen": "2026-03-31T10:00:00",
                "Count": 2,
            }
        ],
    }

    buf = pdf_service.build_dashboard_pdf(payload)
    assert isinstance(buf, BytesIO)
    content = buf.getvalue()
    assert len(content) > 100
    assert content.startswith(b"%PDF")
