"""마침표 뒤에 닫는 부호가 오면 ⠲ 를 ∋ 로 읽던 것.

⠲ 는 마침표이자 집합 기호 ∋ 다(규정). 종전에는 **끝·공백 앞**일 때만 마침표로 봐서,
마침표 바로 뒤에 점역자 주표나 닫는 괄호가 오면 ∋ 로 샜다.
근거: 재추출 묵자 1,361쪽에 마침표 29,887회 · ∋ 0회.
"""
import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("cells,tail", [
    ("⠘⠕⠈⠍⠫⠡⠢⠲⠠⠄", "."),      # 마침표 + 점역자 주표
    ("⠘⠕⠈⠍⠫⠡⠢⠲⠠⠴", "."),      # 마침표 + 닫는 소괄호
])
def test_닫는_부호_앞의_마침표(cells, tail):
    d = decode(cells)
    assert "∋" not in d
    assert tail in d


def test_끝과_공백_앞은_종전대로():
    assert decode("⠘⠕⠈⠍⠫⠡⠢⠲").endswith(".")


def test_단독_셀도_마침표다():
    """★ 2026-09-03 뒤집었다 — 종전에는 단독 ⠲ 를 ∋ 로 뒀다.

    같은 근거가 단독 셀에도 그대로 걸린다. 전 코퍼스 1,180쪽 실측에서 ∋ 가
    **171쪽**의 출력에 떴는데 그 쪽 묵자에 ∋ 는 **0건**이다(LaTeX `\ni` 까지 찾은 값).
    ∋ 를 본문 역맵에서 빼면 이 자리가 마침표로 떨어진다.
    """
    assert decode("⠲") == "."
