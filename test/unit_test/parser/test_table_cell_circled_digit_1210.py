"""표 칸 ㉠ → 민 숫자 되돌리기(#1210) — mineru_runner._correct_table_cells.

MinerU 가 표 칸의 동그라미 한글을 민 숫자로 읽는다(㉠ → 7 · 1 · 8 …). 칸 ↔ 층 창에서 숫자 한 글자가 층의 동그라미
한글 한 글자와 같은 자리에 서고, 앞뒤 글자로 그 글자가 하나로 정해질 때만 되돌린다. 시험 표는 #1148 탐침이 기록한
실제 칸 HTML(MinerU)과 층 글이다(V2 temp/n136/cells_EBS-E26-*_on.jsonl). 기대 글자는 층(묵자 원본) 글자다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

BBOX = [0, 0, 1000, 1000]

# 화법과 작문 body p0064 표 0: 설득 전략 ㉠ · ㉡ · ㉢ 이 7 · 8 · 9 로 읽혔다.
PERSUADE_HTML = (
    "<table><tr><td>설득 전략</td><td>내용</td></tr><tr><td>7인성적 설득 전략</td><td>화자의 성품, 경험, 전문성 "
    "등을 내세워 믿을 만하다고 판단하게 하는 전략</td></tr><tr><td>8이성적 설득 전략</td><td>주장에 대해 타당한 근거를 "
    "들어 논리적으로 표현함으로써 설득력을 높이는 전략</td></tr><tr><td>9감성적 설득 전략</td><td>감성에 호소함으로써 "
    "청중에게 감정을 유발하여 화자의 말에 공감하게 하는 전략</td></tr></table>")
PERSUADE_LAYER = (
    "설득 전략  내용\n㉠ <!강조>인성적 설득 전략<!/강조>\n화자의 성품, 경험, 전문성 등을 내세워 믿을 만하다고 "
    "판단하게 하는 \n전략\n㉡ <!강조>이성적 설득 전략<!/강조>\n주장에 대해 타당한 근거를 들어 논리적으로 "
    "표현함으로써 설득력을 높\n이는 전략 \n㉢ <!강조>감성적 설득 전략<!/강조>\n감성에 호소함으로써 청중에게 "
    "감정을 유발하여 화자의 말에 공감하게 \n하는 전략")

# 생명과학Ⅰ body p0100 표 1: `㉠이 있는 사람` · `㉡이 있는 사람` 이 7 · 8 로 읽혔다. 앞뒤 글이 같아 어느 글자인지 못 가린다.
BLOOD_HTML = (
    "<table><tr><td>구분</td><td>사람 수</td></tr><tr><td>7이 있는 사람</td><td>60</td></tr><tr><td>8이 있는 사람</td>"
    "<td>59</td></tr><tr><td>9과 10이 모두 없는 사람</td><td>16</td></tr></table>")
BLOOD_LAYER = "구분  사람 수\n㉠이 있는 사람  60\n㉡이 있는 사람  59\nⓐ <!강조>㉠과 ㉡이 모두 없는 사람<!/강조>  16"

# 생명과학Ⅰ body p0188 표 1: ㉠ 이 수식 구간 `$7$` 로 읽혔다.
VALUE_HTML = (
    "<table><tr><td>구분</td><td>가치</td></tr><tr><td>(가)</td><td> $7$ 생태계 평형 유지에 매우 중요하다.</td></tr>"
    "<tr><td>(나)</td><td>식량을 제공하고, 의약품 등의 원료로 이용된다.</td></tr><tr><td>(다)</td><td>아름다운 경관을 "
    "통해 인간에게 휴식 공간과 문화 공간을 제공한다.</td></tr></table>")
VALUE_LAYER = (
    "구분  가치\n(가)  ㉠ <!강조>생태계 평형 유지<!/강조>에 매우 중요하다.\n(나)  식량을 제공하고, 의약품 등의 "
    "원료로 이용된다.\n(다)\n아름다운 경관을 통해 인간에게 휴식 공간과 문화 공간을 제\n공한다.")

# 생명과학Ⅰ ans p0041 표 0: 행머리 ㉠(3) · ㉡(2) · ㉢(1) 이 $7(3)$ · $8(2)$ · $9(1)$ 로 읽혔다. 창 하나는 나란한 행에서
# 옆 행 글자에 맞춰지기 쉬워, 글자는 문맥 `(2)` · `(1)` 로 정한다. ⓐ(2) 는 동그라미 로마자라 이 고침 밖.
DNA_HTML = (
    '<table><tr><td rowspan="2">구성원</td><td colspan="4">DNA 상대량</td></tr><tr><td>A</td><td>a</td><td>B</td>'
    "<td>b</td></tr><tr><td> $7(3)$ </td><td>1</td><td>1</td><td>?(1)</td><td>0</td></tr><tr><td> $8(2)$ </td><td>0</td>"
    "<td>?(2)</td><td>2</td><td>0</td></tr><tr><td> $9(1)$ </td><td> $10(2)$ </td><td>0</td><td>0</td><td>?(1)</td></tr>"
    "<tr><td>5</td><td>?(1)</td><td>?(1)</td><td> $11(1)$ </td><td>2</td></tr></table>")
DNA_LAYER = ("구성원\nDNA 상대량\nA  a  B  b\n㉠(3)  1  1 ?(1)  0\n㉡(2)  0 ?(2)  2  0\n㉢(1)  ⓐ(2)  0  0 ?(1)\n"
             "5 ?(1) ?(1)  ⓑ(1)  2")


@pytest.fixture
def layer(monkeypatch):
    """층 글을 원하는 문자열로 고정한다(PDF 없이). 스위치는 기본(켬)에서 시작한다."""
    monkeypatch.delenv("TABLE_CELL_CIRCLED_DIGIT", raising=False)

    def _set(text):
        monkeypatch.setattr(MR, "_native_text_pair", lambda page, bb, skip_math=False: (text, text))
    return _set


def test_표_칸_민_숫자를_층의_동그라미_한글로_되돌린다(layer, monkeypatch):
    layer(PERSUADE_LAYER)
    monkeypatch.setenv("TABLE_CELL_CIRCLED_DIGIT", "0")
    assert "7인성적 설득 전략" in MR._correct_table_cells(None, BBOX, PERSUADE_HTML)        # 종전
    monkeypatch.setenv("TABLE_CELL_CIRCLED_DIGIT", "1")
    out = MR._correct_table_cells(None, BBOX, PERSUADE_HTML)
    assert "<td>㉠인성적 설득 전략</td>" in out
    assert "<td>㉡이성적 설득 전략</td>" in out
    assert "<td>㉢감성적 설득 전략</td>" in out


def test_어느_글자인지_못_가리면_되돌리지_않는다(layer):
    layer(BLOOD_LAYER)
    out = MR._correct_table_cells(None, BBOX, BLOOD_HTML)
    assert "<td>7이 있는 사람</td>" in out and "<td>8이 있는 사람</td>" in out


def test_수식_구간_숫자를_되돌리면_글로_푼다(layer):
    layer(VALUE_LAYER)
    out = MR._correct_table_cells(None, BBOX, VALUE_HTML)
    assert "<td> ㉠ 생태계 평형 유지에 매우 중요하다.</td>" in out and "$" not in out


def test_글자는_창이_아니라_문맥으로_정한다(layer):
    layer(DNA_LAYER)
    out = MR._correct_table_cells(None, BBOX, DNA_HTML)
    assert "<td> ㉠(3) </td>" in out and "<td> ㉡(2) </td>" in out and "<td> ㉢(1) </td>" in out
    assert "<td> $10(2)$ </td>" in out
