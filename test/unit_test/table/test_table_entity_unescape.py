"""표 셀의 HTML 엔티티 해제 회귀 — 마크업 이스케이프가 본문 글자로 새지 않을 것.

MinerU는 표를 HTML(`<table><tr><td>…`)로 내므로 셀 안의 부등호가 HTML 규약대로
`&gt;`/`&lt;`로 이스케이프돼 들어온다. 해제하지 않으면 우리는 그 5글자를 그대로
점역한다(생물 p093 실측: `A>C` → ⠠⠁⠯⠛⠞⠰⠆⠠⠉).

기대값의 근거는 **규정 원문**이다(코퍼스 아님):
  · 한국 점자 규정 제5장 제12절 제45항 "연산 기호와 비교 기호는 다음과 같이 적는다"
    표 — '보다 크다'(>) = `55`, '보다 작다'(<) = `99`
  · 수학 점자 제4항 2·4 — `a55b`(a>b), `x99#j`(x<10)
BRF `55`/`99`를 유니코드로 옮기면 ⠢⠢ / ⠔⠔ 다(ascii_to_unicode로 직접 환산해 확인).
"""
from app.ai.braille.translator import translate_tagged_text
from app.ai.llm.table_opt import _cell_text, _html_to_grid
from app.utils.braille_ascii import ascii_to_unicode

# 규정 BRF에서 직접 환산 — 상수를 손으로 적지 않는다(순환검증 방지).
GT = ascii_to_unicode("55")   # 제45항 '보다 크다'
LT = ascii_to_unicode("99")   # 제45항 '보다 작다'


class TestCellText:
    def test_엔티티_해제(self):
        assert _cell_text("A&gt;C") == "A>C"
        assert _cell_text("A&lt;C") == "A<C"

    def test_태그_제거_후_해제(self):
        """`&lt;`를 먼저 풀면 태그 제거가 삼킨다 — 순서가 뒤바뀌지 않았는지."""
        assert _cell_text("<b>A&lt;C</b>") == "A<C"

    def test_이중해제_안함(self):
        """`&amp;gt;`는 원문이 문자열 '&gt;'라는 뜻 — 한 번만 푼다."""
        assert _cell_text("A&amp;gt;C") == "A&gt;C"

    def test_격자_전체_적용(self):
        grid = _html_to_grid(
            "<table><tr><td>A&gt;C</td><td>B&lt;D</td></tr></table>")
        assert grid == [["A>C", "B<D"]]


class TestBrailleMatchesRegulation:
    def test_부등호_점형이_규정과_같다(self):
        assert translate_tagged_text(_cell_text("A&gt;C")).count(GT) == 1
        assert translate_tagged_text(_cell_text("A&lt;C")).count(LT) == 1

    def test_엔티티_글자가_점역되지_않는다(self):
        """해제 전에는 `&`·`g`·`t`·`;`가 각각 셀로 찍혔다 — 그 흔적이 없어야 한다."""
        out = translate_tagged_text(_cell_text("A&gt;C"))
        assert out == translate_tagged_text("A>C")
        assert len(out) == len(translate_tagged_text("A>C"))
        # `;`(⠰⠆)·`g`(⠛)·`t`(⠞) 등 엔티티 잔재 셀이 남지 않는다
        for stray in (ascii_to_unicode("g"), ascii_to_unicode("t"),
                      ascii_to_unicode("&")):
            assert stray not in out
