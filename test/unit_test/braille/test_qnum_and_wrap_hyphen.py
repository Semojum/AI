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

from app.ai.braille.translator import (
    _QNUM_RE,
    translate_body,
    translate_visual,
    translate_with_breaks,
)

_PERIOD = "⠲"
_HYPHEN = "⠤"
_OPEN_PAREN = "⠦⠄"      # 규정 제49항 여는 소괄호
_CLOSE_PAREN = "⠠⠴"     # 닫는 소괄호
_MINUS = "⠔"


class TestQuestionNumberPeriod:
    """_QNUM_RE는 요소 전체에서 먼저 적용된다 — 추출이 문항 번호를 자기 줄에 홀로
    주더라도('2\\n다음은…') 마침표를 붙일 수 있어야 한다."""

    def test_번호가_홀로_선_줄에도_마침표(self):
        lines, _ = translate_with_breaks("2\n다음은 수업 시간에 나눈 대화이다")
        assert lines[0].endswith(_PERIOD), f"문항 번호 마침표 없음: {lines[0]}"

    def test_한_자리_번호는_마침표를_찍는다(self):
        # ⠼⠃ = 수표+2, 그 뒤 온점 1개(⠲⠲가 아니다)
        lines, _ = translate_with_breaks("2 자연수를 모두 더하면")
        assert lines[0].startswith("⠼⠃" + _PERIOD), f"문항 번호 마침표: {lines[0]}"
        assert not lines[0].startswith("⠼⠃" + _PERIOD * 2), f"마침표 중복: {lines[0]}"

    def test_두_자리_번호는_마침표를_안_찍는다(self):
        """M006(2026-08-23) — 정답은 두 자리·영패딩 번호 뒤에 마침표를 **안 찍는다**.
        줄머리 제약을 푼 전수 대조에서 dev 1,031 · val 405 건에 **반례 0**이다.
        (구판 테스트는 `02 자연수` → `02.` 를 '종전대로'로 박아 뒀는데 그건 우리 관행이었다.)
        규정 근거는 「점자 도서 제작 지침」 4194행 — 번호 체계는 원본 자료를 따른다.
        """
        lines, _ = translate_with_breaks("02 자연수를 모두 더하면")
        assert lines[0].startswith("⠼⠚⠃"), f"번호 자체가 어긋난다: {lines[0]}"
        assert not lines[0].startswith("⠼⠚⠃" + _PERIOD), f"두 자리에 마침표가 붙었다: {lines[0]}"

    def test_멱등_이중적용_없음(self):
        """요소 단위 선적용 뒤 _apply_book_style이 같은 규칙을 다시 걸어도
        마침표가 겹치면 안 된다(치환 후 '2.' 다음이 '.'이라 룩어헤드가 실패)."""
        once = _QNUM_RE.sub(r"\1.", "2\n다음은 수업")
        twice = _QNUM_RE.sub(r"\1.", once)
        assert once == twice == "2.\n다음은 수업"

        # 두 자리는 애초에 발동하지 않는다(M006) — 멱등성은 한 자리로 본다.
        once1 = _QNUM_RE.sub(r"\1.", "7 자연수")
        assert _QNUM_RE.sub(r"\1.", once1) == once1 == "7. 자연수"
        assert _QNUM_RE.sub(r"\1.", "02 자연수") == "02 자연수"

        lines, _ = translate_with_breaks("2\n다음은 수업 시간에 나눈 대화이다")
        assert lines[0].count(_PERIOD) == 1, f"마침표 중복: {lines[0]}"

    def test_뒤에_본문이_없는_숫자는_그대로(self):
        # 쪽번호 '16'은 정답도 마침표를 안 찍는다
        lines, _ = translate_with_breaks("16")
        assert _PERIOD not in lines[0], f"쪽번호에 마침표: {lines[0]}"

    def test_번호_뒤가_기호면_항목번호가_아니다(self):
        """수식 시작·화살표 뒤 숫자는 항목 번호가 아니다(원장 C-41, 2026-09-08).

        gold 전수 대조에서 손해 0 · 이득 dev 74. 눈검사 `수학 I ans p0009`.
        """
        for src in (r"6 $|\log_{a} a^{2}|=2$", "2 → 추분(9월 20일경)", "5 → 하지로 순환"):
            assert not _QNUM_RE.search(src), f"기호 뒤인데 발동한다: {src}"

    def test_번호_뒤가_낱말이면_종전대로_찍는다(self):
        """회귀 방어 — gold 가 마침표를 찍는 쪽(본책 단원 소제목·발문)은 건드리지 않는다.

        `(`·`[`·`<` 는 일부러 남겨 뒀다(근거 없음 = 끄지 않는다).
        """
        for src in ("1 동아시아의 과거와 현재", "3 (가) 황제에 대한 설명으로 옳은 것은?",
                    "6 <!강조>근대적 생활 방식의 확산<!/강조>", "1 [26008-0001]"):
            assert _QNUM_RE.search(src), f"낱말 뒤인데 안 찍는다: {src}"


class TestVisualItemNumber:
    """시각 자료 설명·전사는 항목 번호 마침표 관행을 아예 안 탄다(원장 C-41).

    근거: 「점자 자료 제작 지침」 2.4.1 (1) "**본문의** 번호 체계는 원본 자료의 형태를
    따른다"(재추출 892행) · 6.1.4 (6) "과정 흐름에 대한 설명은 위계가 있는 개조식
    항목으로 표현한다"(3016행) — 그 항목 번호는 점역자가 세운 것이라 본책 단원 번호가
    아니다. 시각 자료 설명에는 대응 gold 가 없어 요소 유형으로만 가른다.
    """

    def test_시각_설명은_마침표를_안_찍는다(self):
        for src in ("1 태양을 중심으로 지구가 공전한다",
                    "2 중앙 집권 체제가 확립되었다"):
            lines, _ = translate_visual(src)
            assert _PERIOD not in lines[0][:4], f"시각 설명에 온점: {lines[0]}"

    def test_본문은_종전대로_찍는다(self):
        """본문 경로는 gold 가 마침표를 찍는 쪽이라 건드리지 않는다."""
        lines, _ = translate_body("1 태양을 중심으로 지구가 공전한다")
        assert lines[0].startswith("⠼⠁" + _PERIOD), f"본문 마침표 손상: {lines[0]}"

    def test_끄는_것은_번호_마침표뿐(self):
        """다른 관행(괄호 감쌈 등)까지 같이 꺼지면 안 된다."""
        body, _ = translate_body("보기 (가) 를 보자")
        visual, _ = translate_visual("보기 (가) 를 보자")
        assert body[0] == visual[0], f"번호 마침표 밖까지 갈렸다: {body[0]} vs {visual[0]}"


class TestWrapHyphenPlaceholder:
    """괄호가 음수 부호로 재해석되면 안 된다.

    2026-08-06 괄호 판정 번복(원장 R-06) 이후 괄호는 **소괄호 셀**(⠦⠄ … ⠠⠴)로 나간다.
    감쌈 붙임표 경로는 배열형 답지만 쓰지만, 음수 오독 가드는 그대로 지켜야 한다.
    """

    def test_공백_낀_괄호는_소괄호(self):
        # 구버그: '(2010 수능)' → '-2010 수능-' → 여는 하이픈이 음수로 읽혀 ⠔
        lines, _ = translate_with_breaks("(2010 수능)")
        assert lines[0].startswith(_OPEN_PAREN), f"소괄호 아님: {lines[0]}"
        assert not lines[0].startswith(_MINUS)
        assert lines[0].endswith(_CLOSE_PAREN)

    def test_공백_없는_괄호도_소괄호(self):
        lines, _ = translate_with_breaks("(2010)")
        assert lines[0].startswith(_OPEN_PAREN) and lines[0].endswith(_CLOSE_PAREN)

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
