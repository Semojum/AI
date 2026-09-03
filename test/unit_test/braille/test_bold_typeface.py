"""굵은 글자체표 — 규정 제56항.

제56항은 강조를 두 갈래로 적는다.
· 드러냄표·밑줄 → `,-` … `-'` (⠠⠤ … ⠤⠄)
· 굵은 글자     → `;-` … `-2` (⠰⠤ … ⠤⠆)

역맵에 굵은 쪽이 없어 뜻 없는 ASCII 가 새어 나갔다(`_-어제도-;`).
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


def test_굵은_글자체표를_벗긴다():
    raw = "⠀⠀⠰⠤⠎⠨⠝⠊⠥⠤⠆⠀⠚⠐⠍⠄⠘⠢"
    assert decode(raw) == "  어제도 하룻밤"


@pytest.mark.parametrize("text", ["고복지-저부담", "(가)와 (나)", "근대화(1)"])
def test_붙임표_괄호_비회귀(text):
    """⠤ 는 붙임표와 같은 셀이다 — 짝일 때만 벗기므로 안 깨진다."""
    assert decode(translate_plain(text)) == text


def test_한글표를_벗긴다():
    """제39항 — 수식 안 한글은 한글표 ⠸⠷ … 한글 종료표 ⠸⠾ 으로 묶는다.

    역맵에 없어 `(㉠)+(㉢)=` 가
    `⟨2838⟩온㉠⟨2838⟩언+⟨2838⟩온㉢⟨2838⟩언=` 로 풀렸다.
    """
    raw = "⠀⠀⠦⠄⠴⠠⠭⠠⠴⠿⠁⠲⠀⠸⠷⠶⠿⠁⠶⠸⠾⠢⠸⠷⠶⠿⠔⠶⠸⠾⠒⠒"
    assert decode(raw) == "  (X)ㄱ. ㉠+㉢="


@pytest.mark.parametrize("raw,want", [
    ("⠴⠠⠝⠁⠘⠢", "Na^+"),      # 화학 이온 — ⠘⠢ 가 한글 `밤` 과 같은 셀이다
    ("⠴⠠⠅⠘⠢", "K^+"),
])
def test_로마자_런_안_위첨자(raw, want):
    assert decode(raw) == want


@pytest.mark.parametrize("text", ["밤에", "바람", "pH 농도"])
def test_한글_초성_ㅂ_비회귀(text):
    """⠘ 는 한글 초성 ㅂ 이기도 하다 — 로마자 런 안에서만 위첨자로 읽는다."""
    assert decode(translate_plain(text)) == text


@pytest.mark.parametrize("text", [
    "전쟁(1840)",
    "제1차 아편전쟁(1840~1842)",
    "청프전쟁(1884~1885)",
    "조약(1842)",
    "전쟁(가)",
])
def test_한글_뒤_괄호_숫자가_수식으로_안_빠진다(text):
    """닫는 묶음 괄호 ⠾ 는 한글 `전`(⠨⠾)과 겹친다.

    수표 + ⠾ 만으로 MATH 로 분류돼 `전쟁(1840)` 이 `전ρ{(1840)` 으로 깨졌다.
    묶음 괄호는 짝으로 오므로 여는 ⠷ 를 요구한다.
    """
    assert decode(translate_plain(text)) == text
