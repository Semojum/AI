"""T25 — 2027 생명과학 글꼴이 아래·위첨자를 라틴 1 글자 칸(Á·ª·Ñ)에 싣던 것.

복원 전: `COª` → CO(ª 가 조용히 지워져 일산화탄소가 된다) · `GÁ기` → GA기 · `RhÑ` → RhN.
기대값은 gold(EBS-E26-001) 셀이다.
"""
import pytest

from app.ai.braille.translator import translate_body


def _b(text: str) -> str:
    return translate_body(text)[0][0]


@pytest.mark.parametrize("text, cells", [
    ("Oª와 COª가", "⠉⠕⠰⠼⠃"),          # p008 gold CO⠰⠼⠃ (아래첨자 2)
    ("간기 중 GÁ기에는", "⠛⠰⠼⠁⠈⠕"),     # p048 gold G⠰⠼⠁기
    ("생장하며, Gª기에는", "⠛⠰⠼⠃⠈⠕"),   # p048 gold G⠰⠼⠃기
    ("자손 1대(FÁ)에서", "⠋⠰⠼⠁"),       # p174 gold F⠰⠼⠁
    ("질산 이온(NO£Ñ), ㉡은", "⠕⠰⠼⠉⠘⠔"),  # p092 gold NO⠰⠼⠉⠘⠔ (위첨자 −)
    ("않으면 RhÑ형이다", "⠗⠓⠘⠔"),        # p140 gold Rh⠘⠔
])
def test_글꼴_칸_첨자를_복원한다(text, cells):
    assert cells in _b(text)


def test_아래첨자_2가_사라지지_않는다():
    assert _b("이산화 탄소(COª)이다.") != _b("이산화 탄소(CO)이다.")


@pytest.mark.parametrize("text", ["h(x)=(fÁg)(x)", "ESPAÑA 여행", "Álvaro 씨"])
def test_뒤가_라틴_글자면_그대로(text):
    # 수학2 합성함수 칸(정체 미확정)과 스페인어 낱말은 건드리지 않는다
    assert "⠰⠼" not in _b(text) and "⠘⠔" not in _b(text)
