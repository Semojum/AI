"""묵자 꼬리말(강 · 단원 이름)을 점자 본문에 옮기지 않는다(이슈 #1319, 원장 C-86).

좌표는 test_zero_foot_page_number_1247 과 같은 실측이다(생명과학 Ⅰ body p0085 · 사회·문화 body p0023, dev).
꼬리말 글은 언어와 매체 · 화법과 작문 쪽 아래 `[2부] 적용 학습`(dev · val)이다.
"""
import pytest

from app.core import pipeline
from app.core.pipeline import _blocks_with_bbox, _is_page_foot, _parse_txt_result

H = 1474
BODY = {"content": "그림은 사람의 혈당 조절 과정을 나타낸 것이다.", "bbox": [125, 300, 900, 330]}
FOOT = {"content": "06강 항상성  85", "bbox": [977, 1393, 1077, 1417]}
ZERO = {"extraction_method": "TEXT_NATIVE", "bbox_space": "pixel", "image_width": 1168, "image_height": H}
MINERU = {"extraction_method": "OCR", "bbox_space": "norm1000", "image_width": 1167, "image_height": H}
M_BODY = {"type": "text", "content": "갑의 연구 방법은 질적 연구에 해당한다.", "bbox": [101, 903, 699, 926]}
M_FOOT = {"type": "text", "content": "[2부] 적용 학습", "flags": ["MINERU_FOOTER"], "bbox": [735, 945, 891, 960]}


@pytest.fixture(autouse=True)
def _form_off(monkeypatch):
    monkeypatch.setattr(pipeline, "_ITEM_CODE_FORM", "off")


def _texts(meta, els):
    els = [dict(e, order=i) for i, e in enumerate(els, start=1)]
    lay, em, _ = _parse_txt_result({"meta": meta, "elements": els}, "p")
    return [em[b.element_id].corrected_text for b in sorted(lay.elements, key=lambda b: b.reading_order)
            if b.type != "page_number"]


def test_ZERO_쪽_번호를_뗀_꼬리말은_본문에_안_싣는다():
    els = _blocks_with_bbox([BODY, FOOT], H)
    assert [e.get("page_foot") for e in els if e["type"] == "text"] == [None, True]
    assert _texts(ZERO, els) == [BODY["content"]]


def test_MinerU_맨_아래_footer_는_안_싣는다():
    assert _texts(MINERU, [M_BODY, M_FOOT]) == [M_BODY["content"]]


def test_꼬리말도_열_묶기에는_들어간다(monkeypatch):
    # 먼저 빼면 x 겹침 열이 달라져 남은 요소 차례가 바뀐다(A/B 53쪽). 빼는 것은 열 묶기 뒤다.
    seen, real = [], pipeline._reorder_by_geometry
    monkeypatch.setattr(pipeline, "_reorder_by_geometry", lambda items, rot=0: seen.append(len(items)) or real(items, rot))
    assert _texts(MINERU, [M_BODY, M_FOOT]) == [M_BODY["content"]]
    assert seen == [2]


def test_맨_아래가_아닌_footer_는_본문이라_싣는다():
    # 세계사 · 동아시아사에서 MinerU 가 본문(선택지 · 정답 · 해설)을 footer 로 잡는다. 맨 아래가 아니면 안 지운다.
    body = dict(M_BODY, flags=["MINERU_FOOTER"])
    assert _texts(MINERU, [body, M_FOOT]) == [body["content"]]


@pytest.mark.parametrize("content", [
    "정답 해설 ▶ 자료에서 궁재의 지위를 물려받은 점\n오답 피하기 ▶ ① 카롤루스 대제는",   # 여러 문단 = 본문
    "정답과 해설 24쪽",                                                              # 상호참조
    "<!상자>[2부] 적용 학습<!/상자>",                                                 # 상자가 붙은 요소
])
def test_본문_꼴은_맨_아래_footer_여도_싣는다(content):
    assert not _is_page_foot({"flags": ["MINERU_FOOTER"]}, content, True)


def test_스위치를_끄면_종전처럼_싣는다(monkeypatch):
    monkeypatch.setenv("PAGE_FOOT_DROP", "0")
    assert _texts(MINERU, [M_BODY, M_FOOT]) == [M_BODY["content"], M_FOOT["content"]]
    assert _texts(ZERO, _blocks_with_bbox([BODY, FOOT], H)) == [BODY["content"], "06강 항상성"]
