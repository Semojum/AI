"""#1274 표 · 수식 요소도 환각 표시(R4)를 받는다.

글 요소 환각 절(#1078)은 표 · 수식을 안 봐서, 2027 dev · val 에서 층에 없는 한자가 남은 표 22 · 수식 82 요소가
표시 없이 나갔다(언매 자음표 `ㅅ → 人`, 수학 `므로 → 旦豆`). 한자는 점역에서 빠지므로 점역사가 자리를 못 찾는다.
층은 `_page_layer_norm` 이 내는 꼴(NFKC · 빈칸 없음 · 소문자)로 준다.
"""
from app.ai.parser import mineru_runner as MR


def test_표_칸에_층에_없는_한자는_신호다():
    layer = MR._halluc_norm("마찰음 평음 ㅅ ㅆ 경음")
    assert MR._halluc_struct_signs("<table><tr><td>마찰음</td><td>人</td><td>从</td></tr></table>", "table", layer) == ["人", "从"]


def test_표의_HTML_태그는_로마자_낱말로_안_센다():
    layer = MR._halluc_norm("마찰음 평음")
    assert MR._halluc_struct_signs('<table><tr><td colspan="2">마찰음</td></tr></table>', "table", layer) == []


def test_표에_지어낸_영어_머리줄은_신호다():
    """수학Ⅰ high 풀이 p0021 `Point: X-axis Position Y-axis Value`(지면은 x · y 값 표)."""
    layer = MR._halluc_norm("x 1 2 3 y 4 5 6")
    signs = MR._halluc_struct_signs("<table><tr><td>Point</td><td>Position</td></tr></table>", "table", layer)
    assert signs == ["Point", "Position"]


def test_수식은_한자만_본다():
    layer = MR._halluc_norm("a 이므로 b 또는 c")
    assert MR._halluc_struct_signs(r"a \text { 旦豆 } b", "formula", layer) == ["旦", "豆"]
    assert MR._halluc_struct_signs(r"\operatorname{area}(S) = 2", "formula", layer) == []     # LaTeX 안 로마자는 안 센다
    assert MR._halluc_struct_signs("x^{2}+1", "formula", layer) == []


def test_이체자는_층의_정자와_같다():
    layer = MR._halluc_norm("황하(黃河)")
    assert MR._halluc_struct_signs(r"\text{黄河}", "formula", layer) == []
