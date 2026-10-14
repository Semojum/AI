"""표 칸 원문자 오독 되돌리기 넓히기(#1403) — mineru_runner._restore_lone_circled · _circled_digit_restores.

MinerU 가 표 칸의 원문자를 민 숫자로 읽는다(㉠ → 7, ① → 1, ⓐ → 9). #1210 은 칸 글 앞뒤 문맥으로 글자를 정해, 숫자만 든 칸과
동그라미 숫자 · 로마자는 못 되돌렸다. 시험 표는 2027 dev · val 쪽의 실제 칸 HTML(MinerU 원출력)과 층 글이다.
기대 글자는 층(묵자 원본) 글자다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

BBOX = [0, 0, 1000, 1000]

# 생명과학Ⅰ body p0107: 머리 줄 ㉠ ㉡ ㉢ ㉣ 이 $7$ $8$ $9$ $10$ 으로, 둘째 줄 ⓐ · ⓑ 가 $9$ · $10$ 으로 읽혔다.
SERUM_HTML = (
    "<table><tr><td>시약\\혈장</td><td> $7$ </td><td> $8$ </td><td> $9$ </td><td> $10$ </td></tr><tr><td>A형 적혈구 시약</td>"
    "<td>응집됨</td><td> $9$ </td><td>응집 안 됨</td><td> $10$ </td></tr><tr><td>B형 적혈구 시약</td><td>?</td><td>응집됨</td>"
    "<td>응집됨</td><td>응집 안 됨</td></tr></table>")
SERUM_LAYER = "혈장  ㉠  ㉡  ㉢  ㉣\n시약\nA형 적혈구 시약  응집됨  ⓐ  응집 안 됨  ⓑ\nB형 적혈구 시약 ?  응집됨  응집됨  응집 안 됨"

# 생활과 윤리 body p0077: 행 머리 ① ~ ⑤ 가 1 ~ 5 로 읽혔다. 층은 행 머리 다음에 대답 칸을 먼저 읽는다.
JUSTICE_HTML = (
    "<table><tr><td></td><td>질문</td><td>대답</td></tr><tr><td>1</td><td>공동체의 맥락에 따른 정의의 기준이 필요한가?</td>"
    "<td>예</td></tr><tr><td>2</td><td>영역 간 가치의 자유로운 전환은 분배의 정의를 실현하는가?</td><td>예</td></tr><tr>"
    "<td>3</td><td>서로 다른 사회적 가치는 동일한 기준에 따라 분배되어야 하는가?</td><td>예</td></tr><tr><td>4</td>"
    "<td>사회적 가치는 각각 고유한 분배 영역을 가지는가?</td><td>아니요</td></tr><tr><td>5</td><td>사회적 가치의 다원적 "
    "평등이 실현될 때 정의로 운 사회가 실현되는가?</td><td>아니요</td></tr></table>")
JUSTICE_LAYER = (
    "질문  대답\n①  예\n공동체의 맥락에 따른 정의의 기준이 필요\n한가?\n②  예\n영역 간 가치의 자유로운 전환은 분배의 정\n"
    "의를 실현하는가?\n③  예\n서로 다른 사회적 가치는 동일한 기준에 따\n라 분배되어야 하는가?\n④  아니요\n사회적 가치는 "
    "각각 고유한 분배 영역을 가지\n는가?\n⑤  아니요\n사회적 가치의 다원적 평등이 실현될 때 정의로\n운 사회가 실현되는가?")

# 언어와 매체 body p0055: 머리 줄 ㉠ ㉡ 이 $7$ $8$ 로, 행 머리 ① ~ ⑤ 가 1 ~ 5 로 읽혔다(두 갈래가 한 표에).
SOUND_HTML = (
    "<table><tr><td></td><td> $7$ </td><td> $8$ </td></tr><tr><td>1</td><td>군이[구지]</td><td>솔잎[솔립]</td></tr><tr>"
    "<td>2</td><td>만형[마팅]</td><td>꺼안다[꺼안파]</td></tr><tr><td>3</td><td>걸옷[거돈]</td><td>한여름[한녀름]</td></tr>"
    "<tr><td>4</td><td>쌍이다[싸이다]</td><td>낮설다[난WWW]</td></tr><tr><td>5</td><td>넓적하다[넘찌카다]</td>"
    "<td>백분율[백뿐놀]</td></tr></table>")
SOUND_LAYER = ("㉠  ㉡\n①  굳이[구지]  솔잎[솔립]\n②  맏형[마텽]  껴안다[껴안따]\n③  겉옷[거돋]  한여름[한녀름]\n"
               "④  쌓이다[싸이다]  낯설다[낟썰다]\n⑤  넓적하다[넙쩌카다]  백분율[백뿐뉼]")

# 혈액형 표(#1210 시험의 생명과학Ⅰ body p0100): 숫자만 든 칸 60 · 59 · 16 은 층에 수로 찍혀 있다. 진짜 수다.
BLOOD_HTML = (
    "<table><tr><td>구분</td><td>사람 수</td></tr><tr><td>7이 있는 사람</td><td>60</td></tr><tr><td>8이 있는 사람</td>"
    "<td>59</td></tr><tr><td>9과 10이 모두 없는 사람</td><td>16</td></tr></table>")
BLOOD_LAYER = "구분  사람 수\n㉠이 있는 사람  60\n㉡이 있는 사람  59\nⓐ <!강조>㉠과 ㉡이 모두 없는 사람<!/강조>  16"


@pytest.fixture
def layer(monkeypatch):
    """층 글을 원하는 문자열로 고정한다(PDF 없이). 스위치는 기본(켬)에서 시작한다."""
    for k in ("TABLE_CELL_LONE_CIRCLED", "TABLE_CELL_CIRCLED_ANY", "TABLE_CELL_CIRCLED_DIGIT"):
        monkeypatch.delenv(k, raising=False)

    def _set(text):
        monkeypatch.setattr(MR, "_native_text_pair", lambda page, bb, skip_math=False: (text, text))
    return _set


def test_숫자만_든_머리_줄을_층의_원문자로_차례대로_되돌린다(layer, monkeypatch):
    layer(SERUM_LAYER)
    fixes = []
    out = MR._restore_lone_circled(None, BBOX, SERUM_HTML, fixes=fixes)
    assert "<td> ㉠ </td><td> ㉡ </td><td> ㉢ </td><td> ㉣ </td>" in out
    assert "<td>응집됨</td><td> ⓐ </td><td>응집 안 됨</td><td> ⓑ </td>" in out
    assert "$" not in out and fixes == ["{10→ⓑ}", "{9→ⓐ}", "{10→㉣}", "{9→㉢}", "{8→㉡}", "{7→㉠}"]
    monkeypatch.setenv("TABLE_CELL_LONE_CIRCLED", "0")
    assert MR._restore_lone_circled(None, BBOX, SERUM_HTML) == SERUM_HTML           # 종전


def test_행_머리_숫자는_값으로_동그라미_숫자를_되돌린다(layer, monkeypatch):
    layer(JUSTICE_LAYER)
    out = MR._restore_lone_circled(None, BBOX, JUSTICE_HTML)
    assert all(f"<td>{c}</td>" in out for c in "①②③④⑤") and "<td>1</td>" not in out
    monkeypatch.setenv("TABLE_CELL_CIRCLED_ANY", "0")                                # 동그라미 한글만 보던 종전
    assert MR._restore_lone_circled(None, BBOX, JUSTICE_HTML) == JUSTICE_HTML


def test_한_표에_두_갈래가_섞여도_갈래마다_맞춘다(layer):
    layer(SOUND_LAYER)
    out = MR._restore_lone_circled(None, BBOX, SOUND_HTML)
    assert "<td></td><td> ㉠ </td><td> ㉡ </td>" in out
    assert all(f"<td>{c}</td>" in out for c in "①②③④⑤")


def test_층에_수로_찍힌_숫자는_되돌리지_않는다(layer):
    layer(BLOOD_LAYER)
    assert MR._restore_lone_circled(None, BBOX, BLOOD_HTML) == BLOOD_HTML


def test_개수가_안_맞으면_차례로_되돌리지_않는다(layer):
    layer(SERUM_LAYER.replace("ⓑ", ""))                                              # 층 원문자 5 · 숫자 칸 6
    assert MR._restore_lone_circled(None, BBOX, SERUM_HTML) == SERUM_HTML


def test_칸_글_속_숫자도_동그라미_로마자로_되돌린다(layer):
    html = "<table><tr><td>•아기를 품에 1안다.</td></tr><tr><td>•그 일에 대해 2안다.</td></tr></table>"
    layer("•아기를 품에 ⓐ안다.\n•그 일에 대해 ⓑ안다.")
    out = MR._correct_table_cells(None, BBOX, html)
    assert "ⓐ안다." in out and "ⓑ안다." in out
