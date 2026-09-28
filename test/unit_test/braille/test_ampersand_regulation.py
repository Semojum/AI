"""#910 — 한글 문맥의 & 는 ⠴⠈⠯⠲ 로 적는다(「한국 점자 규정」 제71항 [다만]).

book 모드가 & 를 ⠯ 한 칸으로 바꾸고 앞뒤 칸을 지웠다. 근거("정답 도서는 ⠯ 단독")는 지금 gold 에
없다 — 구판 gold 도 한글 문맥은 ⠴⠈⠯⠲, 영어 줄은 ⠈⠯ 로 규정대로 적는다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def test_규정_예문_종이접기():
    # 재추출 2844행 — 앞뒤 칸은 묵자대로 둔다.
    assert _body("종이접기 & 클레이아트") == \
        ascii_to_unicode('.=o.sb@o`0@&4`f!"no<h{', backtick="space")


def test_붙어_나와도_감싼다():
    # 구판 gold 수학2 `출제 경향 ⠴⠈⠯⠲ 대표 기출`(묵자 추출은 칸을 잃고 붙어 온다).
    assert "⠶⠴⠈⠯⠲⠊⠗" in _body("출제경향&대표기출문제")


def test_영어_줄은_감싸지_않는다():
    # 구판 gold 외국어 `Words ⠈⠯ Phrases` — 영어 구간 안이라 UEB & 그대로, 칸도 그대로.
    assert "⠎⠀⠈⠯⠀⠠⠏" in _body("Words & Phrases")


def test_로마자_사이도_감싸지_않는다():
    out = _body("IBM and AT&T.")
    assert "⠞⠈⠯⠠⠞" in out and "⠴⠈⠯⠲" not in out
