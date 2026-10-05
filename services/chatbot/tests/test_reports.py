from chatbot.reports.store import render_report_html


def test_render_report_html_includes_title_and_body() -> None:
    html = render_report_html(
        title="Q1 Brief",
        body_html="<h2>Insights</h2><p>Revenue up.</p>",
        user_label="Admin",
    )
    assert "Q1 Brief" in html
    assert "<h2>Insights</h2>" in html
    assert "Revenue up." in html
    assert "Prepared for Admin" in html
