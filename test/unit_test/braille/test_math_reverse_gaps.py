"""수식 역맵 빈칸 — 정답쌍 역방향에서 한글·미해독으로 새던 기호들.

정방향에 기호를 채우면서 **역방향 짝을 안 만든** 자리다.
수식 경로 전용이라 본문 한글과 안 겹친다(⠳ 는 한글 `열` 과 같은 셀이다).

정규부분군 ▷·◁(⠸⠜·⠸⠣)는 뺐다 — 코퍼스 1,180쪽에서 묵자 정답 0건인데 5쪽에 오검출로
떴다. ⠸ 는 도형 접두라 본문에 흔하다.
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


@pytest.mark.parametrize("raw,want", [
    ("⠳⠳⠭⠳⠳", "‖"),            # 노름 (제28항) — 단일 ⠳ 보다 먼저 잡혀야 한다
    ("⠠⠁⠀⠈⠔⠒⠒⠀⠠⠃", "≅"),      # 물결 아래 등호 (제32항)
    ("⠼⠃⠨⠳⠼⠉", "∤"),           # 나누어떨어지지 않음 (제27항)
])
def test_수식_역맵(raw, want):
    assert want in decode(raw, math=True)


def test_절댓값():
    """⠳ 는 절댓값(제21항)이자 한글 `열` 이다 — 수식 경로에서만 기호로 읽는다."""
    assert decode("⠳⠭⠳", math=True).startswith("|")


@pytest.mark.parametrize("text", ["열심히", "열 개"])
def test_본문_한글은_그대로(text):
    assert decode(translate_plain(text)) == text
