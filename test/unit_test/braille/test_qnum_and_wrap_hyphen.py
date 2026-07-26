"""문항번호 마침표 층위 이동 + 감쌈 붙임표 자리표시자 회귀 테스트.

순환검증 금지: 기대 점형은 규정·도서 관행에서 도출한다(생산 코드로 생성하지 않음).
  · 마침표 ⠲ · 붙임표 ⠤ = 「한국 점자 규정」 **제49항 문장 부호**(규정_텍스트.txt 2113행~).
    감쌈 -가-·-1-은 그 붙임표를 쓰는 도서 관행이다(D-01, memory: 도서 관행≠규정).
  · 뺄셈표(음수 부호) ⠔ = **제45항 연산 기호와 비교 기호**(2027행) — 감쌈 붙임표와 다른 셀.
    부등식 예시 -1<x<3(`9#a99x99#c`)의 자리는 수학 점자 제4항 4호(3075행)다.
  ⚠ 조항 번호를 적을 때는 braille-source 원문을 직접 열어 확인할 것 — 초안에 '제5항 온점'·
    '제63항 붙임표'·'수학 제45항 4호'라는 실재하지 않는 인용이 들어갔다가 독립 검증에서
    잡혔다(2026-07-27). 제5항은 총칙, 제63항은 긴소리표, 수학편 제45항은 함수다.
"""
from __future__ import annotations

from app.ai.braille.translator import _QNUM_RE, translate_with_breaks

_PERIOD = "⠲"
_HYPHEN = "⠤"
_MINUS = "⠔"


class TestQuestionNumberPeriod:
    """_QNUM_RE는 요소 전체에서 먼저 적용된다 — 추출이 문항 번호를 자기 줄에 홀로
    주더라도('2\\n다음은…') 마침표를 붙일 수 있어야 한다."""

    def test_번호가_홀로_선_줄에도_마침표(self):
        lines, _ = translate_with_breaks("2\n다음은 수업 시간에 나눈 대화이다")
        assert lines[0].endswith(_PERIOD), f"문항 번호 마침표 없음: {lines[0]}"

    def test_한_줄에_이어진_번호도_종전대로(self):
        # ⠼⠚⠃ = 수표+02, 그 뒤 온점 1개(⠲⠲가 아니다)
        lines, _ = translate_with_breaks("02 자연수를 모두 더하면")
        assert lines[0].startswith("⠼⠚⠃" + _PERIOD), f"문항 번호 마침표: {lines[0]}"
        assert not lines[0].startswith("⠼⠚⠃" + _PERIOD * 2), f"마침표 중복: {lines[0]}"

    def test_멱등_이중적용_없음(self):
        """요소 단위 선적용 뒤 _apply_book_style이 같은 규칙을 다시 걸어도
        마침표가 겹치면 안 된다(치환 후 '2.' 다음이 '.'이라 룩어헤드가 실패)."""
        once = _QNUM_RE.sub(r"\1.", "2\n다음은 수업")
        twice = _QNUM_RE.sub(r"\1.", once)
        assert once == twice == "2.\n다음은 수업"

        once1 = _QNUM_RE.sub(r"\1.", "02 자연수")
        assert _QNUM_RE.sub(r"\1.", once1) == once1 == "02. 자연수"

        lines, _ = translate_with_breaks("2\n다음은 수업 시간에 나눈 대화이다")
        assert lines[0].count(_PERIOD) == 1, f"마침표 중복: {lines[0]}"

    def test_뒤에_본문이_없는_숫자는_그대로(self):
        # 쪽번호 '16'은 정답도 마침표를 안 찍는다
        lines, _ = translate_with_breaks("16")
        assert _PERIOD not in lines[0], f"쪽번호에 마침표: {lines[0]}"


class TestWrapHyphenPlaceholder:
    """(N) 감쌈 붙임표는 음수 부호로 재해석되면 안 된다 — 자리표시자로 보호한다."""

    def test_공백_낀_괄호도_붙임표(self):
        # 구버그: '(2010 수능)' → '-2010 수능-' → 여는 하이픈이 음수로 읽혀 ⠔
        lines, _ = translate_with_breaks("(2010 수능)")
        assert lines[0].startswith(_HYPHEN), f"감쌈 붙임표 아님: {lines[0]}"
        assert not lines[0].startswith(_MINUS)
        assert lines[0].endswith(_HYPHEN)

    def test_공백_없는_괄호는_종전대로(self):
        lines, _ = translate_with_breaks("(2010)")
        assert lines[0].startswith(_HYPHEN) and lines[0].endswith(_HYPHEN)

    def test_진짜_음수는_뺄셈표_유지(self):
        lines, _ = translate_with_breaks("-3보다 크다")
        assert lines[0].startswith(_MINUS), f"음수 부호 손상: {lines[0]}"

    def test_자리표시자_잔류_없음(self):
        # 비문자 U+FDD0/1이 출력에 새어 나오면 점자 파일이 깨진다
        for src in ("(2010 수능)", "(가)", "(SNS)", "산소(O₂)와 이산화탄소",
                    "(A) 다음 글을 읽고", "정답률(%)은 -5보다 크다"):
            lines, _ = translate_with_breaks(src)
            joined = "".join(lines)
            assert "\ufdd0" not in joined and "\ufdd1" not in joined, src
