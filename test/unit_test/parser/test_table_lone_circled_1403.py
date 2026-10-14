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


# 화법과 작문 body p0050: 묻는 말 머리 ㉮ · ㉯ 가 7 · 14 로 읽혔다. #1210 이 ㉮ 를 되돌리던 자리다. 1판은 칸 창 맞추기까지 갈래를
# 넓혀 창이 옮겨 이걸 놓쳤다. 두 자리 수 14 ↔ ㉯ 는 #1403 부터 되돌린다.
TALK_HTML = (
    '<table><tr><td rowspan="2">1</td><td>7:반상 차림에 활용되는 식재료로 보통 어떤 식재료를 활용했나요?</td></tr><tr><td>14:조선 시대에 좌식 생활을 했던'
    ' 이유는 무엇인가요?</td></tr><tr><td rowspan="2">2</td><td>7:반상 문화에는 선조들의 어떤 가치관이 투영된 것일까요?</td></tr><tr><td>14:조선 시대에'
    ' 검상보다 독상이 사용된 또 다른 이유로는 무엇이 있을까요?</td></tr><tr><td rowspan="2">3</td><td>7:반상 문화를 현대적 관점에서 계승하기 위해서는 어떤 변화가 필요'
    '할까요?</td></tr><tr><td>14:반상 문화가 정착된 이유로 조선 시대 유교 문화의 영향이 있다고 보시나요?</td></tr><tr><td rowspan="2">4</td><td>7:반상'
    ' 문화와 서구식 음식 문화 사이에는 어떤 공통점과 차이점이 있을까요?</td></tr><tr><td>14:오늘날 독상보다 검상을 많이 차리는 이유는 무엇이라고 생각하시나요?</td></tr><tr>'
    '<td rowspan="2">5</td><td>7:조선 시대 반상 문화를 모든 계층에서 볼 수 있는 보편적인 문화로 볼 수 있을까요?</td></tr><tr><td>14:1인 가구가 늘고 있는 오늘'
    '날의 상황에 독상 문화가 적합하다고 생각하나요?</td></tr></table>')
TALK_LAYER = (
    '①\n㉮: 반상 차림에 활용되는 식재료로 보통 어떤 식재료를 활용했나요?\n㉯: 조선 시대에 좌식 생활을 했던 이유는 무엇인가요?\n②\n㉮: 반상 문화에는 선조들의 어떤 가치관이 투영된 것일까요?\n㉯: '
    '조선 시대에 겸상보다 독상이 사용된 또 다른 이유로는 무엇이 있을까요?\n③\n㉮: 반상 문화를 현대적 관점에서 계승하기 위해서는 어떤 변화가 필요할까요?\n㉯: 반상 문화가 정착된 이유로 조선 시대 유'
    '교 문화의 영향이 있다고 보시나요?\n④\n㉮: 반상 문화와 서구식 음식 문화 사이에는 어떤 공통점과 차이점이 있을까요?\n㉯: 오늘날 독상보다 겸상을 많이 차리는 이유는 무엇이라고 생각하시나요?\n⑤\n<'
    '!강조>㉮: 조선 시대 반상 문화를 모든 계층에서 볼 수 있는 보편적인 문화로 볼 수 있을까요?<!/강조>\n㉯: 1인 가구가 늘고 있는 오늘날의 상황에 독상 문화가 적합하다고 생각하나요?')

# 수학Ⅰ ans p0008 빠른 정답 표: 층은 `1 ②  2 ③ … 10 2`. 칸 `10 2` 의 0 이 숫자뿐인 문맥 `1` · `2` 로 ② 에 들어맞아
# `1② 2` 가 됐고(#1403 1판), 그 바람에 경계 단계의 정답 표지 되돌리기가 표째 빠졌다.
ANSWER_HTML = (
    '<table><tr><td colspan="6">유제</td><td>본문 21~29쪽</td></tr><tr><td>1 2</td><td>2 3</td><td>3 5</td><td>4 4</td><td>5 4</td>'
    "<td>6 2</td><td></td></tr><tr><td>7 2</td><td>8 4</td><td>9 3</td><td>10 2</td><td></td><td></td><td></td></tr></table>")
ANSWER_LAYER = "1 ②  2 ③  3 ⑤  4 ④  5 ④  6 ②\n7 ②  8 ④  9 ③  10 2\n유제  본문 21~29쪽"


def test_종전에_되돌리던_동그라미_한글은_그대로_두_자리_수도_되돌린다(layer):
    layer(TALK_LAYER)
    out = MR._correct_table_cells(None, BBOX, TALK_HTML)
    assert "<td>㉮:반상 차림에" in out and "<td>㉯:조선 시대에 좌식" in out


def test_숫자뿐인_문맥으로는_원문자를_넣지_않는다(layer):
    layer(ANSWER_LAYER)
    html = MR._correct_table_cells(None, BBOX, ANSWER_HTML)
    assert "<td>10 2</td>" in html and "<td>1 2</td>" in html
    assert MR._restore_lone_circled(None, BBOX, html) == html                       # `1 2` 는 두 수라 숫자만 든 칸이 아니다


# 014 body p0010: 층 `➊ 주장하기` 가 칸 `1 주장하기` 로 읽혔다. ➀~➓(U+2780~2793)는 번역기가 못 찍고 통째로 빼서(`➊ 가` → `⠫`),
# 되돌리면 번호가 점자에서 사라진다(#1403 2판 손해). 그 갈래는 되돌리지 않는다. 번역기가 찍는 ❶~❿ 은 그대로 되돌린다.
ARGUE_HTML = (
    "<table><tr><td>1 주장하기</td><td>자신의 주장에 대한 근거를 찾고 자신의 주장을 발표함</td></tr><tr><td>2 반론하기</td>"
    "<td>상대방 주장의 오류나 부당성을 밝힘</td></tr><tr><td>3 재반론하기</td><td>상대방의 반론이 옮지 않음을 밝히거나 자기주장을 "
    "뒷받침할 만한 더 많은 근거를 제시함</td></tr><tr><td>4 정리하기</td><td>상대방의 반론을 참고하여 자신의 최종 입장을 발표함</td></tr></table>")
ARGUE_LAYER = (
    "➊ 주장하기  자신의 주장에 대한 근거를 찾고 자신의 주장을 발표함\n➋ 반론하기  상대방 주장의 오류나 부당성을 밝힘\n"
    "➌ 재반론하기  상대방의 반론이 옳지 않음을 밝히거나 자기주장을 뒷받침할 만한 더 많은 근거를 제시함\n"
    "➍ 정리하기  상대방의 반론을 참고하여 자신의 최종 입장을 발표함")


def _both(html):
    return MR._restore_lone_circled(None, BBOX, MR._correct_table_cells(None, BBOX, html))


def test_번역기가_못_찍는_원문자로는_되돌리지_않는다(layer):
    layer(ARGUE_LAYER)
    out = _both(ARGUE_HTML)
    assert "<td>1 주장하기</td>" in out and "<td>4 정리하기</td>" in out
    assert not set(out) & {chr(c) for c in range(0x2780, 0x2794)}


def test_번역기가_찍는_검은_원문자는_그대로_되돌린다(layer):
    layer(ARGUE_LAYER.translate({0x278A + k: 0x2776 + k for k in range(10)}))   # ➊ → ❶ 같은 표
    out = _both(ARGUE_HTML)
    assert "<td>❶ 주장하기</td>" in out and "<td>❹ 정리하기</td>" in out
