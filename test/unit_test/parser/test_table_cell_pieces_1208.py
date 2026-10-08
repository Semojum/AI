"""표 칸 대조: 긴 칸 층 조각 대조와 창 어긋남 막이(#1208) — mineru_runner._correct_table_cells.

층은 표 전체 폭을 줄 단위로 읽어 두 줄 이상인 칸 사이에 이웃 칸 글이 끼고 줄 차례도 칸 차례와 다르다.
그래서 긴 칸이 창 하나로 안 맞아 표의 오독 교정이 통째로 막혔다. 시험 표는 전부 #1148 탐침이 기록한 실제
칸 HTML(MinerU)과 층 글이다(V2 temp/n136/cells_EBS-E26-*_on.jsonl). 기대 글자는 층(묵자 원본) 글자다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as MR  # noqa: E402

BBOX = [0, 0, 1000, 1000]

# 생명과학Ⅰ body p0074 표 0: 증상 칸이 세 줄이고, 층에서 그 칸 셋째 줄('박수와 … 증가한다.')이 첫 줄보다 앞에 온다.
THYROID_HTML = (
    "<table><tr><td>종류</td><td>증상</td><td>치료</td></tr><tr><td>갑상샘 기능 향진증</td>"
    "<td>• 대사량 증가: 땅을 많이 흘리고, 체중이 감소하고, 심박수와 심장 박출량이 증가한다."
    "• 성격이 과민해지고, 눈이 돌출되는 경우도 있다.</td><td>갑상샘 기능 억제제 복용방사성 아이오딘 치료</td></tr>"
    "<tr><td>갑상샘 기능 저하증</td><td>• 대사량 감소: 동작이 느려지고, 추위를 많이 타고, 체중이 증가하고, "
    "심박수와 심장 박출량이 감소한다.</td><td>갑상샘 호르몬(티록신) 복용</td></tr></table>")
THYROID_LAYER = (
    "종류  증상  치료\n갑상샘 기능 항진증  박수와 심장 박출량이 증가한다.\n"
    "•  대사량 증가: 땀을 많이 흘리고, 체중이 감소하고, 심\n•  성격이 과민해지고, 눈이 돌출되는 경우도 있다.\n"
    "갑상샘 기능 억제제 복용\n방사성 아이오딘 치료\n갑상샘 기능 저하증  갑상샘 호르몬(티록신) 복용\n"
    "• 대사량 감소: 동작이 느려지고, 추위를 많이 타고, 체\n중이 증가하고, 심박수와 심장 박출량이 감소한다.")

# 생명과학Ⅰ body p0019 표 0: 두 칸이 나란한 문장이다('동화 작용은 … 흡수되는' ↔ '이화 작용은 … 방출되는').
ANABOLISM_HTML = (
    "<table><tr><td>동화 작용</td><td>이화 작용</td></tr><tr><td>•간단하고 작은 물질을 복잡하고 큰 물질로 "
    "합성하는 반응이다.•동화 작용은 에너지가 흡수되는 반응이다.</td><td>•복잡하고 큰 물질을 간단하고 작은 "
    "물질로 분해하는 반응이다.•이화 작용은 에너지가 방출되는 반응이다.</td></tr><tr><td></td><td></td></tr></table>")
ANABOLISM_LAYER = (
    "동화 작용  이화 작용\n• 간단하고 작은 물질을 복잡하고 큰 물질로 합성하는  • 복잡하고 큰 물질을 간단하고 "
    "작은 물질로 분해하는\n반응이다.  반응이다.\n• 동화 작용은 에너지가 흡수되는 반응이다.  • 이화 작용은 "
    "에너지가 방출되는 반응이다.\n반응의 진행  반응의 진행\n반응물  생성물\n생성물  에너지가  반응물  에너지가\n"
    "흡수됨  방출됨")

# 사회·문화 body p0047 표 1: 청소년기 기관 칸 '학교, 또래 집단, 대중 매체' 의 창 하나가 칸 끝에서 이웃 줄로 넘어가
# '대중 매체' 를 '대중 의정' 으로 바꾸려 한다(창 끝 치환).
SOCIAL_HTML = (
    "<table><tr><td>구분</td><td>주요 사회화 내용</td><td>주요 사회화 기관</td></tr><tr><td>유아기</td>"
    "<td>기본적인 욕구 충족 및 정서적 반응 방식 습득</td><td>가족</td></tr><tr><td>아동기</td><td>타인들과의 "
    "상호 작용을 위한 언어와 규범, 기초적인 지식과 기능 습득</td><td>가족, 또래 집단</td></tr><tr><td>청소년기</td>"
    "<td>사회생활에 필요한 전문적인 지식과 기능 습득, 사회 구성원으로서 의 정체성 형성</td><td>학교, 또래 집단, "
    "대중 매체</td></tr><tr><td>성년기</td><td>소속 집단에서 요구되는 지식과 기능, 변화하는 사회에 적응하기 위한 "
    "새로운 지식과 기능 습득</td><td>회사, 대중 매체, 평생 교육 기관</td></tr></table>")
SOCIAL_LAYER = (
    "구분  주요 사회화 내용  주요 사회화 기관\n유아기  기본적인 욕구 충족 및 정서적 반응 방식 습득  가족\n"
    "아동기  가족, 또래 집단\n타인들과의 상호 작용을 위한 언어와 규범, 기초적인 지식과 기능 \n습득\n청소년기\n"
    "사회생활에 필요한 전문적인 지식과 기능 습득, 사회 구성원으로서  학교, 또래 집단, 대중\n의 정체성 형성  매체\n"
    "성년기\n소속 집단에서 요구되는 지식과 기능, 변화하는 사회에 적응하기  회사, 대중 매체, 평생\n"
    "위한 새로운 지식과 기능 습득  교육 기관")


@pytest.fixture
def layer(monkeypatch):
    """층 글을 원하는 문자열로 고정한다(PDF 없이). 스위치는 기본(켬)에서 시작한다."""
    monkeypatch.delenv("TABLE_CELL_PIECES", raising=False)

    def _set(text):
        monkeypatch.setattr(MR, "_native_text_pair", lambda page, bb, skip_math=False: (text, text))
    return _set


def test_섞여_읽힌_긴_칸을_조각으로_대어_표_교정을_살린다(layer, monkeypatch):
    layer(THYROID_LAYER)
    monkeypatch.setenv("TABLE_CELL_PIECES", "0")
    assert MR._correct_table_cells(None, BBOX, THYROID_HTML) == THYROID_HTML   # 종전: 증상 칸 하나로 표째 포기
    monkeypatch.setenv("TABLE_CELL_PIECES", "1")
    out = MR._correct_table_cells(None, BBOX, THYROID_HTML)
    assert "갑상샘 기능 항진증" in out and "향진증" not in out                   # 창 하나로 맞는 칸의 교정
    assert "땀을 많이 흘리고" in out and "땅을" not in out                       # 조각으로 댄 긴 칸의 교정


def test_나란한_옆_칸_문장으로_고치지_않는다(layer):
    layer(ANABOLISM_LAYER)
    out = MR._correct_table_cells(None, BBOX, ANABOLISM_HTML)
    assert "•이화 작용은 에너지가 방출되는 반응이다." in out
    assert "•동화 작용은 에너지가 흡수되는 반응이다." in out
    assert out == ANABOLISM_HTML


def test_살린_표는_창_끝에_닿는_치환을_버린다(layer):
    layer(SOCIAL_LAYER)
    out = MR._correct_table_cells(None, BBOX, SOCIAL_HTML)
    assert "학교, 또래 집단, 대중 매체" in out and "의정" not in out


def test_다른_칸_글과_똑같은_조각은_이_칸을_고치는_데_안_쓴다():
    # 언어와 매체 body p0033 표 1: 두 칸이 '직접적으로' ↔ '간접적으로' 만 다르다.
    left = "담화의수용이나생산활동에직접적으로개입하는맥락"
    right = "담화의수용이나생산활동에간접적으로개입하는맥락"
    piece = "담화의수용이나생산활동에간접적으로개입하는"
    assert MR._piece_windows(left, [piece], left + "\x00" + right) is None
    assert MR._piece_windows(right, [piece], left + "\x00" + right) == [(0, piece)]
