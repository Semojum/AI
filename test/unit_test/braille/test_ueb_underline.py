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


# ── 한·영 혼합 줄의 영어 구간 (제32항 · 원장 R-70) ──────────────────────────
# 한국어 발문 안에 영어가 섞이면 줄 전체가 `_english_line` 을 통과할 수 없어, 밑줄
# 구간표가 미해독으로 새고 영어는 뜻 없는 한글로 나갔다. 짝 안쪽만 영어로 읽는다.
# 실측(gold 전권 18,892쪽): 짝 1,774회·573쪽, 그중 줄을 넘는 짝 1,079회.

def test_혼합_줄의_구간표_안쪽만_영어로_읽는다():
    """ES-TXT-KA0107/p0028 실물 — `A: Can I get a map?` 의 밑줄 구간."""
    line = "⠀⠀⠴⠠⠁⠒⠀⠠⠉⠁⠝⠀⠠⠊⠀⠸⠶⠛⠑⠞⠀⠁⠀⠍⠁⠏⠸⠄⠦"
    out = decode(line)
    assert "get a map" in out
    assert "⟨2838⟩" not in out


def test_줄을_넘는_구간표도_읽는다():
    """EBS-E26-006/p0025 실물 — 구간이 두 줄에 걸친다(32칸 조판)."""
    out = decode("⠀⠀⠼⠚⠙⠀⠑⠕⠦⠨⠯⠀⠰⠟⠀⠴⠸⠶⠩⠁⠅⠑⠎⠀⠥⠀⠞⠕⠀⠮\n⠉⠕⠗⠑⠸⠄⠲")
    # `⠥` 는 낱자 u 가 아니라 단어기호 `us` 다(eng_braille.WORDSIGNS · 규정 제37항 목록).
    assert "shakes us to the" in out and "core." in out
    assert "⟨2838⟩" not in out


def test_도형_반복_틀은_구간표로_보지_않는다():
    """`⠸⠶ⁿ⠇`(제57항 [붙임] 계열)은 도형이다 — 안쪽이 통째로 틀이면 영어가 아니다.

    ES-TXT-KA0171 실물 `⠸⠶⠶⠶⠇` + 다음 줄 `⠸⠄`.
    """
    assert decode("⠸⠶⠶⠶⠇\n⠀⠀⠸⠄").startswith("□□□")


def test_읽을_수_없는_조각에는_표를_새로_붙이지_않는다():
    """줄을 넘는 짝의 조각이 영어로 안 읽히면 종전 출력을 그대로 둔다.

    조각마다 표를 붙이면 그 ⠸ 가 미해독으로 새어 이물질이 **늘어난다**(첫 판 231줄).
    """
    src = "⠀⠀⠸⠶⠈⠼⠂⠱⠕\n⠇⠊⠧⠑⠎⠀⠁⠉⠗⠀⠮⠀⠌⠗⠑⠑⠞⠸⠄⠲"
    first, second = decode(src).split("\n")
    assert second == "lives across the street."
    assert first == decode("⠀⠀⠸⠶⠈⠼⠂⠱⠕")     # 앞줄은 종전 그대로
