# -*- coding: utf-8 -*-
"""유형별 대체텍스트 안 이름 (계획서 §5·§6, 2026-08-25 1단계).

이 단계의 회귀 조건은 **기본 선택 불변**이다. CER 로는 못 잰다 — 기본 선택이 그대로면
점수도 그대로다. 그래서 판정을 안 개수·라벨·선택 인덱스로 한다.

★ `_dedupe` 가 **라벨이 아니라 글**로 접고 selected_idx 를 다시 매긴다. 라벨을 바꾸면
  여기가 먼저 깨진다(8/20 에 option 번호로 찾다가 터진 자리와 같은 계열).
"""
from __future__ import annotations

import pytest

from app.ai.llm import visual_drafts as vd
from app.schemas.content import Draft


# ── 할 일 A: 이름 ──────────────────────────────────────────────────────────

def test_이름은_짧다():
    """★ 2026-08-25 2단계 — 대표 지시로 되돌렸다. 긴 이름은 피커에서 오히려 흐려졌다.
    뜻은 옆 근거(rule_trail·점역자 주)가 진다."""
    assert vd.LABELS == ("생략", "설명", "참조")


@pytest.mark.parametrize("subtype,name", [
    ("concept_map", "개념도"),
    ("flowchart", "흐름도"),
    ("org_chart", "조직도"),
    ("family_tree", "가계도(하향식)"),
    ("timeline", "연대표"),
    ("form", "양식"),
    ("screen_image", "화면 이미지"),
    ("slide", "발표용 슬라이드"),
])
def test_도표는_유형명_자체가_방식이다(subtype, name):
    """★ "개념도 - 위계 개조식"은 같은 말을 두 번 하는 꼴이고 조어가 붙는다(대표 지시)."""
    assert vd.desc_label(subtype) == name


def test_골격이_하나뿐인_유형은_설명_하나다():
    """그림·사진·그래프·만화는 방식이 갈리지 않는다."""
    for k in ("이미지", "차트", "만화", ""):
        assert vd.desc_label(k) == "설명", k
        assert vd.prose_label(k) == "설명", k


def test_도표만_줄글이_골격과_갈린다():
    assert vd.prose_label("concept_map") == "줄글 설명"


def test_표_이름이_규정_낱말이다():
    from app.ai.llm.table_opt import _RENDER_LABEL, _TABLE_DRAFT_MODES
    assert _RENDER_LABEL["table_grid"] == "정렬 유지"      # §3.2 절 제목
    assert _RENDER_LABEL["transposed"] == "행열 바꿈"
    assert "선형" not in _RENDER_LABEL["linear"]           # 우리 조어를 지운다
    # 같은 것을 두 이름으로 부르지 않는다 — 묵자 초안과 점자 초안의 라벨이 같아야 한다
    from app.ai.braille import table_braille as tb
    src = open(tb.__file__, encoding="utf-8").read()
    for _n, mode, label in _TABLE_DRAFT_MODES:
        assert f'render_mode="{mode}", label="{label}"' in src, f"{mode} 라벨이 두 파일에서 다르다"


# ── 할 일 B: 안 목록 ───────────────────────────────────────────────────────

def _d(text: str, label: str = "") -> Draft:
    return Draft(option=1, text=text, render_mode="narrative", label=label)


def test_dedupe_는_글이_같을_때만_접고_선택을_따라간다():
    drafts = [_d("가"), _d("나"), _d("가"), _d("다")]
    kept, sel = vd._dedupe(drafts, 2)          # 접히는 안이 선택돼 있었다
    assert [x.text for x in kept] == ["가", "나", "다"]
    assert sel == 0                            # 살아남은 같은 글로 옮겨간다


def test_라벨만_달라도_글이_같으면_접힌다():
    """라벨을 유형별로 바꿔도 접기 기준은 글이다 — 여기가 라벨 변경에 안 흔들려야 한다."""
    kept, sel = vd._dedupe([_d("같은 글", "위계 개조식"), _d("같은 글", "줄글 설명")], 0)
    assert len(kept) == 1 and sel == 0


def test_줄글_안은_재료가_없으면_안_나간다():
    assert vd.prose_draft("", "concept_map") is None
    assert vd.prose_draft("   ", "concept_map") is None


def test_줄글_안은_뒤에_붙는_새_번호다():
    d = vd.prose_draft("사용자 서버, DNS 서버", "concept_map")
    assert d is not None
    assert d.option == vd.PROSE_OPTION == 7          # 1·2·6 은 BE·FE 계약이라 안 건드린다
    assert d.label == "줄글 설명"


# ── 2단계 B: 안마다 자기 들여쓰기 ─────────────────────────────────────────

def test_가계도_방향마다_들여쓰기가_다르다():
    """★ 줄 수가 6으로 같아 길이 검사로는 못 잡는다. 씌우면 세대 방향이 거꾸로 나간다."""
    from app.ai.llm.diagram_opt import assemble_family_tree
    st = {"title": "가계도", "nodes": [{"text": "해모수", "children": [
              {"text": "주몽", "children": [{"text": "유리"}]}]}],
          "items": [{"text": "유리"}, {"text": "주몽"}, {"text": "해모수"}]}
    _t, td = assemble_family_tree({**st, "mode": "top_down"})
    _t2, bu = assemble_family_tree({**st, "mode": "bottom_up"})
    assert len(td) == len(bu)          # 길이 검사가 못 거른다는 것 자체를 고정한다
    assert td != bu


def test_안마다_자기_들여쓰기를_싣는다():
    import asyncio
    from uuid import uuid4
    from app.schemas.content import ExtractedContent
    from app.ai.llm.diagram_opt import DiagramOpt
    st = {"subtype": "family_tree", "title": "가계도", "mode": "top_down",
          "nodes": [{"text": "해모수", "children": [
              {"text": "주몽", "children": [{"text": "유리"}]}]}],
          "items": [{"text": "유리"}, {"text": "주몽"}, {"text": "해모수"}]}
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=st)
    opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
    by = {d.label: d.line_indents for d in opt.drafts}
    assert by["가계도(하향식)"] is not None and by["가계도(상향식)"] is not None
    assert by["가계도(하향식)"] != by["가계도(상향식)"], "안마다 값이 달라야 한다"
    # 호환 필드는 **선택된 안**의 값을 그대로 든다
    assert opt.line_indents == opt.drafts[opt.selected_idx].line_indents


def test_점역_뒤에도_안별_들여쓰기가_남는다():
    import asyncio
    from uuid import uuid4
    from app.schemas.content import ExtractedContent
    from app.ai.llm.diagram_opt import DiagramOpt
    from app.ai.braille.diagram_braille import DiagramBraille
    st = {"subtype": "family_tree", "title": "가계도", "mode": "top_down",
          "nodes": [{"text": "해모수", "children": [
              {"text": "주몽", "children": [{"text": "유리"}]}]}],
          "items": [{"text": "유리"}, {"text": "주몽"}, {"text": "해모수"}]}
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=st)
    bo = DiagramBraille().translate(asyncio.run(DiagramOpt().optimize([ext], "ZERO")))[0]
    by = {d.label: d.line_indents for d in bo.drafts}
    assert by["가계도(하향식)"] != by["가계도(상향식)"]
    assert bo.line_indents == bo.drafts[bo.selected_idx].line_indents


def test_가계도는_방향_둘을_같이_낸다():
    """§6.6.4(1) '효과적인 쪽을 고르라'는 기계가 못 하는 판단이다 — 둘 다 내고 사람이 고른다."""
    from app.ai.llm.diagram_opt import _family_alt, _skeleton_label
    st = {"mode": "top_down",
          "nodes": [{"text": "할아버지", "children": [{"text": "아버지"}]}],
          "items": [{"text": "나"}, {"text": "아버지"}]}
    assert _skeleton_label("family_tree", st) == "가계도(하향식)"
    alt = _family_alt("family_tree", st)
    assert alt is not None and alt.label == "가계도(상향식)"
    assert alt.option == vd.FAMILY_BOTTOMUP_OPTION
    # 반대로 상향식으로 조립됐으면 이름도 뒤집힌다
    st2 = {**st, "mode": "bottom_up"}
    assert _skeleton_label("family_tree", st2) == "가계도(상향식)"
    assert _family_alt("family_tree", st2).label == "가계도(하향식)"


def test_가계도_아닌_유형은_방향_안이_없다():
    from app.ai.llm.diagram_opt import _family_alt
    assert _family_alt("concept_map", {"nodes": [{"text": "가"}]}) is None


def test_없는_방향은_지어내지_않는다():
    """상향식 재료(items)가 없으면 상향식 안을 만들지 않는다 — §6.6.4(3)④ 부모 번호 미배선."""
    from app.ai.llm.diagram_opt import _family_alt
    assert _family_alt("family_tree", {"mode": "top_down", "nodes": [{"text": "가"}]}) is None
