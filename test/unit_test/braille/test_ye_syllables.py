"""자음+ㅖ 음절이 받침 ㅆ로 읽히던 것.

⠌ 는 ㅖ(규정 제7항)이자 **받침 ㅆ**(제4항)이라 역맵이 받침 쪽으로 기울었다.
어느 쪽으로 펼지는 실측으로 정한다 — 재추출 묵자 1,361쪽:
    혜 206 : 핬 0   ·   뎨 1 : 닸 0     → ㅖ 로 편다
    났 241 : 녜 2   ·   맜 1 : 몌 0     → 현행(받침)이 옳다
둘 다 0인 음절(볘·졔·톄 등)은 근거가 없어 건드리지 않는다.
"""
import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("cells,expect", [("⠚⠌", "혜"), ("⠊⠌", "뎨")])
def test_실측_우세한_ㅖ_음절(cells, expect):
    assert decode(cells) == expect


def test_이름과_낱말():
    assert decode("⠩⠒⠚⠌⠨⠻") == "윤혜정"
    assert decode("⠨⠕⠚⠌") == "지혜"


def test_받침이_우세한_자리는_안_건드린다():
    # 났 241 : 녜 2 — 뒤집으면 흔한 말이 깨진다.
    assert decode("⠉⠌") == "났"


def test_받침_ㅆ_문장은_그대로():
    assert "났다" in decode("⠉⠌⠊")
