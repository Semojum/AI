"""페이지행 걸침 접두 알파벳 — 지침 1장2절2-2(3).

원본 한 쪽이 여러 점자 면에 걸치면 두 번째 면부터 원본 쪽 번호 앞에 로마자표 없이
a·b·c… 를 적는다(braille-assist `_alpha` 와 대칭). 종전에는 이 낱자가 어느 표에도 없어
`⟨2803⟩4` 로 샜다 — 코퍼스 1,500쪽 표본에서 2,467건으로 미지셀 1위였다.
"""
import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("cells,expect", [
    ("⠁⠼⠙", "a4"),
    ("⠃⠼⠙", "b4"),
    ("⠉⠼⠁⠚", "c10"),
])
def test_걸침_접두를_읽는다(cells, expect):
    assert decode(cells) == expect


def test_접두_없는_쪽번호는_그대로():
    assert decode("⠼⠙") == "4"


def test_한글_토큰을_가로채지_않는다():
    # `운6기` = ⠛⠼⠋⠈⠕ — ⠛ 는 낱자 g 와 같은 셀이지만 토큰이 숫자로 안 끝난다.
    assert decode("⠛⠼⠋⠈⠕") == "운6기"


def test_숫자_셀은_연속_범위가_아니다():
    # `[⠁-⠚]` 로 쓰면 ⠈·⠕ 가 들어와 위 케이스가 깨진다. 명시 집합이어야 한다.
    from app.utils.braille_back import _CONT_PREFIX_RE
    assert not _CONT_PREFIX_RE.fullmatch("⠛⠼⠋⠈⠕")
