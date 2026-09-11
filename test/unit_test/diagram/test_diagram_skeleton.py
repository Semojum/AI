"""도표 규정 골격 회귀 — 개념도(§6.6.1)·흐름도(§6.6.2) rule-based 조립.

§6.3.3(1) 제목 5칸 · §6.3.4(1) 유형 점역자주 · §6.6.1(3) 위계 개조식(2단계 5/3·3단계 7/5/3)
· §6.6.2(4) 흐름도 번호+한 줄·분기 3칸(도형 점형은 점역사 확인 후 — 구조만).
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.visual_braille import DiagramBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.diagram_opt import (
    DiagramOpt, assemble_concept_map, assemble_flowchart,
    _tree_depth, _concept_indent,
)
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult
from app.utils.braille_back import decode

# 유형 제시어 줄 — 쌍점은 **주 밖**이다(도서지침 제3장 제2절 4)(1) L2367-2369,
# [예 3-19] BRF `,'@["o5,'"1`). gold 는 반대지만 빈도로 규정을 뒤집지 않는다(원장 C-D4).
_TYPE_NOTE = "<!주>그림<!/주>:"

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
        # 도서지침 3장 2절 4)(1)(2) L2368 유형 제시어 머리줄 "3칸에서 시작" = 빈칸 2
        # (원장 C-D3 — 종전 §2.1.8(3) 5칸 인용은 "자료 위에 얹는 주"의 자리였다)
        assert lines[0] == _TYPE_NOTE and indents[0] == 2
        # 중심개념부터 하위로(§6.6.1(2)), 7/5/3칸 = 빈칸 6/4/2
        assert lines[1:] == ["생물", "동물", "포유류", "조류", "식물", "속씨식물"]
        assert indents[1:] == [6, 4, 2, 2, 4, 2]

    def test_2단계_제목5칸(self):
        text, indents = assemble_concept_map(_CONCEPT_2)
        lines = text.split("\n")
        assert lines[0] == "먹이 사슬" and indents[0] == 4                      # §6.3.3(1) 5칸
        assert lines[1] == _TYPE_NOTE
        assert (lines[2], indents[2]) == ("생산자", 4) and (lines[3], indents[3]) == ("소비자", 2)


class TestFlowAssemble:
    def test_번호_한줄_분기3칸(self):
        text, indents = assemble_flowchart(_FLOW)
        lines = text.split("\n")
        assert lines[0] == _TYPE_NOTE                      # §6.3.4(1)
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
        # 이름에 탐지된 유형이 붙는다(2026-09-06 결재). 끝 낱말로 본다.
        assert len(opt.drafts) == 1 and opt.drafts[0].label.endswith(_LB[_OI])


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
        from app.ai.llm.visual_drafts import caption_source

        f = caption_source
        # ★ 2026-09-08(재구조화 5단계) — `used_llm` 인자를 뺐다. L8 LLM 팔이 없어져
        #   4안 출처는 '구조 전사 / 인쇄 캡션 전사 / 제목 전사 / 생략' 넷뿐이다.
        # ★ 2026-09-11(#863) — 첫 인자를 리스트 인덱스에서 **'생략 안이 골렸는가'** 로
        #   바꿨다. 순서가 바뀌어 0 번이 생략이 아니라 기본 안이 됐기 때문이다.
        assert f(False, has_print_caption=True, has_struct=False) == "인쇄 캡션 전사"
        assert f(False, has_print_caption=False, has_struct=False) == "제목 전사"
        assert f(False, has_print_caption=True, has_struct=True) == "구조 전사(무-LLM)"
        assert "생략" in f(True, has_print_caption=False, has_struct=False)

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
            assert _TYPE_NOTE in text, (asm.__name__, text)
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


class TestSummaryHeadLine:
    """제목 자리(5칸·주표 밖)에는 **원본에서 관측된 제목만** 앉는다(#794).

    「점자 자료 제작 지침」 §6.3.3(1) L3168 "시각 자료의 제목은 **원본 자료의** 위치와
    상관없이 … 윗줄 5칸에 적는다" · §6.3.4(2)① L3177-3179 "**제목이 없는** 시각 자료를
    설명하거나 생략할 경우 점역자 주표 안에 '시각 자료 유형: 추가 설명문'을 적고".
    규정 예시 전수 25건에도 유형어 줄 앞 별도 줄에 설명을 둔 것은 0건이다.

    ★ 2026-09-10 — 판정 기준이 **문장 꼴**(종결어미+마침표)에서 **출처**로 바뀌었다.
      캡션 첫 줄이 명사구면 LLM 이 지은 말이 제목 자리에 그대로 앉았다(실측 67건 중 51건).
    """

    def test_캡션에서_만든_제목은_유형어_뒤_같은_줄(self):
        """`structure_from_caption` 이 만든 title = 캡션 첫 줄 = 점역자가 쓴 글."""
        from app.ai.llm.diagram_opt import DiagramOpt, _structure
        from app.ai.llm.diagram_opt import assemble_timeline

        ext = ExtractedContent(
            element_id=uuid4(), ocr_confidence=1.0,
            corrected_text="도표: 주요 사건 연대표\n1911년 신해혁명\n1919년 5·4 운동")
        st = _structure(ext, "timeline")
        assert st.get("_llm_title") is True, st
        text, indents = assemble_timeline(st)
        first = text.split("\n")[0]
        assert first.startswith(f"{_TYPE_NOTE} "), first     # §6.3.4(2)①
        assert indents[0] == 2, indents          # 3칸(도서지침 3장 2절 4)(1) L2368)
        assert DiagramOpt is not None

    def test_명사구_요약도_제목_자리에_안_앉는다(self):
        """종전 `_is_summary`(종결어미+마침표)가 놓치던 자리 — 실측 51/67건."""
        from app.ai.llm.diagram_opt import _head_lines

        lines, indents = _head_lines({"title": "고려 중앙 통치 조직도", "_llm_title": True})
        assert lines == [f"{_TYPE_NOTE} 고려 중앙 통치 조직도"], lines
        assert indents == [2], indents

    def test_앞단이_준_원본_제목은_5칸_제목_줄로_남는다(self):
        from app.ai.llm.diagram_opt import assemble_flowchart
        st = {"subtype": "flowchart",
              "title": "[심화·보충형 교육과정 운영도]",     # 규정 예3-22 실물
              "boxes": [{"no": "1", "text": "기본과정"}]}
        text, indents = assemble_flowchart(st)
        lines = text.split("\n")
        assert lines[0] == "[심화·보충형 교육과정 운영도]", lines
        assert indents[0] == 4, indents                     # §6.3.3(1) 5칸
        assert lines[1] == _TYPE_NOTE, lines

    def test_제목이_없으면_유형어만(self):
        from app.ai.llm.diagram_opt import assemble_concept_map
        text, indents = assemble_concept_map({"subtype": "concept_map",
                                              "nodes": [{"text": "생물"}]})
        assert text.split("\n")[0] == _TYPE_NOTE, text
        assert indents[0] == 2, indents


class TestFamilyTreeGenerationIndent:
    """§6.6.4(2)② 하향식 가계도 — 처음 선조 1칸, 세대마다 +2칸(정답 예6-21)."""

    def test_평면_캡션도_세대로_들여쓴다(self):
        from app.ai.llm.diagram_structure import structure_from_caption
        from app.ai.llm.diagram_opt import assemble_family_tree
        cap = ("도표: 어떤 유전병에 대한 3대에 걸친 가계도이다.\n"
               "1세대 1 정상 남자 × 2 유전병 여자 →\n"
               "2세대 1 정상 여자, 2 유전병 남자\n"
               "3세대 1 정상 여자, 2 정상 남자")
        st = structure_from_caption(cap, "family_tree")
        text, indents = assemble_family_tree(st)
        lines = text.split("\n")
        gen = {ln[:3]: ind for ln, ind in zip(lines, indents) if ln[:1].isdigit()}
        assert gen == {"1세대": 0, "2세대": 2, "3세대": 4}, (gen, lines)

    def test_로마자_세대도_들여쓴다(self):
        """생물 교과 가계도는 세대를 `I대`·`II대` 로 적는다 — 동결 코퍼스 실물(#794).

        아라비아 숫자만 보던 종전 정규식은 dev·val 1,131쪽의 가계도 6건 중 **한 건도**
        못 잡았다(전건 평면). 실물: corpus-devall-생물 p025.
        """
        from app.ai.llm.diagram_structure import structure_from_caption
        from app.ai.llm.diagram_opt import assemble_family_tree
        cap = ("도표: 가계도 자료, 3대에 걸친 유전병 유전 양식 표시.\n"
               "I대: 1(정상 남) × 2(유전병 여) 부부.\n"
               "II대: 1(정상 여) × 2(유전병 남) 부부.\n"
               "III대: 1(정상 여), 2(유전병 남).")
        st = structure_from_caption(cap, "family_tree")
        text, indents = assemble_family_tree(st)
        gen = {ln.split(":")[0]: ind for ln, ind in zip(text.split("\n"), indents)
               if ln[:1] == "I"}
        assert gen == {"I대": 0, "II대": 2, "III대": 4}, (gen, text)

    def test_세대_표지가_아니면_안_건드린다(self):
        """`부모 세대`·`위 세대` 같은 낱말 표지는 순서를 모른다 — 평면 그대로 둔다."""
        from app.ai.llm.diagram_structure import caption_outline, _generation_levels
        cap = ("도표: 가계도\n부모 세대: 남자와 여자 부부\n자녀 세대: 영희, 영희의 자매")
        items = caption_outline(cap)
        assert _generation_levels(items) == items

class TestGistDraftHasContent:
    """간추린 설명(#793) — 유형 제시어 줄만 남아 쌍점이 허공에 매달리면 안 된다.

    골격 안에서는 `그림:` 뒤에 항목 줄이 따라오지만 간추린 안은 항목을 버린다.
    그래서 종전에는 `신경 경로 / 그림:` 로 끝나 **설명이 아니라 이름표**가 나갔다
    (캡션 캐시 3,244건 재생 실측: 도표 간추린 475건 중 442건 = 93.1%).
    제목을 유형 제시어 줄로 끌어와 §6.1.4(4) '전체 윤곽' 한 줄로 만든다.
    """

    @staticmethod
    def _gist(structure: dict):
        from app.ai.llm.visual_drafts import GIST_OPTION
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, structure=structure)
        opt = asyncio.run(DiagramOpt().optimize([ext], "ZERO"))[0]
        return next((d for d in opt.drafts if d.option == GIST_OPTION), None)

    def test_제목이_있으면_유형어와_한_줄(self):
        d = self._gist(_CONCEPT_2)
        assert d is not None, "간추린 안이 안 섰다"
        body = decode_free(d.text)
        assert body == f"{_TYPE_NOTE} 먹이 사슬", body

    def test_쌍점으로_끝나는_안은_없다(self):
        """제목이 있든 없든 유형 제시어 뒤에 내용이 있어야 한다."""
        for st in (_CONCEPT_2, _CONCEPT_3, _FLOW):
            d = self._gist(st)
            if d is None:
                continue
            for ln in decode_free(d.text).split("\n"):
                assert not ln.rstrip().endswith(":"), (st.get("subtype"), ln)


def decode_free(text: str) -> str:
    """들여쓰기 태그만 걷어 낸 글 (점역자 주 태그는 남긴다 — 자리 비교용)."""
    from app.ai.braille import tag_names as _T
    return _T.strip_indent_tags(text)[0]
