"""영문 지문의 점456 첫글자 약자가 미해독으로 새던 문제 (2026-09-06, #575).

규정 제29항 [다만](`한국 점자 규정_재추출.txt` 1507행)이 문단 전체가 로마자일 때
로마자표·종료표를 생략하게 해서, 영어 교재의 영문 단락에는 단서 셀 ⠴ 가 없다.
`_english_line` 이 그 줄을 영어로 못 가르면 한글 디코더로 넘어가는데 거기에 ⠸ 를
아는 표가 없어 `⠸⠓`(had)가 `⟨2838⟩타`(미해독 ⠸ + ⠓ 를 한글로 오독)로 갈라졌다.

읽는 근거는 제7항(97~100행)·제32항(1650행)이 「통일영어점자 규정」을 준용하는 것이고,
이 여섯은 제37항(1795~1866행)의 "풀어 적는" 목록에 없어 약자 그대로 적는다.
"""
import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("cells,word", [
    ("⠸⠓", "had"),
    ("⠸⠮", "their"),
    ("⠸⠉", "cannot"),
    ("⠸⠍", "many"),
    ("⠸⠺", "world"),
])
def test_점456_첫글자_약자가_미해독으로_안_샌다(cells, word):
    # 한글 디코더로 떨어지는 자리를 그대로 재현한다(로마자표 없는 영문 줄).
    got = decode(f"⠠⠱⠢⠀⠠⠊⠀{cells}⠀⠁⠀⠛⠜⠙⠢")
    assert "⟨2838⟩" not in got
    assert word in got


def test_한글_음절_것은_영어로_안_뒤집힌다():
    """⠸⠎ 는 EBAE `spirit` 과 점형이 같지만 한글 음절 **'것'** 이다.

    전권 18,892쪽에 53,197건·12,354쪽으로 나오는 자리라 뒤집히면 손해가 크다.
    `_COMBINED` 가 먼저 잡고, 표에서도 `spirit` 을 빼 두 겹으로 막는다.
    """
    from app.utils.braille_back import _ENG_456

    assert "⠸⠎" not in _ENG_456
    assert "것은" in decode("⠘⠾⠠⠕⠁⠚⠉⠵⠀⠸⠎⠵⠀⠠⠗⠶⠠⠕⠁⠈⠧")
