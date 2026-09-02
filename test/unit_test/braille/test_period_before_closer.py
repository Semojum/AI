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


def test_단독_셀은_기호로_둔다():
    # 앞에 텍스트가 없으면 마침표가 아니다 — 종전 동작을 지킨다.
    assert decode("⠲") == "∋"
