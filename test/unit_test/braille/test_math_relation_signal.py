"""겹친 관계 기호가 수식 구간 신호로 안 잡히던 문제 (「수학 점자」 제4·7항, 2026-09-04).

`_classify_token` 이 수표(⠼)가 있어야 수식을 봤다. `ax=b`(⠁⠭⠒⠒⠃)에는 숫자가 없어
TEXT 로 떨어졌고 변수가 한글 약자로 읽혔다 — `a옥=b`. 원장 C-104.
"""

from app.utils.braille_back import decode


def test_숫자_없는_등식도_수식으로_읽는다():
    assert decode("⠁⠭⠒⠒⠃") == "ax=b"


def test_숫자_없는_부등식도_수식으로_읽는다():
    assert decode("⠁⠢⠢⠃") == "a>b"


def test_수표가_있는_부등식의_변수도_산다():
    assert decode("⠭⠔⠔⠼⠚") == "x<0"
    assert decode("⠽⠨⠒⠒⠼⠚") == "y≠0"


def test_토큰_전체가_등록된_기호면_수식으로_안_보낸다():
    """`≲`(⠔⠔⠈⠔)은 ⠔⠔ 를 품지만 그 자체가 한 기호다."""
    assert decode("⠔⠔⠈⠔") == "≲"


def test_한글과_겹치는_셀은_신호로_안_쓴다():
    """`⠲⠲`(≥)·`⠌`(분수선)·`⠡`(×)는 받침 ㅍ·ㅖ·약자 '연'과 점형이 같다."""
    from app.utils.braille_back import _MATH_REL_RE

    for cell in ("⠲⠲", "⠌", "⠡"):
        assert not _MATH_REL_RE.search(cell), cell


def test_홑_로마자로_시작하는_부등식은_수식이다():
    """`⠲⠲`(≥)는 받침 ㅍ·마침표와 겹쳐 무조건 신호로는 못 쓴다(전권 36.0%가 본문 한글).

    다만 토큰 첫 칸이 홑 로마자면 겹칠 것이 없다 — 한글은 낱자 하나로 낱말을
    시작하지 않는다. 표본 2,362쪽 실측 16건이 전부 수식이고 손해가 없었다.
    """
    assert decode("⠭⠲⠲⠼⠚") == "x≥0"
    assert decode("⠝⠲⠲⠼⠓") == "n≥8"
    assert decode("⠭⠨⠲⠲⠽") == "x≱y"


def test_홑_로마자가_아니면_안_건드린다():
    """`⠲⠲⠲` 은 마침표 셋이다 — 첫 칸이 로마자가 아니라 걸리지 않는다."""
    assert decode("⠲⠲⠲") == "......"
