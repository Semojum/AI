"""UEB 밑줄 표시가 미해독 셀로 새던 문제 (2026-09-04).

국어 교재 속 영어 지문에서 밑줄 친 낱말 앞에 `⠸⠂`(밑줄 낱말표), 구간 끝에 `⠸⠄`(종료표)를
적는다. 역맵에 없어 `⠸`가 미지셀 `⟨2838⟩`로 새고 뒤 셀이 쉼표·아포스트로피로 읽혔다.
gold 전권 18,892쪽 실측: `⠸⠂` 5,474건 · `⠸⠄` 1,495건.
"""

from app.utils.braille_back import decode


def test_밑줄_낱말표는_사라진다():
    assert "⟨2838⟩" not in decode("⠸⠂⠎⠁⠙")
    assert "," not in decode("⠸⠂⠎⠁⠙")


def test_밑줄_종료표는_사라진다():
    assert decode("⠸⠄") == ""
    assert "'" not in decode("⠛⠇⠁⠎⠎⠸⠄")


def test_굵게_이탤릭_낱말표는_안_건드린다():
    """`⠘⠂`·`⠨⠂`는 한글 음절 '발'·'잘'과 점형이 같다 — 떼면 본문을 먹는다."""
    assert decode("⠘⠂") == "발"
    assert decode("⠨⠂") == "잘"
    assert decode("⠘⠄") == "밧"


def test_밑줄_빈칸은_그대로():
    """`⠸⠤`(제73항 밑줄 빈칸)는 별건이다 — 밑줄 하나로 편다."""
    assert decode("⠸⠤") == "_"


def test_밑줄_낱말표가_영어_줄_판정을_막지_않는다():
    """`⠸⠂`(UEB 밑줄 낱말표)가 낱말 런을 끊어 `_english_line`(#482)을 막았다.

    gold 전권 18,892쪽: `⠸⠂` 든 줄 4,197 중 통과가 0 → 표를 벗기면 724.
    """
    from app.utils.braille_back import _UEB_UNDERLINE_RE, _english_line

    line = "⠮⠀⠸⠺⠀⠷⠀⠼⠆⠀⠸⠂⠍⠔⠊⠍⠁⠇⠊⠎⠍⠀⠾⠀⠥⠀⠯⠀⠇⠑⠜⠝"
    assert _english_line(line) is None
    assert _english_line(_UEB_UNDERLINE_RE.sub("", line)) is not None
