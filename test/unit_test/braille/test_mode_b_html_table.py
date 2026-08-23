"""mode b 원문의 HTML 표가 표 체인을 타는가 (노션 Review T705·T706).

종전에는 `<!표>` 형식만 표로 봤고 hwp·docx 에서 온 HTML `<table>` 은 평범한 글줄로
떨어져 **마크업이 그대로 점자화**됐다(`<table>` → ⠠⠦⠞⠁⠼⠴⠄ …).
"""
from app.core.pipeline import _mode_b_html_tables_to_tags, _mode_b_segments

HTML = "<table><tr><td>구분</td><td>1학기</td></tr><tr><td>국어</td><td>90</td></tr></table>"


def test_HTML_표가_태그형으로_바뀐다():
    out = _mode_b_html_tables_to_tags(HTML)
    assert "<!표>" in out and "<!/표>" in out
    assert "<table" not in out.lower()
    assert "구분" in out and "90" in out


def test_바뀐_표는_요소_하나로_묶인다():
    segs = _mode_b_segments(_mode_b_html_tables_to_tags(HTML))
    assert [t for _no, t, _s in segs] == ["table"]


def test_앞뒤_글은_그대로_줄_요소다():
    src = f"머리말\n{HTML}\n꼬리말"
    segs = _mode_b_segments(_mode_b_html_tables_to_tags(src))
    assert [t for _no, t, _s in segs] == ["text", "table", "text"]


def test_표가_없으면_원문_그대로():
    src = "표 아닌 글줄"
    assert _mode_b_html_tables_to_tags(src) is src


def test_망가진_HTML_은_원문을_지킨다():
    """못 읽으면 종전 동작(글줄)으로 떨어진다 — 조용히 내용을 잃지 않는다."""
    broken = "<table><tr><td>가</table>"
    out = _mode_b_html_tables_to_tags(broken)
    assert "가" in out
