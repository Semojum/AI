"""규정 제56항 굵은 글자 점형 — 배선 회귀 테스트 (원장 B-05).

왜 이 파일이 있나: 굵은 글자는 **검출을 일부러 안 붙인** 상태다(2026-08-22 대표 결재).
표본이 홀드아웃 한 권에 몰려 있어 dev·val로는 검출기를 만들 수도 검증할 수도 없기
때문이다. 그래서 지금 살아 있는 것은 "태그가 오면 점형이 나가는 배선"뿐이고,
그 배선이 **죽은 코드로 남지 않도록** 여기서 붙잡아 둔다(대표 조건 ②).

규정 원문(`braille-source/text/규정_텍스트.txt:2467~`):
  제56항 드러냄표( ̊)나 밑줄로 강조된 글자체는 `,- -'`으로,
         굵은 글자로 강조된 글자체는 `;- -2`으로 묶어 나타낸다.
  예문   서울은 대한민국의 **수도**이다.  →  `,s&z`irj3eq@maw`;-,miu-2oi4`
"""
from app.ai.braille import tag_names as _TAGS
from app.ai.braille.translator import _TAG_PAIR_MARKER, translate_tagged_text

BOLD_OPEN, BOLD_CLOSE = "⠰⠤", "⠤⠆"
EMPH_OPEN, EMPH_CLOSE = "⠠⠤", "⠤⠄"


def test_bold_marker_matches_regulation():
    """제56항 굵은 글자 = ⠰⠤ … ⠤⠆."""
    assert _TAG_PAIR_MARKER[_TAGS.BOLD] == (BOLD_OPEN, BOLD_CLOSE)


def test_bold_and_emphasis_are_different_marks():
    """드러냄표(⠠⠤…⠤⠄)와 굵은 글자(⠰⠤…⠤⠆)는 다른 점형이다 — 한 조항의 두 절이다."""
    assert _TAG_PAIR_MARKER[_TAGS.EMPH] != _TAG_PAIR_MARKER[_TAGS.BOLD]


def test_bold_tag_emits_regulation_example():
    """규정 예문 그대로 — '수도'가 ⠰⠤…⠤⠆로 묶인다."""
    out = translate_tagged_text("서울은 대한민국의 <!굵은>수도<!/굵은>이다.")
    assert BOLD_OPEN in out and BOLD_CLOSE in out
    i, j = out.index(BOLD_OPEN), out.index(BOLD_CLOSE)
    assert i < j, "여는 점형이 닫는 점형보다 앞에 와야 한다"
    inner = out[i + len(BOLD_OPEN):j]
    assert inner and "⠠⠍" in inner, "묶인 자리에 본문이 들어 있어야 한다(수도)"


def test_bold_tag_does_not_leak_literal():
    """태그 문자열이 그대로 점자화되면 안 된다(불변규칙 9 — 리터럴 금지)."""
    out = translate_tagged_text("<!굵은>가<!/굵은>")
    assert "<" not in out and ">" not in out and "!" not in out
