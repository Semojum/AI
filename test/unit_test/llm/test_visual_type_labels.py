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


def test_만화는_안이_하나다():
    """한 장면이면 장면 설정, 여러 장면이면 대사 — **재료가 가르니** 이름은 하나다."""
    assert vd.desc_label("만화") == "만화"
    assert vd.prose_label("만화") == "만화"       # 같은 이름 → 둘째 안을 안 만든다


def test_그림_사진_그래프는_분량으로_갈린다():
    """형식이 아니라 분량이다. '문제 풀이용/개념 학습용'은 폐기됐다 — 우리는 문제를 안 본다."""
    for k in ("이미지", "차트", ""):
        assert vd.desc_label(k) == "설명", k
        assert vd.prose_label(k) == "설명(자세히)", k


def test_도표만_줄글이_골격과_갈린다():
    assert vd.prose_label("concept_map") == "줄글 설명"


def test_표_이름이_점자_차이를_말한다():
    """★ 셋이 **묵자로는 똑같이 보이고 차이가 점자에만 있다**(대표 승인 2026-08-25).
    그래서 이름이 그 차이를 말한다 — 무엇이 다른지를 안 알려 주는 이름은 폐기다."""
    from app.ai.llm.table_opt import _RENDER_LABEL, _TABLE_DRAFT_MODES
    assert _RENDER_LABEL["table_grid"] == "테두리+구분선"   # 테두리 + 구분선 + 쌍점
    assert _RENDER_LABEL["linear"] == "테두리만"            # 테두리만, 구분선·쌍점 없음
    assert _RENDER_LABEL["transposed"] == "행열 바꿈"       # 축이 다르다
    assert dict(_TABLE_DRAFT_MODES and
                {m: lb for _n, m, lb in _TABLE_DRAFT_MODES})["unfold"] == "테두리 없음"
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


def test_들여쓰기_태그_숫자는_앞_빈칸_수다():
    """★ 지침의 칸 번호가 아니다(대표가 못 박음). 지침 '3칸에서 적는다' = <!2칸>."""
    from app.ai.braille import tag_names as T
    assert T.indent_tag(2) == "<!2칸>"     # 지침 "3칸에서 적는다"
    assert T.indent_tag(4) == "<!4칸>"     # 지침 "5칸에서 적는다"
    assert T.indent_tag(6) == "<!6칸>"     # 지침 "7칸에서 적는다"


def test_들여쓰기_0에는_태그를_안_붙인다():
    """★ 태그는 **묵자에서 점자로 갈 때 달라지는 것만** 표기한다(대표 지시).
    0은 기본값이라 달라지는 게 없다 — 표기할 것이 없으면 태그도 없다."""
    from app.ai.braille import tag_names as T
    assert T.indent_tag(0) == ""
    tagged = T.apply_indent_tags("해모수\n주몽\n유리", [0, 2, 4])
    assert tagged == "해모수\n<!2칸>주몽\n<!4칸>유리"
    assert T.strip_indent_tags(tagged) == ("해모수\n주몽\n유리", [0, 2, 4])


def test_후보를_점수순_최대_셋까지_낸다():
    """★ 신호는 코퍼스 실측으로만 정했다(471건) — 화살표·친족낱말·위계깊이 셋뿐이다."""
    from uuid import uuid4
    from app.schemas.content import ExtractedContent
    from app.ai.llm.diagram_opt import _subtype_scores, _CAND_MAX
    def sc(cap):
        e = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, corrected_text=cap)
        return [k for k, _v in _subtype_scores(e, cap)]
    # 유형어는 개념도인데 화살표가 있다 → 흐름도가 둘째 후보로 선다(실측 최대 갈래 35건)
    assert sc("개념도: 물질대사 A → B → C") == ["concept_map", "flowchart"]
    # 8종 밖(지도)은 후보가 서지 않는다 — 억지 배정 금지
    assert sc("동아시아 지역을 표시한 지도") == []
    assert _CAND_MAX == 3


def test_8종_밖은_설명_폴백이다():
    """지도를 개념도로 보면 위계 없는 자료에 위계 개조식이 붙는다."""
    import asyncio
    from uuid import uuid4
    from app.schemas.content import ExtractedContent
    from app.ai.llm.diagram_opt import DiagramOpt
    ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                           corrected_text="동아시아 지역을 표시한 지도")
    opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
    assert opt.drafts[opt.selected_idx].label == "설명"


def test_표_셀_태그와_안_섞인다():
    """`<!칸>`(표 셀)에는 숫자가 없어 들여쓰기 태그로 안 읽힌다."""
    from app.ai.braille import tag_names as T
    assert T.split_indent("<!칸>값") == (None, "<!칸>값")
    assert T.split_indent("<!2칸>값") == (2, "값")


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
    from app.ai.braille import tag_names as T
    by = {d.label: T.strip_indent_tags(d.text)[1] for d in opt.drafts}
    assert by["가계도(하향식)"] == [4, 4, 2, 0, 2, 4]
    assert by["가계도(상향식)"] == [4, 4, 2, 2, 2, 2]
    # ★ 줄 수가 6으로 같아 길이 검사로는 못 걸렀다 — 그래서 태그로 옮겼다
    assert len(by["가계도(하향식)"]) == len(by["가계도(상향식)"])
    # 호환 필드는 **선택된 안의 글에 박힌 태그**에서 되읽는다
    assert opt.line_indents == T.strip_indent_tags(opt.drafts[opt.selected_idx].text)[1]


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
    from app.ai.braille import tag_names as T
    assert bo.line_indents == [4, 4, 2, 0, 2, 4]          # 선택 안(하향식)의 값
    # 점역 결과에 태그 잔재가 남으면 안 된다
    assert not any("칸>" in ln for d in bo.drafts for ln in (d.braille_lines or []))
    assert not any("칸>" in ln for ln in bo.braille_lines)


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
