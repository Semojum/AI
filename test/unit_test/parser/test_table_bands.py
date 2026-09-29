"""표 영역에 먹힌 표 밖 글 되살리기(#989).

실물(2027 언매 p062): 〈보기〉 상자 안에 대화와 표가 있는데 MinerU 가 상자 전체를 표 하나로 잡았다.
표 bbox 는 상자를 다 덮고 table_body 에는 안쪽 표만 있어 대화가 사라졌다. 글은 텍스트레이어에 있다.
"""
import sys
from pathlib import Path

import fitz
import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser import mineru_runner as M  # noqa: E402

BB = [204, 160, 876, 424]          # 표 bbox(0~1000) — 상자 전체
HTML = ("<table><tr><td>구분</td><td>명령형 어미</td><td>관형사형 어미</td></tr>"
        "<tr><td>동사</td><td>결합할 수 있음</td><td>는과 결합함</td></tr>"
        "<tr><td>형용사</td><td>결합할 수 없음</td><td>은과 결합함</td></tr></table>")


def _page(extra_above=True, extra_below=True, label=False):
    doc = fitz.open()
    pg = doc.new_page(width=583, height=737)

    def put(y, t, x=130):
        pg.insert_text((x, y), t, fontname="korea", fontsize=9)
    if label:
        put(128, "보기", 135)
    if extra_above:
        put(140, "학생: 선생님, 어떤 용언이 동사로도 쓰이고 형용사로도 쓰이는 경우")
        put(155, "품사를 어떻게 구분할 수 있을까요?")
    put(210, "구분", 166), put(210, "명령형 어미", 230), put(210, "관형사형 어미", 340)
    put(248, "동사", 166), put(248, "결합할 수 있음", 230), put(248, "는과 결합함", 340)
    put(266, "형용사", 162), put(266, "결합할 수 없음", 230), put(266, "은과 결합함", 340)
    if extra_below:
        put(290, "선생님: 맞습니다. 잘 이해했네요.")
    return doc, pg


def _run(pg, cl):
    return M._recover_table_bands(cl, pg, 1)


def test_표_위아래_띠를_표_앞뒤_글로_되살린다():
    doc, pg = _page()
    out = _run(pg, [{"type": "table", "bbox": BB, "table_body": HTML}])
    assert [x["type"] for x in out] == ["text", "table", "text"]
    assert "구분할 수 있을까요" in out[0]["text"] and "맞습니다" not in out[0]["text"]
    assert "맞습니다" in out[2]["text"]
    assert out[0]["_flag"] == out[2]["_flag"] == "TEXTLAYER_TABLE_OUTSIDE"
    # 띠 bbox 는 표 bbox 안, 표 줄 위·아래에 있다
    assert BB[1] <= out[0]["bbox"][1] < out[0]["bbox"][3] <= out[2]["bbox"][1] <= BB[3]


def test_표_줄만_있으면_그대로():
    doc, pg = _page(extra_above=False, extra_below=False)
    cl = [{"type": "table", "bbox": BB, "table_body": HTML}]
    assert _run(pg, cl) == cl


def test_상자_제목_보기는_띠에서_뺀다():
    """gold 는 '보기' 를 테두리 제목(【글상자 〈보기〉】)으로 적는다 — 본문 줄로 넣으면 두 번 적힌다."""
    doc, pg = _page(extra_above=False, extra_below=False, label=True)
    cl = [{"type": "table", "bbox": BB, "table_body": HTML}]
    assert _run(pg, cl) == cl


def test_이미_글_블록에_있으면_넣지_않는다():
    doc, pg = _page(extra_above=True, extra_below=False)
    cl = [{"type": "text", "text": "학생: 선생님, 어떤 용언이 동사로도 쓰이고 형용사로도 쓰이는 경우 품사를 어떻게 구분할 수 있을까요?"},
          {"type": "table", "bbox": BB, "table_body": HTML}]
    assert _run(pg, cl) == cl


def test_표_줄을_못_찾으면_건드리지_않는다():
    """칸 글이 레이어와 안 맞으면(스캔본·오독) 어디가 표인지 모른다 — 되살리지 않는다."""
    doc, pg = _page()
    cl = [{"type": "table", "bbox": BB, "table_body": "<table><tr><td>전혀</td><td>다른</td></tr></table>"}]
    assert _run(pg, cl) == cl


def test_표_붕괴는_건드리지_않는다(monkeypatch):
    """붕괴한 표는 run() 이 영역 레이어 글로 통째로 갈아치운다 — 띠까지 넣으면 두 번 들어간다."""
    doc, pg = _page()
    monkeypatch.setattr(M, "_collapsed_table", lambda html: True)
    cl = [{"type": "table", "bbox": BB, "table_body": HTML}]
    assert _run(pg, cl) == cl


def test_표가_아니면_그대로():
    doc, pg = _page()
    cl = [{"type": "image", "bbox": BB}, {"type": "text", "text": "본문", "bbox": [1, 1, 2, 2]}]
    assert _run(pg, cl) == cl


@pytest.mark.parametrize("label", ["보기", "<보기>", "〈보기〉", "보 기"])
def test_상자_제목_꼴(label):
    assert M._BAND_LABEL_RE.match(label)


def test_문장이_아닌_띠는_되살리지_않는다():
    """그림 라벨·격자 칸 이름은 표 밖 글처럼 보여도 gold 가 그렇게 적지 않는다(590쪽 실측 6개 모두)."""
    doc = fitz.open()
    pg = doc.new_page(width=583, height=737)

    def put(y, t, x=130):
        pg.insert_text((x, y), t, fontname="korea", fontsize=9)
    put(210, "구분", 166), put(210, "명령형 어미", 230), put(210, "관형사형 어미", 340)
    put(248, "동사", 166), put(248, "결합할 수 있음", 230), put(248, "는과 결합함", 340)
    put(266, "형용사", 162), put(266, "결합할 수 없음", 230), put(266, "은과 결합함", 340)
    put(290, "반응의 진행  반응물  생성물  흡수됨  방출됨")
    cl = [{"type": "table", "bbox": BB, "table_body": HTML}]
    assert _run(pg, cl) == cl
