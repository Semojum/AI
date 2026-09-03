"""제23·27·28·30·31항 — 정답쌍 대조에서 나온 기호 빠짐.

밑줄은 규정이 `,-`(⠠⠤)이라고 못박는데 우리는 아무것도 안 냈다.
나눗셈 기호는 규정 예시에 칸이 없는데 우리는 앞뒤를 띄웠다.
"""
import pytest

from app.ai.braille import translator as _t  # noqa: F401 — \text{한글} 훅 등록
from app.ai.braille.kor_math_rules import convert_latex


def _b(t: str) -> str:
    return convert_latex(t).strip()


@pytest.mark.parametrize("tex,want", [
    (r"4 \mid 8", "⠼⠙⠳⠼⠓"),        # 제27항 — 앞뒤를 붙인다
    (r"-5 \mid n", "⠔⠼⠑⠳⠝"),
    (r"2 \nmid 3", "⠼⠃⠨⠳⠼⠉"),
    (r"p \nmid n", "⠏⠨⠳⠝"),
])
def test_나누어떨어짐(tex, want):
    assert _b(tex) == want


def test_노름():
    """제28항 — ‖ 는 수직바 둘. 여는 쪽이 절댓값 처리로 새면 닫는 쪽만 노름이 된다."""
    assert _b(r"\|x\|") == "⠳⠳⠭⠳⠳"
    assert _b(r"|x|") == "⠳⠭⠳"      # 절댓값은 그대로 하나


@pytest.mark.parametrize("tex,want", [
    (r"f \simeq g", "⠋⠀⠈⠔⠒⠀⠛"),                   # 제31항
    (r"A/G \approxeq B", "⠠⠁⠸⠌⠠⠛⠀⠈⠔⠈⠔⠒⠀⠠⠃"),      # 제30항
])
def test_물결_아래_한_줄(tex, want):
    assert _b(tex) == want


def test_밑줄():
    """제23항 2호 — `밑줄( )은 ,-으로 적는다`. 본문 뒤에 붙인다."""
    assert _b(r"\underline{X}") == "⠠⠭⠠⠤"
    assert _b(r"\overline{AB}") == "⠈⠉⠠⠠⠁⠃"      # 가로바는 앞에(제23항 1호)
