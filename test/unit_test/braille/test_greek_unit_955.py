"""#955 — 그리스 문자 단위(μm)는 수식이 아니다(「한국 점자 규정」 제69항 [붙임 1])."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def test_규정_예문():
    # 재추출 2713행 `1 μm는 1,000분의 1 mm이다.` = `#a`0.mm4cz`#a1jjj^gw`#a`0mm4oi4`
    assert _body("1 μm는 1,000분의 1 mm이다.") == \
        ascii_to_unicode("#a`0.mm4cz`#a1jjj^gw`#a`0mm4oi4", backtick="space")


def test_문장_중간_두_칸이_안_붙는다():
    assert _body("길이는 1 μm이다.") == "⠈⠕⠂⠕⠉⠵⠀⠼⠁⠀⠴⠨⠍⠍⠲⠕⠊⠲"


def test_홀로_선_뮤는_수식이다():
    assert _body("μ=0.3") == "⠨⠍⠒⠒⠼⠚⠲⠉"


# ── 라틴·사각 단위 (제69항) ─────────────────────────────────────────────────────
def test_빗금_복합_단위는_한_구간():
    # 2691행 `160㎎/㎗를` = `#afj0mg_/dl4"!` · 2694행 `cal/㎠/min이` = `0cal_/cm~#b_/m94o`
    assert _body("그의 혈당 수치가 160㎎/㎗를 넘었다.") == ascii_to_unicode(
        '@[w`j\\i7`,m;o$`#afj0mg_/dl4"!`cs5s/i4', backtick="space")
    assert "⠴⠉⠁⠇⠸⠌⠉⠍⠘⠼⠃⠸⠌⠍⠔⠲⠕" in _body("일사량 단위에는 cal/㎠/min이 있다.")


def test_두_번째_cm_도_숫자에_붙지_않는다():
    # C5 — 둘째 `6cm` 가 숫자에 붙어 ⠼⠋⠉⠍(=633)로 읽히면 안 된다(생명과학 p100). #958 부터는 단위마다
    #   로마자표가 서서 갈린다(제69항 `#ahj0cm4`).
    out = _body("지점이 3cm, 6cm일 때")
    assert "⠼⠋⠉" not in out and "⠼⠋⠴⠉⠍⠲" in out


def test_줄머리_단위_수량에_문항번호_마침표가_없다():
    # 주자 2027 생명과학 표 셀 `7 mL`·`4 kg` 이 문항 번호로 읽혀 ⠼⠛⠲ 가 됐다
    for s in ("7 mL", "4 kg", "1 mm", "3 ㎠"):
        assert not _body(s).startswith(_body(s)[:2] + "⠲"), s
    assert _body("3 m").startswith("⠼⠉⠲")        # 한 글자 단위는 번호와 못 가른다(그대로)
