"""도표 규정 골격 회귀 — 개념도(§6.6.1)·흐름도(§6.6.2) rule-based 조립.

§6.3.3(1) 제목 5칸 · §6.3.4(1) 유형 점역자주 · §6.6.1(3) 위계 개조식(2단계 5/3·3단계 7/5/3)
· §6.6.2(4) 흐름도 번호+한 줄·분기 3칸(도형 점형은 점역사 확인 후 — 구조만).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.diagram_braille import DiagramBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.diagram_opt import (
    DiagramOpt, assemble_concept_map, assemble_flowchart,
    _tree_depth, _concept_indent,
)
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

_CONCEPT_3 = {
    "subtype": "concept_map",
    "nodes": [
        {"text": "생물", "children": [
            {"text": "동물", "children": [{"text": "포유류"}, {"text": "조류"}]},
            {"text": "식물", "children": [{"text": "속씨식물"}]},
        ]},
    ],
}
_CONCEPT_2 = {
    "subtype": "concept_map",
    "title": "먹이 사슬",
    "nodes": [{"text": "생산자", "children": [{"text": "소비자"}]}],
}
_FLOW = {
    "subtype": "flowchart",
    "boxes": [
        {"no": 1, "text": "시작"},
        {"no": 2, "text": "조건?", "branches": [{"label": "예", "to": 3}, {"label": "아니오", "to": 4}]},
        {"no": 3, "text": "처리"},
        {"no": 4, "text": "종료"},
    ],
}


class TestConceptIndent:
    def test_깊이(self):
        assert _tree_depth(_CONCEPT_3["nodes"]) == 3
        assert _tree_depth(_CONCEPT_2["nodes"]) == 2

    def test_들여쓰기_규칙(self):
        # ★ 단위는 **앞 빈칸**이다 — 규정의 "N칸에서 시작" = 빈칸 N-1.
        # 2단계: 상위 5칸·하위 3칸 (§6.6.1(3)①)
        assert _concept_indent(0, 2) == 4 and _concept_indent(1, 2) == 2
        # 3단계: 최상위 7칸·중위 5칸·하위 3칸 (§6.6.1(3)②)
        assert [_concept_indent(l, 3) for l in (0, 1, 2)] == [6, 4, 2]


class TestConceptAssemble:
    def test_3단계_개조식_전사(self):
        text, indents = assemble_concept_map(_CONCEPT_3)
        lines = text.split("\n")
        assert lines[0] == "<!주>그림<!/주>:" and indents[0] == 4   # §2.1.8(3) 5칸
        # 중심개념부터 하위로(§6.6.1(2)), 7/5/3칸 = 빈칸 6/4/2
        assert lines[1:] == ["생물", "동물", "포유류", "조류", "식물", "속씨식물"]
        assert indents[1:] == [6, 4, 2, 2, 4, 2]

    def test_2단계_제목5칸(self):
        text, indents = assemble_concept_map(_CONCEPT_2)
        lines = text.split("\n")
        assert lines[0] == "먹이 사슬" and indents[0] == 4                      # §6.3.3(1) 5칸
        assert lines[1] == "<!주>그림<!/주>:"
        assert (lines[2], indents[2]) == ("생산자", 4) and (lines[3], indents[3]) == ("소비자", 2)


class TestFlowAssemble:
    def test_번호_한줄_분기3칸(self):
        text, indents = assemble_flowchart(_FLOW)
        lines = text.split("\n")
        assert lines[0] == "<!주>그림<!/주>:"                      # §6.3.4(1)
        # §6.6.2(4)⑥ "3o 선택사항 3o 목적지" — 정답 예6-19(⠒⠕ = →)
        assert lines[1:] == ["1 시작", "2 조건?", "→ 예 → 3", "→ 아니오 → 4", "3 처리", "4 종료"]
        # 상자 1칸(빈칸0), 분기 선택지 3칸(빈칸2)
        assert indents[1:] == [0, 0, 2, 2, 0, 0]


class TestOptimize:
    def test_concept_라우팅(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=_CONCEPT_3)
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert opt.render_mode == "narrative"
        assert "생물" in opt.corrected_text and opt.line_indents[1] == 6

    def test_flow_라우팅_visual_subtype(self):
        # structure.subtype 없이 visual_subtype로만 흐름도 판별
        st = {"boxes": _FLOW["boxes"]}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               structure=st, visual_subtype="flowchart")
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert "1 시작" in opt.corrected_text

    def test_구조없음_폴백(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               corrected_text="가계도 설명", visual_subtype="concept_map")
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert "개념도" in opt.corrected_text and "가계도 설명" in opt.corrected_text

    def test_빈입력은_생략_표기(self):
        """재료가 없으면 생략 표기다 (§6.3.4(2)②, 2026-08-12 대표 지시).

        종전엔 "[처리 불가: 도표 캡션 없음]"을 냈다 — 그 한글이 **그대로 점자로 찍혀**
        학생에게 나갔고, drafts가 0개라 점역사 피커에는 생략조차 안 떴다.
        """
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, visual_subtype="flowchart")
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        assert "처리 불가" not in opt.corrected_text
        assert opt.corrected_text.endswith("생략<!/주>")
        from app.ai.llm.visual_drafts import LABELS as _LB, OMIT_IDX as _OI
        assert [d.label for d in opt.drafts] == [_LB[_OI]]


class TestE2E:
    def test_개념도_위계_들여쓰기(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_CONCEPT_3)
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))
        bo = DiagramBraille().translate(opt)
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="diagram", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="dg", layout_result=lr)
        result = (tmp_path / "storage/jobs/dg/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8").split("\n")
        content = [l for l in result if l.strip()]
        dec = decode("\n".join(result))
        assert "생물" in dec and "포유류" in dec                       # 셀 값 전사
        # 최상위 7칸(빈칸6)·하위 3칸(빈칸2) 들여쓰기가 result.txt에 반영
        top = next(l for l in content if "생물" in decode(l))
        assert top.startswith("⠀" * 6) and not top.startswith("⠀" * 7)
        leaf = next(l for l in content if "포유류" in decode(l))
        assert leaf.startswith("⠀" * 2) and not leaf.startswith("⠀" * 3)


class TestStep17DiagramTrail:
    """Step17 — 도표 근거는 subtype마다 제 조항으로, tag에 판정·조립 방식을 담는다."""

    def test_subtype마다_제_조항(self):
        from app.ai.llm.diagram_opt import _min_trail

        assert _min_trail("flowchart", "골격 조립")[0].rule_id == "NISE-6.6.2"
        assert _min_trail("org_chart", "골격 조립")[0].rule_id == "NISE-6.6.5"
        assert _min_trail("timeline", "골격 조립")[0].rule_id == "NISE-6.6.6"
        # 종전에는 셋 다 개념도(§6.6.1)로 나갔다 — 흐름도에 개념도 조항이 근거로 붙었다.
        assert _min_trail("concept_map", "골격 조립")[0].rule_id == "NISE-6.6.1"

    def test_tag에_유형과_조립방식(self):
        from app.ai.llm.diagram_opt import _min_trail

        assert _min_trail("flowchart", "골격 조립")[0].tag == "흐름도·골격 조립"

    def test_모든_조항이_레지스트리에_있다(self):
        from app.ai.braille.regulations import all_rule_ids
        from app.ai.llm.diagram_opt import _SUBTYPE_RULE

        assert set(_SUBTYPE_RULE.values()) <= all_rule_ids()


class TestStep17CaptionSource:
    """Step17 — 대체텍스트의 출처(인쇄 캡션 전사 / AI 생성 / 구조 전사)를 근거에 남긴다."""

    def test_출처_구분(self):
        from app.ai.llm.visual_drafts import OMIT_IDX, DESC_IDX, caption_source

        f = caption_source
        assert f(DESC_IDX, used_llm=True, has_print_caption=True, has_struct=False) == "AI 생성"
        assert f(DESC_IDX, used_llm=False, has_print_caption=True, has_struct=False) == "인쇄 캡션 전사"
        assert f(DESC_IDX, used_llm=True, has_print_caption=True, has_struct=True) == "구조 전사(무-LLM)"
        assert f(OMIT_IDX, used_llm=False, has_print_caption=False, has_struct=False).startswith("생략")

    def test_근거_tag는_선택안과_출처(self):
        from app.ai.llm.visual_drafts import DESC_IDX, LABELS, visual_trail
        from app.schemas.content import Draft

        drafts = [Draft(option=i + 1, text="x", render_mode="narrative", label=lb)
                  for i, lb in enumerate(LABELS)]
        r = visual_trail("NISE-6.3.4", drafts, DESC_IDX, "AI 생성")[0]
        assert r.tag == "설명·AI 생성"


class TestCaptionTypeWord:
    """캡션이 말한 유형어를 그대로 쓴다 (F16, 2026-08-26).

    `_SUBTYPE_WORDS` 가 모식도·구조도·도식을 concept_map 으로 접는다. 골격은 §6.6.1 을
    같이 쓰니 그 접기가 맞지만, **표시 이름까지 '개념도'로 바꾸면 캡션이 '구조도'라고
    말한 자료를 우리가 고쳐 부른다.** dev-2027 60쪽에서 유형이 배정된 29건 중 20건이
    이 자리였다.
    """

    def test_캡션_유형어를_쓴다(self):
        from app.ai.llm.diagram_opt import _caption_type_word
        assert _caption_type_word("concept_map", "도표: 구조도, 삼각형 ABC") == "구조도"
        assert _caption_type_word("concept_map", "도표: 모식도, 적혈구의 용혈") == "모식도"
        assert _caption_type_word("flowchart", "도표: 흐름도: 림프구의 성숙") == "흐름도"

    def test_갈래가_어긋나면_안_쓴다(self):
        """캡션은 가계도라는데 앞단이 개념도를 줬으면 이름을 캡션 쪽으로 끌지 않는다 —
        골격(개념도 조항)과 이름이 따로 놀면 점역사에게 틀린 근거가 붙는다."""
        from app.ai.llm.diagram_opt import _caption_type_word
        assert _caption_type_word("concept_map", "가계도 설명") == ""

    def test_유형어가_없으면_빈값(self):
        from app.ai.llm.diagram_opt import _caption_type_word
        assert _caption_type_word("concept_map", "삼각형 ABC 와 점 H") == ""


class TestOutputTypeWord:
    """점자로 나가는 유형 제시어는 `그림` 하나다 (대표 결재 2026-08-26).

    두 층을 나눈다 — **피커에 뜨는 이름**(흐름도·개념도·조직도…)은 그대로 두고,
    **점자로 나가는 글**만 규정 형식으로 적는다.

    근거는 지침 §6.3.4(1) 원문이다 — "원본 제목에 **'사진', '그림'** 등과 같은 시각 자료
    유형 제시어가 없더라도 …". 규정이 드는 제시어가 '사진'·'그림'이지 '흐름도'가 아니다.
    gold 도 같다: 도형 그림 11/11 `그림:` · 흐름도도 `그림:` · 그래프 88건도 `그림:`.
    """

    def test_점자에는_그림만_나간다(self):
        from app.ai.llm.diagram_opt import (
            assemble_flowchart, assemble_org_chart, assemble_concept_map)
        for asm, st in (
            (assemble_flowchart, {"boxes": [{"no": "1", "text": "가"}]}),
            (assemble_org_chart, {"nodes": [{"text": "가", "children": []}]}),
            (assemble_concept_map, {"items": [(0, "가")]}),
        ):
            text, _ = asm(st)
            assert "<!주>그림<!/주>:" in text, (asm.__name__, text)
            for word in ("흐름도", "조직도", "개념도"):
                assert f"<!주>{word}<!/주>" not in text, (asm.__name__, text)

    def test_피커_이름은_그대로다(self):
        """골격 안 이름(점역사가 고르는 것)은 유형 그대로 남는다."""
        from app.ai.llm.diagram_opt import _skeleton_label
        assert "흐름도" in _skeleton_label("flowchart", {})


class TestFlowChainAlt:
    """흐름도는 규정형·관행형 **둘 다** 낸다 (대표 결재 2026-08-26).

    어느 쪽이 맞는지 정하지 않는다 — 규정 §6.6.2(4)③④ 는 '상자 한 줄에 하나' 이고
    gold 2027 은 화살표 체인 한 줄이다(desk D020). 둘을 피커에 나란히 띄우고
    점역사가 고른다.
    """

    _ST = {"boxes": [{"no": "1", "text": "시상하부"},
                     {"no": "2", "text": "뇌하수체전엽"},
                     {"no": "3", "text": "갑상선",
                      "branches": [{"label": "예", "to": "A"}]}]}

    def test_관행형은_한_줄로_접는다(self):
        from app.ai.llm.diagram_opt import assemble_flowchart_chain
        text, _ = assemble_flowchart_chain(self._ST)
        assert "①시상하부 → ②뇌하수체전엽 → ③갑상선" in text, text
        assert "- 예 → A" in text, text          # 갈래는 붙임표로(gold 실물)

    def test_규정형은_줄마다_하나다(self):
        from app.ai.llm.diagram_opt import assemble_flowchart
        text, _ = assemble_flowchart(self._ST)
        assert "1 시상하부" in text and "2 뇌하수체전엽" in text, text
        assert "→" not in text.split("\n")[1], text   # 첫 상자 줄에 화살표가 없다

    def test_상자_하나면_체인을_안_낸다(self):
        """체인이 성립하지 않는다 — 없는 안을 피커에 띄우지 않는다."""
        from app.ai.llm.diagram_opt import _flow_chain_alt
        assert _flow_chain_alt("flowchart", {"boxes": [{"no": "1", "text": "가"}]}) is None
        assert _flow_chain_alt("concept_map", self._ST) is None
