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


def test_밑줄표를_떼면_영어_줄로_읽힌다():
    """`_english_line`(제29항 [다만])은 정방향 왕복이 맞아야 영어로 본다.

    밑줄표가 섞이면 왕복이 안 맞아 그 줄이 통째로 한글로 깨졌다. 그래서 이 표는
    `_COMBINED` 가 아니라 **줄을 쪼개기 전에** 뗀다.
    """
    from app.utils.braille_back import _english_line, _strip_typeform_marks

    line = "⠮⠀⠸⠺⠀⠷⠀⠼⠆⠀⠸⠂⠍⠔⠊⠍⠁⠇⠊⠎⠍⠀⠾⠀⠥⠀⠯⠀⠇⠑⠜⠝"
    assert _english_line(line) is None
    assert _english_line(_strip_typeform_marks(line)) is not None
