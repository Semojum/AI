"""#917 — 줄표·붙임표 뒤 로마자의 헛 로마자표, 한글 섞인 세그 끝 로마자 + 쌍점의 헛 종료표.

「한국 점자 규정」 제33항(재추출 1667행): 점형이 다른 문장 부호(, : ; ―)가 로마자와 한글 사이에
나오면 로마자 종료표를 적지 않고 문장 부호는 한글 점자로 적는다.
`:` 는 문자표가 먼저 ⠐⠂ 로 바꿔 다음 조각으로 가므로 앞 세그가 그 쌍점을 못 봤다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def test_규정_예문_WHO():
    # 재추출 1674~1675행 — 한글이 없는 세그라 종전에도 맞았다(대조군).
    assert _body("WHO: 세계 보건 기구") == \
        ascii_to_unicode('0,,who"1`,n@/`~u@)`@o@m', backtick="space")


def test_한글_뒤_로마자_쌍점에_종료표가_없다():
    # 실물 `학생 A: 많이…`(구판 언어) · `이 PD: 먼저…`(2027 화법과 작문). gold 는 ⠴⠠x⠐⠂.
    # PD 는 단축형 paid(⠏⠙)와 셀이 같아 1종 지시자 ⠰ 가 붙는다 — val 005 p0187 gold `0;,,pd"1`(원장 C-99).
    for text, want in (("학생 A: 많이 팔린", "⠴⠠⠁⠐⠂⠀"), ("이 PD: 먼저 저는", "⠴⠰⠠⠠⠏⠙⠐⠂⠀")):
        out = _body(text)
        assert want in out and "⠲⠐⠂" not in out, (text, out)


def test_줄표_붙임표_뒤_로마자표는_하나():
    assert _body("범례 — A: 갑") == "⠘⠎⠢⠐⠌⠀⠤⠤⠀⠴⠠⠁⠐⠂⠀⠫⠃"
    assert _body("범례 - A: 갑") == "⠘⠎⠢⠐⠌⠀⠤⠀⠴⠠⠁⠐⠂⠀⠫⠃"


def test_U2015_줄표도_같다():
    assert _body("범례 ― A: 갑") == "⠘⠎⠢⠐⠌⠀⠤⠤⠀⠴⠠⠁⠐⠂⠀⠫⠃"


def test_쌍점이_없으면_종료표는_그대로():
    # 제29항 — 로마자 뒤 빈칸 + 한글은 종료표를 적는다.
    assert "⠴⠠⠁⠲⠀⠫⠃" in _body("범례 — A 갑")


def test_붙임표_감쌈_관행은_그대로():
    # `-⠴UN-` 관행(사회문화 p100·108) — 붙임표에 붙은 로마자에만 여는 ⠴.
    assert _body("-UN-") == "⠤⠴⠠⠠⠥⠝⠤"
