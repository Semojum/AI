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
    assert "<!주>그림<!/주>" in out.corrected_text
    # 캡션 첫 줄('고려 중앙 통치 조직도')은 점역자가 쓴 글이라 §6.3.3(1) 제목 자리(5칸)가
    # 아니라 유형 제시어 뒤 같은 줄로 간다(#794 · §6.3.4(2)① L3177-3179).
    assert out.corrected_text.split("\n")[0].endswith(": 고려 중앙 통치 조직도")
    assert out.line_indents[2:] == [0, 2, 4, 4, 2, 4]
    assert "황제" in out.corrected_text.split("\n")[2]


def test_all_wired_skeletons_reachable():
    """배선한 골격 7종 전부가 캡션에서 만들어진 structure로 발동한다.

    ★ §6.6.7 화면 이미지는 2026-09-09(#793)에 배선을 끊었다 — 조립기는 남아 있고
      `test_diagram_more.TestScreenImage` 가 그 함수를 직접 지킨다.
    """
    caps = {
        "concept_map": "도표: 세포 개념도\n핵\n- 인\n세포질",
        "flowchart": "도표: 처리 흐름도\n입력\n판정\n출력",
        "org_chart": "도표: 조직도\n1. 사장\n1) 부장",
        "family_tree": "도표: 가계도\n1세대\n- 1: 남자",
        "timeline": "도표: 연대표\n1919년 3·1 운동\n1920년 청산리 대첩",
        "form": "도표: 신청 양식\n이름\n생년월일",
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


def test_circled_hangul_is_a_label_not_a_hierarchy_marker():
    """원문자 한글 `㉠~㉺`는 위계 표지가 아니라 **개체 이름표**다 — 떼면 안 된다.

    문항이 `㉠이 무엇인가`를 묻기 때문에 그 글자 자체가 내용이다. 실측 근거:
      · 캡셔너 diagram 프롬프트가 시키는 위계 표지는 `1.` `1)` `①` 셋뿐 — `㉠`은 없다.
      · 캡션 캐시 1,814건의 줄머리 `㉠` 25줄 중 아래 층이 달린 것 0건(전부 잎).
      · gold 시각자료 991건 중 115건이 `㉠~㉺`를 담고 있다(55건은 줄머리). 정답은 안 지운다.
    """
    st = structure_from_caption("도표: 모식도: 사람 몸의 방어 부위\n㉠ 피부\n㉡ 침\n㉢ 눈물\n㉣ 위벽")
    assert [n["text"] for n in st["nodes"]] == ["㉠ 피부", "㉡ 침", "㉢ 눈물", "㉣ 위벽"], st

    # 이름표는 같은 층에 나란히 선다 — 앞 줄 밑으로 들어가지 않는다.
    st2 = structure_from_caption(
        "도표: 모식도: 생태계 구성 요소 사이의 상호 관계\n"
        "생태계 안에 비생물적 요인과 생물 군집\n"
        "㉠ 개체군 A → 비생물적 요인\n㉡ 비생물적 요인 → 개체군 A")
    assert len(st2["nodes"]) == 3 and not st2["nodes"][0]["children"], st2

    # `①`은 프롬프트가 지정한 3층 표지라 종전대로 뗀다(회귀 가드).
    assert structure_from_caption(_ORG)["nodes"][0]["children"][1]["children"][0]["text"] == "이부"


def test_indented_lines_become_flow_branches():
    """#796 — 들여쓴 줄은 상자가 아니라 **분기 선택사항**이다(§6.6.2(4)⑤⑥).

    「점자 자료 제작 지침」 재추출 L3572-3574 "분기점에서 선택사항이 있는 경우,
    선택사항별로 줄을 바꾸어 … 3칸에 3o을 적고, 한 칸 띄어 선택사항, 그 후 3o과 목적지".
    정답 예6-19 가 그 꼴이다. 종전에는 캡션 줄을 전부 상자로 세워 3칸 줄이 한 번도
    안 섰다(캡션 캐시 3,242건 중 흐름도 153건 전부 분기 0개).
    """
    st = structure_from_caption("도표: A와 B를 가르는 흐름도\n"
                                "직관적 통찰로 해석하는가?\n"
                                "  예 → A\n"
                                "  아니요 → B\n"
                                "(나)")
    assert [b["no"] for b in st["boxes"]] == [1, 2], st        # 갈림은 상자 번호를 안 먹는다
    assert st["boxes"][0]["branches"] == [{"label": "예", "to": "A"},
                                          {"label": "아니요", "to": "B"}], st
    assert "branches" not in st["boxes"][1], st

    # 조립하면 갈림 줄이 3칸(들여쓰기 2)에 선다 — §6.6.2(4)⑥.
    text, indents = _ASSEMBLERS["flowchart"][0](st)
    rows = list(zip(text.split("\n"), indents))
    assert ("→ 예 → A", 2) in rows, rows
    assert ("1 직관적 통찰로 해석하는가?", 0) in rows, rows


def test_two_level_indent_builds_concept_and_org_hierarchy():
    """#796 — 캡션이 **두 칸 들여쓰기**로 층을 주면 §6.6.1(3)①·§6.6.5(2)가 선다.

    §6.6.1(3)① "위계가 2단계인 경우: 상위 개념은 5칸, 하위 개념은 3칸"(재추출 L3532).
    종전에는 캡셔너가 "층이 둘이면 한 줄로 끝내라"는 지시를 받아 전건 level 0 으로 와서
    개념도가 408건 중 33건(8.1%)만 위계를 가졌다.
    """
    cap = "도표: 맥락의 갈래를 나눈 개념도이다.\n중심\n  갈래 1\n  갈래 2\n    잔가지"
    st = structure_from_caption(cap, "concept_map")
    assert st["nodes"][0]["children"][1]["children"][0]["text"] == "잔가지", st
    text, indents = _ASSEMBLERS["concept_map"][0](st)
    body = [(ln, i) for ln, i in zip(text.split("\n"), indents) if not ln.startswith(" ")]
    # 3단계 = 7/5/3칸 (들여쓰기 6/4/2) — §6.6.1(3)②
    assert ("중심", 6) in body and ("갈래 1", 4) in body and ("잔가지", 2) in body, body

    st2 = structure_from_caption(cap, "org_chart")
    text2, ind2 = _ASSEMBLERS["org_chart"][0](st2)
    rows = list(zip(text2.split("\n"), ind2))
    # §6.6.5(2) 최상위 1칸 + 단계마다 2칸
    assert ("중심", 0) in rows and ("갈래 1", 2) in rows and ("잔가지", 4) in rows, rows
