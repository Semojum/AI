"""단독 자음자 역점역 — 「한글 점자」 제10항.

"단독으로 쓰인 자음자가 단어에 붙어 나올 때에는 _을 앞세워 받침으로 적는다"
(재추출본 520~521행). ⠸⠂ 가 UEB 밑줄 낱말표와 점형이 같아 통째로 지워지고 있었다.
"""
import pytest

from app.utils.braille_back import decode


@pytest.mark.parametrize("cells, want", [
    # 규정 예문 523~528행
    ("⠴⠠⠗⠕⠍⠁⠲ ⠦⠆⠸⠂⠸⠂⠐⠥⠑⠰⠴", "Roma [ㄹㄹ로마]"),      # Roma [ㄹㄹ로마]
    ("⠦⠆⠠⠫⠸⠂⠸⠂⠐⠥⠰⠴", "[까ㄹㄹ로]"),                     # carro [까ㄹㄹ로]
    ("⠦⠆⠘⠿⠨⠍⠸⠂⠚⠪⠰⠴", "[봉주ㄹ흐]"),                     # bonjour [봉주ㄹ흐]
])
def test_제10항_단독_자음자(cells, want):
    assert decode(cells) == want


@pytest.mark.parametrize("cells", [
    "⠸⠂⠎⠁⠙",          # UEB 밑줄 낱말표 + sad
    "⠸⠂⠋⠗⠑⠑",         # 〃 + free
])
def test_UEB_밑줄_낱말표는_그대로_뗀다(cells):
    assert "ㄹ" not in decode(cells)


def test_중세국어_방점은_안_건드린다():
    # 나랏말ᄊᆞ미 (EBS-E26-004 p0035) — 아래아가 있으면 제27항 거성 방점이다.
    cells = "⠉⠸⠂⠐⠣⠄⠸⠅⠑⠂⠠⠠⠐⠼⠸⠂⠑⠕"
    assert "ㄹ" not in decode(cells)
