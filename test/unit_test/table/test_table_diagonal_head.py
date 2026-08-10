"""표 1행 1열 대각선 회귀.

인쇄본은 머리칸을 대각선으로 갈라 두 축 이름을 넣는다(`문항\\학생`). MinerU가 그 선을
`\\`로 넘기면 우리는 역빗금 ⠸⠡을 찍었다 — 규정 어디에도 근거가 없는 점형이다.

규정과 도서 관행이 갈린다.
  · 규정: 자료지침 §3.1.3(4) "표의 1행 1열의 대각선은 빗금 _/으로 적는다."(= ⠸⠌)
  · 도서: 대체로 두 라벨을 다른 자리에 나눠 적는다(사회문화 p100 gold는 `연도`를 묶음
    머리로, `인구 구조`를 제목으로).
★ 2026-07-27 독립 검증 정정 — **gold는 만장일치가 아니다.** 생물 p058 gold 6행이
  ⠰⠞⠠⠍⠸⠌⠻⠚⠺로 규정형 빗금을 실제로 쓴다(대각선 20건 중 1건). 구 docstring의
  "⠸⠌·⠸⠡ 둘 다 0회"는 거짓이었다. 규정형 발행 A/B도 "양쪽 악화"가 재현되지 않았다
  (독립 재현: dev −5 개선 · val +305). **즉 대각선 표기는 열린 질문이고, 지금 선만
  없애는 것은 잠정 조치다.** 이 테스트는 현재 동작을 고정할 뿐 규정 판단을 확정하지 않는다.

적용 범위는 규정이 지목하는 1행 1열(+ 병합 복제분)뿐이다.
"""
from app.ai.braille.translator import translate_tagged_text
from app.ai.llm.table_opt import _table_tags
from app.utils.braille_ascii import ascii_to_unicode

BACKSLASH = ascii_to_unicode("_\\")   # 규정_텍스트 기호표의 역빗금


def cell00(text: str) -> str:
    """표 텍스트 → <!표> 태그에 실린 1행 1열 셀."""
    tags = _table_tags(None, text)
    return tags.split("<!행>")[1].split("<!칸>")[1].split("<!칸>")[0]


class TestDiagonalRemoved:
    def test_파이프_격자(self):
        assert cell00("문항\\학생 | 갑 | 을\n1. 가 | ○ | ×") == "문항 학생"

    def test_HTML_격자(self):
        html = "<table><tr><td>구분\\연도</td><td>1970</td></tr></table>"
        assert cell00(html) == "구분 연도"

    def test_주변_공백은_한_칸으로(self):
        assert cell00("인구 구조 \\ 연도 | 1970\n총인구 | 32,240") == "인구 구조 연도"

    def test_대각선이_둘이어도(self):
        """3단 머리(사회문화 p185 `연도\\구분\\제도`)."""
        assert cell00("연도\\구분\\제도 | A | B\n2003 | 1 | 2") == "연도 구분 제도"

    def test_라벨이_그리스문자_성별기호여도(self):
        """생물 격자 머리 `♀\\δ` — 한글·로마자만 라벨인 게 아니다."""
        assert cell00("♀\\δ | RY | Ry\nRY | RRYY | RRYy") == "♀ δ"

    def test_역빗금_점형이_사라진다(self):
        out = translate_tagged_text(cell00("문항\\학생 | 갑\n1. 가 | ○"))
        assert BACKSLASH not in out


class TestMergedCorner:
    def test_rowspan_복제분도_함께(self):
        """2단 머리에서 대각선 칸은 rowspan을 갖는다 — 복제분에 역빗금이 남으면 안 된다.

        2026-08-08: 병합 셀은 이제 **한 번만** 실린다(_html_to_grid expand=False).
        구 기대값 2는 rowspan 복제를 세던 것이고, 그 복제가 표 축 과잉생산의 원인이었다.
        """
        html = ('<table><tr><td rowspan="2">연도\\구분</td><td colspan="2">A</td></tr>'
                '<tr><td>인원</td><td>비율</td></tr>'
                '<tr><td>2003</td><td>1,374</td><td>2.84</td></tr></table>')
        tags = _table_tags(None, html)
        assert "\\" not in tags
        assert tags.count("연도 구분") == 1


class TestScope:
    def test_표_안_LaTeX는_보존(self):
        """옛 배선은 셀 단위라 표 안 수식의 백슬래시를 공백으로 지웠다(dev+val 71칸)."""
        html = "<table><tr><td>X</td><td>$\\frac{1}{2600}$</td></tr></table>"
        assert "$\\frac{1}{2600}$" in _table_tags(None, html)

    def test_1행1열만(self):
        """규정이 정한 자리는 1행 1열뿐 — 다른 칸의 백슬래시는 대각선이 아니다."""
        tags = _table_tags(None, "X | y=1/2x+3 | \\(y=\\sqrt{2x+k}\\)\n-6 | 0 | 3")
        assert "\\(y=\\sqrt{2x+k}\\)" in tags

    def test_라벨_사이가_아니면_손대지_않는다(self):
        """추출이 흘리는 마크다운 이스케이프는 대각선이 아니다(앞뒤가 글자가 아님)."""
        assert cell00("32\\~33 | 갑\n가 | 나") == "32\\~33"
        assert cell00("\\- 항목 | 갑\n가 | 나") == "\\- 항목"
