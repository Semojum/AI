"""#913 — 각주 별표는 묵자 자리에 ⠐⠔ 로 붙여 적는다(「한국 점자 규정」 제60항 [다만 2]).

book 모드가 한글 뒤 별표를 번호 붙임표 ⠤⠼⠁⠤ 로 바꿨다. 근거가 구판 실측이었고 주자 2027 gold 는
규정대로다(묵자 한글 뒤 별표가 있는 13쪽: gold ⠐⠔ 26 · ⠤⠼N⠤ 0).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def test_규정_예문_모티프():
    # 재추출 2537~2541행 `…euhod{"9"!…` — 모티프⠐⠔를.
    assert "⠑⠥⠓⠕⠙⠪⠐⠔⠐⠮" in _body("작품의 모티프*를 따와")


def test_2027_gold_참조_자리():
    # vl2027 EBS-E26-012 body p28 gold 셀 그대로.
    out = _body("고조는 몰래 사자를 연지*에게 보내")
    assert "⠡⠨⠕⠐⠔⠝⠈⠝" in out and "⠤⠼⠁⠤" not in out


def test_뜻풀이_줄머리는_한_칸_띄운다():
    # 같은 쪽 gold `⠐⠔⠀⠡⠨⠕` — 제60항 본문 "앞뒤를 한 칸씩 띄어 쓴다".
    assert _body("* 연지 : 선우의 부인").startswith("⠐⠔⠀⠡⠨⠕")
