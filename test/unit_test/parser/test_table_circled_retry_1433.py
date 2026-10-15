"""표 칸 원문자 되돌리기가 막히던 자리(#1433) — mineru_runner._correct_table_cells.

짧은 칸 `1 (가)` 은 층 `① (가)` 와 한 글자 달라 창 문턱에서 빠지고, 긴 칸 하나만 층에서 갈려도 칸을 버린 표가 되어
원문자 되돌리기가 막혔다. 떨어진 칸만 숫자 ↔ 원문자를 같게 보고 창을 다시 찾고, 막히던 문맥 되돌리기는 이웃에 숫자 아닌
글자가 있고 칸의 자리가 전부 정해질 때만 통과시킨다. 시험 표는 실제 MinerU 칸 HTML 과 그 자리 층 글이다(V2 temp/n364/fixtures_1433.json).
기대 글자는 층(묵자 원본) 글자다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

BBOX = [0, 0, 1000, 1000]

# 세계사 본문 161쪽 연표 문항: 선지 칸 ①~⑤ 가 1~5 로 읽혔다. `러일 전쟁발발` 같은 칸은 층에서 두 줄로 갈려 버려진다.
WORLD_HTML = (
    "<table><tr><td></td><td>(가)</td><td>(나)</td><td>(다)</td><td>(라)</td><td>(마)</td><td></td></tr><tr><td>러일 전쟁발발</td>"
    "<td>제1차 세계대전 발발</td><td>러시아,제정 붕괴</td><td>국제 연맹창설</td><td>레닌사망</td><td colspan=\"2\">독소 불가침조약 체결</td>"
    "</tr><tr><td>1 (가)</td><td>2 (나)</td><td>3 (다)</td><td>4 (라)</td><td colspan=\"3\">5 (마)</td></tr></table>")
WORLD_LAYER = ("(가)  (나)  (다)  (라)  (마)\n러일 전쟁  제1차 세계  러시아,  국제 연맹  레닌  독소 불가침\n"
               "발발  대전 발발  제정 붕괴  창설  사망  조약 체결\n① (가)  ② (나)  ③ (다)  ④ (라)  ⑤ (마)")

# 생명과학 본문 187쪽: `1000` · `8000` 은 진짜 수다(층 `생산자  1000  8000`).
ENERGY_HTML = (
    "<table><tr><td>영양 단계</td><td>에너지양(상,\n\n(a)</td><td>(나)</td></tr><tr><td> $\\textcircled{7}$ </td><td>a</td>"
    "<td>400</td></tr><tr><td> $\\textcircled{L}$ </td><td>?</td><td>12</td></tr><tr><td> $\\textcircled{C}$ </td><td>30</td>"
    "<td>b</td></tr><tr><td>생산자</td><td>1000</td><td>8000</td></tr></table>")
ENERGY_LAYER = "영양 단계\n에너지양(상댓값)\n(가)  (나)\n㉠  ⓐ  400\n㉡ ?  12\n㉢  30  ⓑ\n생산자  1000  8000"

# 언어와 매체 본문 60쪽: 단어 구조 칸 `$7 + (7 + 7)$` ↔ 층 `㉡+(㉠+㉢)`. 문맥 `+` 로는 셋 중 하나만 정해진다.
WORD_HTML = (
    "<table><tr><td></td><td>단어</td><td>단어의 구조</td></tr><tr><td>1</td><td>하늘</td><td> $7$ </td></tr><tr><td>2</td>"
    "<td>논밥</td><td> $7 + 7$ </td></tr><tr><td>3</td><td>울보</td><td> $7 + 7$ </td></tr><tr><td>4</td><td>코옷음</td>"
    "<td> $7 + (7 + 7)$ </td></tr><tr><td>5</td><td>짓 Delhi</td><td> $(7 + 7) + 7$ </td></tr></table>")
WORD_LAYER = "단어  단어의 구조\n①  하늘  ㉠\n②  논밭  ㉠+㉠\n③  울보  ㉠+㉢\n④  코웃음  ㉡+(㉠+㉢)\n⑤  짓밟히다  (㉡+㉠)+㉢"


@pytest.fixture
def layer(monkeypatch):
    """층 글을 원하는 문자열로 고정한다(PDF 없이)."""
    for k in ("TABLE_CELL_CIRCLED_DIGIT", "TABLE_CELL_CIRCLED_ANY", "TABLE_CELL_SPLIT", "TABLE_CELL_PIECES"):
        monkeypatch.delenv(k, raising=False)

    def _set(text):
        monkeypatch.setattr(MR, "_native_text_pair", lambda page, bb, skip_math=False, italic=False: (text, text))
    return _set


def test_짧은_칸과_칸을_버린_표에서도_원숫자를_되돌린다(layer):
    layer(WORLD_LAYER)
    fixes: list[str] = []
    out = MR._correct_table_cells(None, BBOX, WORLD_HTML, fixes=fixes)
    for n, mark in enumerate("①②③④", 1):
        assert f"<td>{mark} ({'가나다라'[n - 1]})</td>" in out
    assert '<td colspan="3">⑤ (마)</td>' in out
    assert "<td>러일 전쟁발발</td>" in out                       # 버린 칸은 그대로
    assert len(fixes) == 5                                        # 고친 자리는 R4 '고침' 표지로 남는다


def test_이웃이_숫자뿐인_진짜_수는_안_바꾼다(layer):
    layer(ENERGY_LAYER)
    out = MR._correct_table_cells(None, BBOX, ENERGY_HTML, fixes=[])
    assert "<td>1000</td>" in out and "<td>8000</td>" in out


def test_칸의_자리가_다_정해지지_않으면_안_바꾼다(layer):
    layer(WORD_LAYER)
    out = MR._correct_table_cells(None, BBOX, WORD_HTML, fixes=[])
    assert "<td> $7 + (7 + 7)$ </td>" in out and "<td> $(7 + 7) + 7$ </td>" in out
