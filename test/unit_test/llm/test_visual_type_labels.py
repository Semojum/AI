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

def test_생략_이름이_설명_없음을_밝힌다():
    """정답의 '그림 생략'은 그래픽 미제작 고지이고 뒤에 설명이 붙는다. 우리 것과 다른 뜻이다."""
    assert vd.LABELS[vd.OMIT_IDX] == "설명 없이 생략 고지"


def test_참조는_별책_참조다():
    assert vd.LABELS[vd.VOLREF_IDX] == "별책 참조"


@pytest.mark.parametrize("subtype,name", [
    ("concept_map", "위계 개조식"),
    ("flowchart", "순서대로 풀기"),
    ("org_chart", "위계 들여쓰기"),
    ("family_tree", "하향식"),
    ("timeline", "시간순 목록"),
    ("form", "글상자 항목"),
    ("screen_image", "글상자 구획"),
    ("slide", "제목·들여쓰기 재구성"),
    ("만화", "장면별 대사"),
])
def test_유형마다_제_이름으로_나온다(subtype, name):
    assert vd.desc_label(subtype) == name


def test_모르는_유형은_줄글_설명이다():
    """그림·사진은 §6.1.1(5) 그대로 — 골격이 없으니 줄글이다."""
    assert vd.desc_label("이미지") == "줄글 설명"
    assert vd.desc_label("") == "줄글 설명"


def test_만화만_줄글_이름이_다르다():
    assert vd.prose_label("만화") == "장면 설정 설명"
    assert vd.prose_label("개념도") == "줄글 설명"


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


def test_가계도는_방향_둘을_같이_낸다():
    """§6.6.4(1) '효과적인 쪽을 고르라'는 기계가 못 하는 판단이다 — 둘 다 내고 사람이 고른다."""
    from app.ai.llm.diagram_opt import _family_alt, _skeleton_label
    st = {"mode": "top_down",
          "nodes": [{"text": "할아버지", "children": [{"text": "아버지"}]}],
          "items": [{"text": "나"}, {"text": "아버지"}]}
    assert _skeleton_label("family_tree", st) == "하향식"
    alt = _family_alt("family_tree", st)
    assert alt is not None and alt.label == "상향식"
    assert alt.option == vd.FAMILY_BOTTOMUP_OPTION
    # 반대로 상향식으로 조립됐으면 이름도 뒤집힌다
    st2 = {**st, "mode": "bottom_up"}
    assert _skeleton_label("family_tree", st2) == "상향식"
    assert _family_alt("family_tree", st2).label == "하향식"


def test_가계도_아닌_유형은_방향_안이_없다():
    from app.ai.llm.diagram_opt import _family_alt
    assert _family_alt("concept_map", {"nodes": [{"text": "가"}]}) is None


def test_없는_방향은_지어내지_않는다():
    """상향식 재료(items)가 없으면 상향식 안을 만들지 않는다 — §6.6.4(3)④ 부모 번호 미배선."""
    from app.ai.llm.diagram_opt import _family_alt
    assert _family_alt("family_tree", {"mode": "top_down", "nodes": [{"text": "가"}]}) is None
