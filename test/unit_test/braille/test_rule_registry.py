"""T4-3 #6 — rule_trail 레지스트리 무결성.

환각 0 아키텍처 강제: 코드가 emit하는 모든 rule_id는 regulations.json(226키)에
존재해야 한다. 가짜·댕글링 rule_id = 0. make_rule()이 유일한 emit 경로이므로
(1) 소스의 make_rule("...") 리터럴 전수가 레지스트리 부분집합인지 정적 검사,
(2) 결정적 braille 변환 경로가 실제 emit하는 id가 레지스트리 부분집합인지 동적 검사.
"""

from __future__ import annotations

import pathlib
import re
from uuid import uuid4

import pytest

from app.ai.braille.cartoon_braille import CartoonBraille
from app.ai.braille.chart_graph_braille import ChartGraphBraille
from app.ai.braille.formula_braille import FormulaBraille
from app.ai.braille.image_braille import ImageBraille
from app.ai.braille.regulations import all_rule_ids, make_rule
from app.ai.braille.table_braille import TableBraille
from app.ai.braille.text_braille import TextBraille
from app.schemas.content import Draft, LLMOutput

_APP_AI = pathlib.Path(__file__).resolve().parents[3] / "app" / "ai"
_MAKE_RULE_RE = re.compile(r"""make_rule\(\s*['"]([^'"]+)['"]""")


def _scan_make_rule_ids() -> set[str]:
    ids: set[str] = set()
    for py in _APP_AI.rglob("*.py"):
        for m in _MAKE_RULE_RE.finditer(py.read_text(encoding="utf-8")):
            ids.add(m.group(1))
    return ids


def _collect_trail_ids(outputs) -> set[str]:
    ids: set[str] = set()
    for o in outputs:
        ids.update(r.rule_id for r in o.rule_trail)
        for d in o.drafts:
            ids.update(r.rule_id for r in d.rule_trail)
    return ids


def _llm(text: str, *, drafts=None, render_mode="text_only") -> LLMOutput:
    return LLMOutput(
        element_id=uuid4(),
        corrected_text=text,
        render_mode=render_mode,
        routing_tier="ZERO",
        drafts=drafts or [],
    )


class TestRuleRegistry:

    def test_registry_size(self):
        assert len(all_rule_ids()) == 226

    def test_make_rule_literals_subset_of_registry(self):
        scanned = _scan_make_rule_ids()
        assert scanned, "make_rule 리터럴을 하나도 찾지 못함 (스캔 경로 오류 의심)"
        dangling = scanned - all_rule_ids()
        assert not dangling, f"regulations.json에 없는 rule_id emit: {sorted(dangling)}"

    def test_make_rule_rejects_dangling(self):
        with pytest.raises(KeyError):
            make_rule("KBR-9.9.9")

    def test_braille_modules_emit_registered_ids(self):
        vis_drafts = [
            Draft(option=1, text="[점역사주] 그림. 설명", render_mode="narrative", label="원본"),
            Draft(option=2, text="[점역사주] 그림. 요약", render_mode="narrative", label="요약"),
        ]
        emitted: set[str] = set()
        emitted |= _collect_trail_ids(TextBraille().translate([_llm("가나다라")]))
        emitted |= _collect_trail_ids(
            FormulaBraille().translate([_llm("x^2", render_mode="formula_block")])
        )
        emitted |= _collect_trail_ids(
            TableBraille().translate([_llm("머리1 | 머리2\n값1 | 값2", render_mode="table_grid")])
        )
        emitted |= _collect_trail_ids(ImageBraille().translate([_llm("", drafts=vis_drafts)]))
        emitted |= _collect_trail_ids(CartoonBraille().translate([_llm("", drafts=vis_drafts)]))
        emitted |= _collect_trail_ids(ChartGraphBraille().translate([_llm("", drafts=vis_drafts)]))

        assert emitted, "emit된 rule_id가 없음"
        dangling = emitted - all_rule_ids()
        assert not dangling, f"점역 모듈이 미등록 rule_id emit: {sorted(dangling)}"
