"""Step3 태민 파트 E2E 파이프라인 테스트 (ZERO tier, GPU 불필요).

text_ocr.json / formula_ocr.json → TextOpt/FormulaOpt → TextBraille/FormulaBraille
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from unittest.mock import patch
from uuid import uuid4

import pytest

from app.schemas.content import BrailleOutput, ExtractedContent

_DATA = Path(__file__).parent.parent.parent / "test_data" / "page_001"


def _load_text() -> list[ExtractedContent]:
    raw = json.loads((_DATA / "type" / "text" / "text_ocr.json").read_text(encoding="utf-8"))
    return [ExtractedContent.model_validate(d) for d in raw]


def _load_formula() -> list[ExtractedContent]:
    raw = json.loads((_DATA / "type" / "formula" / "formula_ocr.json").read_text(encoding="utf-8"))
    return [ExtractedContent.model_validate(d) for d in raw]


def _run_text_chain(extracted: list[ExtractedContent]) -> list[BrailleOutput]:
    from app.ai.braille.text_braille import TextBraille
    from app.ai.llm.text_opt import TextOpt
    with patch("app.ai.llm.text_opt.model_manager"):
        llm_outputs = asyncio.run(TextOpt().optimize(extracted, routing_tier="ZERO"))
    return TextBraille().translate(llm_outputs)


def _run_formula_chain(extracted: list[ExtractedContent]) -> list[BrailleOutput]:
    from app.ai.braille.formula_braille import FormulaBraille
    from app.ai.llm.formula_opt import FormulaOpt
    with patch("app.ai.llm.formula_opt.model_manager"):
        llm_outputs = asyncio.run(FormulaOpt().optimize(extracted, routing_tier="ZERO"))
    return FormulaBraille().translate(llm_outputs)


# ── T-4a: text chain E2E ─────────────────────────────────────────────────────

class TestTextChainE2E:

    @pytest.fixture(scope="class")
    def outputs(self):
        return _run_text_chain(_load_text())

    def test_count_matches_input(self, outputs):
        assert len(outputs) == len(_load_text())

    def test_all_braille_output_type(self, outputs):
        assert all(isinstance(o, BrailleOutput) for o in outputs)

    def test_braille_lines_not_empty(self, outputs):
        assert all(len(o.braille_lines) >= 1 for o in outputs)

    def test_each_line_within_32_cols(self, outputs):
        # 모듈은 논리 줄, 32칸 줄바꿈은 layout(BBPG-1.2.1) → break_points wrap 후 검증
        from app.ai.braille.layout_braille import _wrap_line
        for o in outputs:
            brs = o.break_points if len(o.break_points) == len(o.braille_lines) else [[]] * len(o.braille_lines)
            for line, br in zip(o.braille_lines, brs):
                assert all(len(seg) <= 32 for seg in _wrap_line(line, br, 32)[0])

    def test_rule_trail_excludes_generic(self, outputs):
        # 정책(태민 2026-06-01): 포괄/조판 규칙(KBR-0.1·BBPG-1.2.1)은 rule_trail 미기록
        for o in outputs:
            rids = [r.rule_id for r in o.rule_trail]
            assert "BBPG-1.2.1" not in rids
            assert "KBR-0.1" not in rids

    def test_element_ids_preserved_in_order(self, outputs):
        src_ids = [str(e.element_id) for e in _load_text()]
        out_ids = [str(o.element_id) for o in outputs]
        assert src_ids == out_ids

    def test_round_trip_all_elements(self, outputs):
        for o in outputs:
            restored = BrailleOutput.model_validate_json(o.model_dump_json())
            assert restored.element_id == o.element_id
            assert restored.braille_lines == o.braille_lines


# ── T-4b: formula chain E2E ──────────────────────────────────────────────────

class TestFormulaChainE2E:

    @pytest.fixture(scope="class")
    def formula_items(self):
        return _load_formula()

    @pytest.fixture(scope="class")
    def outputs(self, formula_items):
        return _run_formula_chain(formula_items)

    def test_count_matches_input(self, outputs, formula_items):
        assert len(outputs) == len(formula_items)

    def test_all_braille_output_type(self, outputs):
        assert all(isinstance(o, BrailleOutput) for o in outputs)

    def test_braille_lines_not_empty(self, outputs):
        assert all(len(o.braille_lines) >= 1 for o in outputs)

    def test_each_line_within_32_cols(self, outputs):
        # 모듈은 논리 줄, 32칸 줄바꿈은 layout(BBPG-1.2.1) → break_points wrap 후 검증
        from app.ai.braille.layout_braille import _wrap_line
        for o in outputs:
            brs = o.break_points if len(o.break_points) == len(o.braille_lines) else [[]] * len(o.braille_lines)
            for line, br in zip(o.braille_lines, brs):
                assert all(len(seg) <= 32 for seg in _wrap_line(line, br, 32)[0])

    def test_fraction_contains_fraction_bar(self, outputs, formula_items):
        """\\frac{1}{2} → 분수 구분자(⠌) 포함."""
        idx = next(i for i, e in enumerate(formula_items) if "frac" in (e.latex_string or ""))
        combined = "".join(outputs[idx].braille_lines)
        assert "⠌" in combined

    def test_fraction_denominator_order(self, outputs, formula_items):
        """수학 제7항: 분모(⠃)가 분수표(⠌) 앞에 위치해야 함."""
        idx = next(i for i, e in enumerate(formula_items) if "frac" in (e.latex_string or ""))
        combined = "".join(outputs[idx].braille_lines)
        bar_pos = combined.index("⠌")
        assert "⠃" in combined[:bar_pos], (
            f"분모(⠃)가 분수표(⠌) 앞에 없음: {combined!r}"
        )

    def test_decimal_formula_uses_correct_cell(self, outputs, formula_items):
        """제43항: 소수점(.) → ⠲ (dots 2,5,6), 자릿점(⠂)과 달라야 함."""
        idx = next(i for i, e in enumerate(formula_items) if (e.latex_string or "") == "0.48")
        combined = "".join(outputs[idx].braille_lines)
        assert "⠲" in combined, f"소수점 ⠲ 없음: {combined!r}"
        assert "⠼" in combined, f"수표 ⠼ 없음: {combined!r}"

    def test_negative_formula_uses_minus_cell(self, outputs, formula_items):
        """수학 제17항: 음수 부호 → ⠤."""
        idx = next(i for i, e in enumerate(formula_items) if (e.latex_string or "") == "-3")
        combined = "".join(outputs[idx].braille_lines)
        assert "⠤" in combined, f"음수 부호 ⠤ 없음: {combined!r}"

    def test_sqrt_contains_root_indicator(self, outputs, formula_items):
        """\\sqrt{x} → 근호 시작자(⠜) 포함."""
        idx = next(i for i, e in enumerate(formula_items) if "sqrt" in (e.latex_string or ""))
        combined = "".join(outputs[idx].braille_lines)
        assert "⠜" in combined

    def test_superscript_contains_indicator(self, outputs, formula_items):
        """a^2 → 위첨자 표시(⠘) 포함."""
        idx = next(i for i, e in enumerate(formula_items) if "^" in (e.latex_string or "") and "frac" not in (e.latex_string or ""))
        combined = "".join(outputs[idx].braille_lines)
        assert "⠘" in combined

    def test_trig_contains_function_indicator(self, outputs, formula_items):
        """\\sin → 삼각함수 표시(⠋) 포함."""
        idx = next(i for i, e in enumerate(formula_items) if "sin" in (e.latex_string or ""))
        combined = "".join(outputs[idx].braille_lines)
        assert "⠋" in combined

    def test_pi_contains_greek_indicator(self, outputs, formula_items):
        """\\pi → 그리스문자 표시(⠨) 포함."""
        idx = next(i for i, e in enumerate(formula_items) if "pi" in (e.latex_string or "") and "sin" not in (e.latex_string or ""))
        combined = "".join(outputs[idx].braille_lines)
        assert "⠨" in combined

    def test_element_ids_preserved_in_order(self, outputs, formula_items):
        assert [str(e.element_id) for e in formula_items] == [str(o.element_id) for o in outputs]

    def test_round_trip_all_elements(self, outputs):
        for o in outputs:
            restored = BrailleOutput.model_validate_json(o.model_dump_json())
            assert restored.element_id == o.element_id
            assert restored.braille_lines == o.braille_lines

    def test_rule_trail_all_fields_present(self, outputs):
        """모든 BrailleOutput의 rule_trail이 필수 6개 필드를 가짐."""
        for o in outputs:
            for r in o.rule_trail:
                assert r.rule_id,  f"rule_id 없음: {r}"
                assert r.source,   f"source 없음: {r}"
                assert r.section,  f"section 없음: {r}"
                assert r.title,    f"title 없음: {r}"
                assert r.excerpt,  f"excerpt 없음: {r}"
                assert r.priority, f"priority 없음: {r}"


# ── T-4c: 요소 격리 검증 ─────────────────────────────────────────────────────

class TestElementIsolationE2E:

    @pytest.fixture(scope="class")
    def outputs_and_items(self):
        items = _load_text()
        fallback = items[0].model_copy(update={
            "corrected_text": "[처리 불가: OCR 실패]",
            "ocr_confidence": 0.0,
            "flags": ["C2_FALLBACK"],
        })
        modified = [fallback] + list(items[1:])
        return _run_text_chain(modified), modified

    def test_total_count_preserved(self, outputs_and_items):
        outputs, items = outputs_and_items
        assert len(outputs) == len(items)

    def test_fallback_element_produces_output(self, outputs_and_items):
        outputs, _ = outputs_and_items
        assert len(outputs[0].braille_lines) >= 1

    def test_normal_elements_unaffected(self, outputs_and_items):
        outputs, _ = outputs_and_items
        for o in outputs[1:]:
            assert len(o.braille_lines) >= 1

    def test_fallback_content_differs_from_normal(self, outputs_and_items):
        outputs, _ = outputs_and_items
        fallback_content = "".join(outputs[0].braille_lines)
        normal_content = "".join(outputs[1].braille_lines)
        assert fallback_content != normal_content

    def test_element_ids_maintained(self, outputs_and_items):
        outputs, items = outputs_and_items
        assert [str(o.element_id) for o in outputs] == [str(e.element_id) for e in items]


# ── T-4d: C5 배포 블로커 (E2E 수준) ─────────────────────────────────────────

class TestC5NumbersE2E:

    @pytest.mark.parametrize("text", ["20일", "30일", "60일"])
    def test_number_produces_number_indicator(self, text):
        from app.ai.braille.text_braille import TextBraille
        from app.ai.llm.text_opt import TextOpt

        extracted = [ExtractedContent(
            element_id=uuid4(),
            corrected_text=text,
            ocr_confidence=1.0,
        )]
        with patch("app.ai.llm.text_opt.model_manager"):
            llm_outputs = asyncio.run(TextOpt().optimize(extracted, routing_tier="ZERO"))
        braille_outputs = TextBraille().translate(llm_outputs)
        combined = "".join(braille_outputs[0].braille_lines)
        assert "⠼" in combined, f"수표(⠼) 없음 — 입력: {text!r}, 출력: {combined!r}"


# ── T-4e: 6-체인 장애 격리 검증 ──────────────────────────────────────────────

class TestSixChainFaultIsolation:
    """asyncio.gather(return_exceptions=True) — 1개 체인 예외 시 나머지 5개 정상 처리.

    Done Criteria: 6-체인 중 1개 실패 → 나머지 5개 정상 처리 확인.

    TestSixChainFaultIsolation 클래스 내에 두 종류의 테스트가 공존한다:
      1. asyncio.gather 동작 검증 (stdlib 레벨) — 목 체인으로 return_exceptions=True 불변량 확인
      2. pipeline._run_pipeline 통합 검증 — 실제 pipeline.py 코드 경로를 타고 formula 체인이
         예외를 던졌을 때 BLOCKED가 아닌 COMPLETED/NEEDS_REVIEW 응답이 반환되는지 확인
    """

    def _make_successful_chain(self, label: str):
        """항상 성공하는 목 체인."""
        async def _chain():
            from uuid import uuid4
            from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput, RuleApplication
            ext = ExtractedContent(element_id=uuid4(), corrected_text=label, ocr_confidence=1.0)
            rule = RuleApplication(
                rule_id="BBPG-1.2.1", source="점자 도서 제작 지침", section="제1장 제2절",
                title="줄바꿈", excerpt="한 줄은 32칸을 넘지 않는다.", priority="primary",
            )
            llm = LLMOutput(element_id=ext.element_id, corrected_text=label,
                            routing_tier="ZERO", rule_trail=[rule])
            br = BrailleOutput(element_id=ext.element_id,
                               braille_lines=[label[:32]], rule_trail=[rule])
            return [ext], [llm], [br]
        return _chain

    def _make_failing_chain(self):
        async def _chain():
            raise RuntimeError("체인 강제 실패 (격리 테스트)")
        return _chain

    def test_one_chain_failure_does_not_block_others(self) -> None:
        """체인 인덱스 2번이 실패해도 나머지 5개의 결과가 수집되어야 함."""
        async def _run():
            return await asyncio.gather(
                self._make_successful_chain("체인A")(),
                self._make_successful_chain("체인B")(),
                self._make_failing_chain()(),
                self._make_successful_chain("체인D")(),
                self._make_successful_chain("체인E")(),
                self._make_successful_chain("체인F")(),
                return_exceptions=True,
            )
        results = asyncio.run(_run())

        assert len(results) == 6
        assert isinstance(results[2], RuntimeError), "실패 체인이 예외를 반환해야 함"
        successful = [r for r in results if not isinstance(r, Exception)]
        assert len(successful) == 5, f"성공 체인 {len(successful)}개 (기대: 5)"

    def test_exception_chain_does_not_corrupt_other_results(self) -> None:
        """실패 체인의 예외가 성공 체인의 출력을 변조하지 않아야 함."""
        from app.schemas.content import BrailleOutput

        async def _run():
            return await asyncio.gather(
                self._make_successful_chain("체인1")(),
                self._make_failing_chain()(),
                self._make_successful_chain("체인3")(),
                return_exceptions=True,
            )
        results = asyncio.run(_run())

        for r in results:
            if isinstance(r, Exception):
                continue
            _, _, braille_list = r
            for br in braille_list:
                assert isinstance(br, BrailleOutput)
                assert len(br.braille_lines) >= 1

    def test_all_chains_fail_returns_empty_aggregate(self) -> None:
        """모든 체인이 실패하면 수집된 결과가 없어야 함."""
        async def _run():
            return await asyncio.gather(
                *[self._make_failing_chain()() for _ in range(6)],
                return_exceptions=True,
            )
        results = asyncio.run(_run())

        all_extracted, all_llm, all_braille = [], [], []
        for result in results:
            if isinstance(result, Exception):
                continue
            ext, llm, br = result
            all_extracted.extend(ext); all_llm.extend(llm); all_braille.extend(br)

        assert len(all_extracted) == 0
        assert len(all_llm) == 0
        assert len(all_braille) == 0

    def test_gather_return_exceptions_preserves_order(self) -> None:
        """return_exceptions=True 시 결과 순서가 입력 순서와 일치해야 함."""
        labels = ["A", "B", "C", "D", "E", "F"]

        async def _run():
            return await asyncio.gather(
                *[self._make_successful_chain(lbl)() for lbl in labels],
                return_exceptions=True,
            )
        results = asyncio.run(_run())

        for i, (result, label) in enumerate(zip(results, labels)):
            assert not isinstance(result, Exception), f"체인 {i}({label}) 실패"
            _, llm_list, _ = result
            assert label in llm_list[0].corrected_text

    # ── 실제 pipeline.py 코드 경로 검증 ──────────────────────────────────────

    def test_pipeline_run_survives_formula_chain_exception(self) -> None:
        """pipeline._run_pipeline()에서 formula 체인이 예외를 던져도 BLOCKED가 아닌 응답을 반환한다.

        asyncio 표준 동작 검증이 아닌, 실제 pipeline.py의 gather+예외 처리 코드 경로를
        통합 수준에서 검증한다.
        """
        from app.core import pipeline
        from app.schemas.content import BrailleOutput, ExtractedContent, LLMOutput, RuleApplication
        from app.schemas.layout import DocumentMeta
        from app.schemas.task import PageTask

        rule = RuleApplication(
            rule_id="BBPG-1.2.1", source="점자 도서 제작 지침",
            section="제1장 제2절", title="줄바꿈", excerpt="한 줄은 32칸을 넘지 않는다.", priority="primary",
        )
        elem_id = uuid4()
        fake_extracted = ExtractedContent(element_id=elem_id, corrected_text="테스트", ocr_confidence=1.0)
        fake_llm = LLMOutput(element_id=elem_id, corrected_text="테스트", routing_tier="ZERO", rule_trail=[rule])
        fake_braille = BrailleOutput(element_id=elem_id, braille_lines=["⠊⠎⠠⠞"], rule_trail=[rule])

        async def _text_chain(*_a, **_k):
            return ([fake_extracted], [fake_llm], [fake_braille])

        async def _fail_formula_chain(*_a, **_k):
            raise RuntimeError("formula 체인 강제 실패 (격리 통합 테스트)")

        task = PageTask(job_id="test-pipeline-isolation", page_no=1, mode="c")
        zero_meta = DocumentMeta(pdf_confidence=0.95, routing_tier="ZERO", scan_only=False)

        async def _run():
            with patch("app.ai.preprocessor.pdf_analyzer.analyze_pdf",
                       return_value=(zero_meta, "mock text")), \
                 patch.object(pipeline, "_run_text_chain", _text_chain), \
                 patch.object(pipeline, "_run_formula_chain", _fail_formula_chain):
                return await pipeline._run_pipeline(task)

        result = asyncio.run(_run())
        assert result["status"] in ("COMPLETED", "NEEDS_REVIEW"), (
            f"formula 체인 예외 시 파이프라인이 BLOCKED 반환: {result.get('status')!r}\n"
            f"  quality_report: {result.get('quality_report')}"
        )


class TestResponseContract:
    """응답 계약(FE/BE) — 읽기 순서·heading_level. (#2, #9a)"""

    @staticmethod
    def _build(elements, llm_outputs):
        from app.core.pipeline import _build_response
        from app.schemas.layout import LayoutResult
        from app.schemas.task import PageTask

        task = PageTask(job_id="t", page_no=1, mode="c")
        lr = LayoutResult(page_id="p", elements=elements)
        return _build_response(task, "p", None, "ZERO", 0, 0, lr, [], llm_outputs, [])

    def test_읽기순서_정렬(self):
        # 그림(reading_order 1)이 본문(2)보다 앞. 체인 순서상 text가 먼저 와도 응답은 읽기순서.
        from app.schemas.content import LLMOutput
        from app.schemas.layout import BBoxItem

        img = uuid4(); txt = uuid4()
        elements = [
            BBoxItem(element_id=img, type="image", bbox=(0, 0, 0, 0), reading_order=1),
            BBoxItem(element_id=txt, type="text", bbox=(0, 0, 0, 0), reading_order=2),
        ]
        # llm_outputs는 체인 묶음 순서(text 먼저)로 들어온다
        llms = [
            LLMOutput(element_id=txt, corrected_text="본문", routing_tier="ZERO"),
            LLMOutput(element_id=img, corrected_text="그림", routing_tier="ZERO"),
        ]
        resp = self._build(elements, llms)
        ids = [e["id"] for e in resp["text_list"]]
        assert ids == [str(img), str(txt)], f"읽기순서 정렬 안 됨: {ids}"
        assert [e["order"] for e in resp["text_list"]] == [1, 2]

    def test_braille_heading_level_반영(self):
        from app.schemas.content import LLMOutput
        from app.schemas.layout import BBoxItem

        tid = uuid4()
        elements = [BBoxItem(element_id=tid, type="title", bbox=(0, 0, 0, 0),
                             reading_order=1, heading_level=1)]
        llms = [LLMOutput(element_id=tid, corrected_text="제목", routing_tier="ZERO")]
        resp = self._build(elements, llms)
        assert resp["braille_text_list"][0]["heading_level"] == 1
