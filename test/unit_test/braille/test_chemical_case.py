"""화학식 대소문자 — 과학 점자 제2항.

규정은 화학식을 원소마다 대문자표(`,h` = ⠠⠓)로 적는데, 수식 디코더가 ⠠ 를 흘려
소문자로 냈다. 한 글자 꼴은 수학 변수가 대부분이라 건드리지 않는다.
"""
import pytest

from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


@pytest.mark.parametrize("raw,want", [
    ("⠠⠎⠠⠕⠰⠼⠙⠘⠼⠃⠔", "SO_4^2-"),
    ("⠠⠉⠠⠕⠰⠼⠃", "CO_2"),
    ("⠠⠝⠠⠓⠰⠼⠉", "NH_3"),
])
def test_원소_조합은_대문자(raw, want):
    assert decode(raw) == want


@pytest.mark.parametrize("raw,want", [
    ("⠠⠓⠰⠼⠃⠠⠕", "H_2O"),                 # 과학 제4항 [붙임 1] — 첨자 뒤에도 원소가 온다
    ("⠼⠋⠠⠓⠰⠼⠃⠠⠕", "6H_2O"),
    ("⠴⠠⠎⠠⠕⠰⠼⠙⠘⠼⠃⠔", "SO_4^2-"),        # 과학 제2항 — 이온 전하
])
def test_첨자_뒤_원소도_대문자(raw, want):
    """⠠⠕ 는 한글 `소` 로도 읽혀 한글 꼬리 가드에 걸렸다 — 첨자 숫자 뒤로 한정해 살린다.

    로마자표로 연 런에서는 위첨자표 ⠘ 에서 끊겨 `SO_4바2-` 로 나갔다.
    실측(전권 18,892쪽): 바뀐 쪽 34 · 한글 늘어난 조각 0.
    """
    assert decode(raw) == want


@pytest.mark.parametrize("text", ["t_1 구간", "z_1 값"])
def test_한_글자는_변수라_그대로(text):
    """실측 3,332건 중 묵자가 소문자인 것이 1,707 로 더 많다 — 건드리면 나빠진다."""
    assert "_1" in decode(translate_plain(text)).lower()
    assert "T_1" not in decode(translate_plain(text))


@pytest.mark.parametrize("text", ["응이 있다", "반응이 일어난다", "대응이"])
def test_가역_화살표_셀은_한글이다(text):
    """⇄(⠪⠶⠕, 제61항)는 한글 `응이` 와 같은 셀이다.

    실측(전 코퍼스 1,131쪽): 이 셀 404건 · 230쪽 중 묵자에 `⇄` 가 있는 쪽 0,
    `응이` 가 있는 쪽 29. 코퍼스에 화학 가역 반응식이 아예 없다.
    """
    assert decode(translate_plain(text)) == text


@pytest.mark.parametrize("raw,want", [
    ("⠨⠍", "주"), ("⠨⠹", "적"), ("⠨⠗", "재"),
])
def test_그리스_규정_판본은_본문에서_한글(raw, want):
    """book 모드 정방향은 ⠈ 판본만 낸다 — ⠨ 판본은 읽을 일이 없고 전부 흔한 한글이다.

    실측(전 코퍼스 1,131쪽): ⠨⠍ 10,183건 · ⠨⠹ 8,539 · ⠨⠝ 8,283 출현인데
    그 쪽 묵자에 해당 그리스 문자가 있는 것은 전부 0건.
    """
    assert decode(raw) == want


def test_그리스는_수식_경로에서_살아_있다():
    """수식 토큰 안에서는 ⠨ 판본이 실제로 쓰인다 — 왕복 데이터셋도 그걸 지킨다."""
    assert decode("⠨⠍", math=True) == "μ"
