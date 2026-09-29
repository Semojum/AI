"""원장 C-41 부록3 — 수량 표기는 문항 번호가 아니다(문항 번호 마침표 `_QNUM_RE` 오발동).

규정 제44항 "숫자 뒤에 이어 나오는 한글의 띄어쓰기는 묵자를 따른다" 예문 `5 개`·`8 상자`,
제69항 [붙임 1·2] 예문 `1 μm는`·`5 %와`. 기대값은 규정 원문 BRF(백틱 = 빈칸)에서 옮겼다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _b(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def test_제44항_숫자_빈칸_단위명사는_묵자대로():
    assert _b("5 개") == ascii_to_unicode("#e`@r", backtick="space")      # ⠼⠑⠀⠈⠗
    assert _b("8 상자") == ascii_to_unicode("#h`l7.", backtick="space")   # ⠼⠓⠀⠇⠶⠨


def test_제69항_단위기호_앞_숫자에_마침표를_안_붙인다():
    # 규정 `#e`0p`v…` = ⠼⠑⠀⠴⠏⠀⠧ — 번호 마침표 ⠲ 가 없다.
    assert _b("5 %와 6 %의 차이는 1 %p다.").startswith("⠼⠑⠀⠴⠏⠀⠧")
    assert not _b("1 μm는 1,000분의 1 mm이다.").startswith("⠼⠁⠲")


def test_단위명사와_글자가_같은_문항_번호는_그대로():
    # 명나라 단원 소제목(gold 온점, 주자 val 3곳) — 단위 명사 목록으로 넓게 끄면 이게 깨진다.
    assert _b("4 명의 건국과 동아시아 질서의 재편").startswith("⠼⠙⠲")
    assert _b("2 다음은 어느 학생의 필기 내용이다.").startswith("⠼⠃⠲")
