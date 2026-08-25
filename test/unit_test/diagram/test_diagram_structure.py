"""캡션 → 도표 세분류·§6.6 골격 입력 회귀 (`app.ai.llm.diagram_structure`).

앞단이 structure를 안 주면 캡션을 파싱해 세운다 — 이 배선이 끊기면 §6.6 골격 8종이
전부 캡션 한 줄 폴백으로 되돌아간다(2026-08-08 이전 상태).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.llm.diagram_opt import DiagramOpt, _ASSEMBLERS
from app.ai.llm.diagram_structure import (
    caption_head, caption_outline, structure_from_caption, subtype_from_caption,
)
from app.schemas.content import ExtractedContent

_ORG = ("도표: 고려 중앙 통치 조직도\n"
        "1. 황제\n1) 3성\n① 중서성\n① 문하성\n2) 6부\n① 이부\n")


def test_subtype_words():
    cases = {
        "도표: 고려 중앙 통치 조직도": "org_chart",
        "도표: 유전 가계도(계통도)": "family_tree",
        "도표: 정자 형성 과정을 나타낸 흐름도.": "flowchart",
        "도표: 19세기 유럽 연표": "timeline",
        "도표: 세포 구조도": "concept_map",
        "도표: 지원서 양식": "form",
        "도표: 프로그램 화면 이미지": "screen_image",
        "도표: 발표용 슬라이드": "slide",
        "도표: 몽골 제국 최대 영역 지도": "",      # §6.6에 골격 없음 → 캡션 폴백
    }
    for cap, want in cases.items():
        assert subtype_from_caption(cap) == want, cap


def test_hierarchy_markers_build_tree():
    """'1. / 1) / ①' 위계 번호로 트리가 서고, 표지는 본문에서 뗀다."""
    st = structure_from_caption(_ORG)
    assert st["subtype"] == "org_chart"
    top = st["nodes"]
    assert [n["text"] for n in top] == ["황제"]
    assert [n["text"] for n in top[0]["children"]] == ["3성", "6부"]
    assert [n["text"] for n in top[0]["children"][0]["children"]] == ["중서성", "문하성"]


def test_pedigree_number_is_not_a_marker():
    """가계도 '1: 정상 남자'의 개체 번호는 위계 표지가 아니다 — 지우면 안 된다."""
    cap = "도표: 가계도\n1세대\n- 1: 정상 남자\n- 2: 발현 여자"
    st = structure_from_caption(cap)
    assert st["nodes"][0]["children"][0]["text"] == "1: 정상 남자"


def test_timeline_inline_list():
    """사건을 한 줄에 쉼표로 몰아 적은 캡션도 연대표가 선다(§6.6.6(2)②)."""
    cap = ("도표: 연표. 1911 신해혁명, 1919 5·4운동, 1926 북벌개시.\n"
           "구간: (가) 1911~1919")
    st = structure_from_caption(cap)
    assert [e["date"] for e in st["events"][:3]] == ["1911", "1919", "1926"]
    assert st["events"][-1]["date"] == ""          # 못 잡은 줄도 버리지 않는다
    assert st["title"] == ""                       # 머리줄=사건목록이면 제목 중복 제거


def test_no_body_no_structure():
    assert structure_from_caption("도표: 조직도 한 줄뿐") is None
    assert caption_outline("한 줄뿐") == []
    assert caption_head("도표: # 가계도") == "가계도"


def test_opt_dispatches_skeleton_from_caption():
    """캡션만 있어도 §6.6.5 조직도 골격이 돈다(최상위 1칸=빈칸0·하위 +2칸)."""
    ext = ExtractedContent(element_id=uuid4(), corrected_text=_ORG, ocr_confidence=1.0)
    out = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
    assert "<!주>조직도<!/주>" in out.corrected_text
    assert out.line_indents[3:] == [0, 2, 4, 4, 2, 4]
    assert "황제" in out.corrected_text.split("\n")[3]


def test_all_eight_skeletons_reachable():
    """골격 8종 전부가 캡션에서 만들어진 structure로 발동한다."""
    caps = {
        "concept_map": "도표: 세포 개념도\n핵\n- 인\n세포질",
        "flowchart": "도표: 처리 흐름도\n입력\n판정\n출력",
        "org_chart": "도표: 조직도\n1. 사장\n1) 부장",
        "family_tree": "도표: 가계도\n1세대\n- 1: 남자",
        "timeline": "도표: 연대표\n1919년 3·1 운동\n1920년 청산리 대첩",
        "form": "도표: 신청 양식\n이름\n생년월일",
        "screen_image": "도표: 화면 이미지\n도구 막대\n- 저장\n본문",
        "slide": "도표: 발표용 슬라이드\n제목\n- 요점",
    }
    for sub, cap in caps.items():
        st = structure_from_caption(cap)
        assert st and st["subtype"] == sub, (sub, st)
        assemble, ok = _ASSEMBLERS[sub]
        assert ok(st), (sub, st)
        text, indents = assemble(st)
        assert text.count("\n") + 1 == len(indents), (sub, text, indents)


def test_bare_type_word_head_is_stripped():
    """캡션 첫 줄의 **맨 종류어**를 제목으로 쓰면 유형이 두 번 나간다 (F18, 대표 지적).

    실물: '모식도\\n개념도:\\n삼각형 ABC:\\n…' — 캡셔너가 첫 줄에 종류를 쓰라는 지시를 받고
    '모식도'를 썼는데, 종전 정규식이 콜론 붙은 여덟 낱말만 떼어 그 줄이 골격 제목으로 남았다.
    유형은 §6.3.4(1) 점역자 주가 내는 몫이다.
    """
    from app.ai.llm.diagram_structure import caption_head, structure_from_caption

    assert caption_head("모식도\n삼각형 ABC\n꼭짓점: A, B, C") == ""
    assert (structure_from_caption("모식도\n삼각형 ABC\n꼭짓점: A, B, C") or {}).get("title") == ""
    # 종류어 뒤에 내용이 있으면 내용만 남는다(종전 동작 유지)
    assert caption_head("개념도: 삼각형 ABC") == "삼각형 ABC"
    assert caption_head("그림: 절벽 아래 돌 더미") == "절벽 아래 돌 더미"
