"""표 규정 골격 회귀 — 구조화 입력(table_structure) → render_mode + 격자/전치/선형 3안.

도서 제작 지침 제3장: 표는 풀어주기 원칙 + 격자/전치/선형 레이아웃. 셀 값은 전사(rule-based).
(시각자료 제목 5칸 §6.3.3의 표 적용 여부는 도서지침 3장 확인 전까지 보류 — 추측 금지.)
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.table_braille import TableBraille, _border_line
from app.ai.llm.table_opt import TableOpt, _table_to_text, _infer_render_mode
from app.schemas.content import ExtractedContent

_CELLS = {
    "cells": [
        {"row": 0, "col": 0, "text": "연도"}, {"row": 0, "col": 1, "text": "권수"},
        {"row": 1, "col": 0, "text": "2020"}, {"row": 1, "col": 1, "text": "980"},
        {"row": 2, "col": 0, "text": "2021"}, {"row": 2, "col": 1, "text": "1100"},
    ],
}


class TestStructuredInput:
    def test_셀_전사(self):
        text = _table_to_text(_CELLS)
        assert "연도 | 권수" in text and "2020 | 980" in text   # 셀 값 전사(rule-based)

    def test_render_mode_추론(self):
        assert _infer_render_mode(_CELLS) == "linear"            # 2열 → 선형
        grid = {"cells": _CELLS["cells"] + [{"row": 0, "col": 2, "text": "비고"}]}
        assert _infer_render_mode(grid) == "table_grid"          # 3열 → 격자


class TestOptimize:
    def test_구조화입력_render_mode_결정(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, table_structure=_CELLS)
        opt = asyncio.run(TableOpt().optimize([ext], "ZERO"))[0]
        assert opt.render_mode == "linear"
        assert "2020" in opt.corrected_text and "980" in opt.corrected_text

    def test_격자_3안_테두리(self):
        grid = {"cells": _CELLS["cells"] + [{"row": 0, "col": 2, "text": "비고"},
                                            {"row": 1, "col": 2, "text": "a"},
                                            {"row": 2, "col": 2, "text": "b"}]}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, table_structure=grid)
        opt = asyncio.run(TableOpt().optimize([ext], "ZERO"))
        bo = TableBraille().translate(opt)[0]
        labels = [d.label for d in bo.drafts]
        assert labels == ["격자형", "행↔열 전치", "선형(키:값)"]   # 레이아웃 3안(셀 동일)
        assert _border_line() in bo.drafts[0].braille_lines        # 격자 테두리 ⠿
