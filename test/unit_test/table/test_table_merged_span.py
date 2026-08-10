"""병합 셀(colspan/rowspan) 복제 회귀 — 표 축 과잉생산의 최대 원인(2026-08-08, 원장 C-01b).

우리는 colspan="8" 셀을 여덟 번 찍고 있었다. gold는 한 번만 적는다
(EBS-E26-009 p0091·EBS-E26-004 p0002 실물 대조).
열 수를 세는 자리(_infer_render_mode)는 여전히 펼친 격자를 봐야 한다 — 두 쓰임을 가른다.
"""
from app.ai.llm.table_opt import _html_to_grid, _infer_render_mode, _table_tags

HTML = ('<table>'
        '<tr><td rowspan="2">묶음</td><td colspan="3">머리</td></tr>'
        '<tr><td>가</td><td>나</td><td>다</td></tr>'
        '<tr><td>2003</td><td>1</td><td>2</td><td>3</td></tr>'
        '</table>')


def test_출력용은_병합을_한_번만_낸다():
    rows = _html_to_grid(HTML, expand=False)
    assert rows[0] == ["묶음", "머리"]          # colspan 3 → 한 칸
    assert rows[1] == ["가", "나", "다"]        # rowspan 복제분 없음
    assert _table_tags(None, HTML).count("머리") == 1


def test_열_수_판정은_펼친_격자로():
    """expand=True가 아니면 4열 표가 2열(linear)로 오판된다."""
    assert max(len(r) for r in _html_to_grid(HTML)) == 4
    assert _infer_render_mode(None, HTML) == "table_grid"


def test_진짜_반복_값은_지우지_않는다():
    """값 기준 축약이면 '+ + +'가 한 칸으로 줄어든다 — 병합 기준이라 그대로 남는다."""
    html = "<table><tr><td>실험</td><td>+</td><td>+</td><td>+</td></tr></table>"
    assert _html_to_grid(html, expand=False)[0] == ["실험", "+", "+", "+"]
