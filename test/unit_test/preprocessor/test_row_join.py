"""한 인쇄 줄이 여러 line으로 쪼개진 것 잇기(rows_to_text) — QA S4, 2026-08-07.

PyMuPDF(MuPDF stext)는 가로 간격이 크면 같은 줄도 line을 나눈다. 정답표
"01 ⑤  02 ②  03 ①  04 ⑤"가 4개 line으로 나오고, "\n"으로 이으면 항목마다
줄바꿈된 점자가 나갔다.

정답 실측(EBS-E26-013 ans p0001 BRF): `  #ja #5  #jb #2  #jc #1  #jd #5`
= "  01 ⑤  02 ②  03 ①  04 ⑤" — 한 줄, 항목 사이 두 칸.
규정 근거: 「점자 도서 제작 지침」 3장 3절 4)(3)①(선택지 사이 두 칸)·6)(1)(표 셀 두 칸).
"""
from app.ai.braille.translator import translate_tagged_text
from app.ai.preprocessor.pdf_analyzer import rows_to_text


class _R:
    """rows_to_text가 쓰는 rect 최소 인터페이스(x0/y0/y1)."""

    def __init__(self, x0: float, y0: float, y1: float):
        self.x0, self.y0, self.y1 = x0, y0, y1


class TestRowsToText:
    def test_같은_줄_조각은_두_칸으로_이어진다(self):
        items = [(_R(10, 100, 120), "01 ⑤\t"), (_R(60, 100, 120), "02 ②\t"),
                 (_R(110, 100, 120), "03 ①")]
        assert rows_to_text(items) == "01 ⑤  02 ②  03 ①"

    def test_세로로_쌓인_줄은_그대로_줄바꿈(self):
        items = [(_R(10, 100, 120), "첫 줄"), (_R(10, 130, 150), "둘째 줄")]
        assert rows_to_text(items) == "첫 줄\n둘째 줄"

    def test_번호머리_제목은_한_칸(self):
        # 정답 실측: EBS-E26-013 ans p0001 "      01 사회·문화 현상의 이해"(한 칸)
        items = [(_R(10, 100, 120), "01"), (_R(90, 100, 120), "사회·문화 현상의 이해")]
        assert rows_to_text(items) == "01 사회·문화 현상의 이해"

    def test_빈칸_채우기_괄호는_한_칸(self):
        items = [(_R(10, 100, 120), "기능적 단위는 ("), (_R(90, 100, 120), ")이다.")]
        assert rows_to_text(items) == "기능적 단위는 ( )이다."

    def test_섞인_두_줄은_각각_이어진다(self):
        items = [(_R(10, 100, 120), "1 ③"), (_R(60, 100, 120), "2 ⑤"),
                 (_R(10, 130, 150), "3 ④"), (_R(60, 130, 150), "4 ②")]
        assert rows_to_text(items) == "1 ③  2 ⑤\n3 ④  4 ②"


class TestTwoCellGapSurvivesBraille:
    def test_점역해도_두_칸이_남는다(self):
        # braillify는 안쪽 연속 공백을 삼키고 _collapse_spaces가 또 뭉갠다 — 둘 다 통과해야 한다.
        out = translate_tagged_text("① ㄱ, ㄷ  ② ㄱ, ㄹ")
        assert "⠀⠀" in out, out

    def test_모드전환_부산물_두_칸은_그대로_한_칸(self):
        # 원문이 한 칸인데 숫자→로마자 전환으로 생기는 이중 공백은 계속 한 칸으로 정리한다.
        assert "⠀⠀" not in translate_tagged_text("180 cm")

    def test_제어문자_잔류_없음(self):
        out = translate_tagged_text("01 ⑤  02 ②")
        assert all(ord(c) >= 0x20 for c in out), repr(out)
