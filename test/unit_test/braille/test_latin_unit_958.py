"""#958 — 숫자 뒤 로마자 단위를 로마자표·종료표 한 구간으로(「한국 점자 규정」 제69항)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def _brf(s: str) -> str:
    return ascii_to_unicode(s, backtick="space")


def test_한글_없는_줄():
    # 재추출 2685행 `180cm` = `#ahj0cm4`
    assert _body("180cm") == _brf("#ahj0cm4")


def test_인치는_약자가_아니다():
    # 재추출 2697행 `1in는 2.54cm이다.` = `#a0in4cz`#b4ed0cm4oi4`
    assert _body("1in는 2.54cm이다.") == _brf("#a0in4cz`#b4ed0cm4oi4")
    assert "⠔" in _body("Top 10 in Korea")          # 영어 문장의 in 은 약자 그대로


def test_한글_단위_뒤_빗금_끝_종료표():
    # 재추출 2771행 `80킬로미터/h` = `#hj`fo1"ueohs_/0h4`
    assert _body("80킬로미터/h") == _brf('#hj`fo1"ueohs_/0h4')


def test_로마자_빗금_복합_단위는_한_구간():
    # 2027 gold 생명과학 E26-001 p020 `2 cm/ms` = ⠴⠉⠍⠸⠌⠍⠎ (빈칸은 규정대로 묵자를 따른다)
    assert "⠼⠃⠀⠴⠉⠍⠸⠌⠍⠎⠲⠕⠊" in _body("속도는 2 cm/ms이다")
    assert "⠴⠅⠉⠁⠇⠲⠸⠌⠉⠡" in _body("340000 kcal/년")   # 뒤가 한글이면 빗금 앞 종료표


def test_표_셀_단위():
    # 2027 gold 생명과학 E26-001 p037·p047 `⠼⠃⠚⠴⠍⠠⠇` · `⠼⠙⠴⠅⠛`
    assert _body("7 mL") == "⠼⠛⠀⠴⠍⠠⠇⠲"
    assert _body("4 kg") == "⠼⠙⠀⠴⠅⠛⠲"


def test_한_글자는_변수와_같아_그대로():
    assert "⠴" not in _body("3 m") and "⠴" not in _body("5g")


def test_부호_앞_종료표():
    # 2027 gold 사회문화 E26-005 p196·p215 · 세계지리 E26-012 p006
    assert _body("반경: 1km.").endswith("⠼⠁⠴⠅⠍⠲")                 # 제33항 [다만] 마침표와 점형이 같다
    assert "⠼⠛⠴⠉⠍⠐⠀" in _body("가로 7cm, 세로 24cm의")         # 제33항 쉼표 앞
    assert "⠴⠍⠍⠠⠴" in _body("강수량이 적음(400~600mm)")          # 제34항 닫는 괄호 앞
