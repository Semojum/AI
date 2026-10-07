"""한글 없는 영어 줄 안 쌍점·쌍반점 → 통일영어점자 ⠒ · ⠆ (이슈 #1175).

「한국 점자 규정」 제32항(재추출 1650행): 로마자표와 종료표 사이는 「통일영어점자 규정」. 제33항(1667행): 쉼표·쌍점·
쌍반점은 두 규정 점형이 달라, 로마자와 **한글 사이**에서만 한글 점자로 적는다.
symbol_table 이 `:`→⠐⠂ · `;`→⠰⠆ 를 구간 판정보다 먼저 치환해 `_span_gap` 의 UEB 처리가 닿지 못했다.
"""
import pytest

from app.ai.braille.translator import translate_body


def _br(text: str) -> str:
    return "".join(translate_body(text)[0])


def test_영어_줄_쌍점():
    """gold MS-REF-T25-078 body p0011 `③ beard: the hair on a man's chin` = …⠃⠑⠜⠙⠒⠀⠮…"""
    assert "⠜⠙⠒⠀⠮" in _br("beard: the hair")


def test_영어_줄_쌍반점():
    """gold HS-REF-T24-136 body p0270 `company he keeps; for there is a` = …⠅⠑⠑⠏⠎⠆⠀⠿…"""
    assert "⠏⠎⠆⠀⠿" in _br("he keeps; for there is a")


@pytest.mark.parametrize("text,cells", [
    ("A: X의 총발생량이", "⠴⠠⠁⠐⠂⠀⠴⠠⠭"),          # gold EBS-E26-001 body p0027 — 한글 섞인 줄의 말머리는 한글 꼴
    ("WHO: 세계 보건 기구", "⠴⠠⠠⠺⠓⠕⠐⠂"),        # 규정 제33항 예문 `0,,who"1`
])
def test_한글_섞인_줄은_종전대로(text, cells):
    assert _br(text).startswith(cells)
