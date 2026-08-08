"""표 규정 골격 회귀 — 구조화 입력(table_structure) → render_mode + 격자/전치/선형 3안.

도서 제작 지침 제3장: 표는 풀어주기 원칙 + 격자/전치/선형 레이아웃. 셀 값은 전사(rule-based).
표 제목: 도서 제작 지침 제3장 5)(1) "표 제목은 5칸에서 시작한다" + (2) 표 위 테두리 앞에 먼저 적는다.
(차트/이미지 제목 5칸 §6.3.3과 별개로 표 제목은 도서지침 §3에서 확정 — 2026-06-08.)
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.table_braille import TableBraille

# 지침 §3.1(예3-4·3-6) 표 테두리 — 위 ⠿⠛…⠿ / 아래 ⠿⠶…⠿ (2026-07-19 지침형 정정)
_TBL_TOP = "⠿" + "⠛" * 30 + "⠿"
_TBL_BOT = "⠿" + "⠶" * 30 + "⠿"
from app.ai.llm.table_opt import TableOpt, _table_to_text, _infer_render_mode, _table_title
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
        # 3열 이상 = 격자형 (2026-08-06 판정 번복 — 원장 C-01a).
        # gold dev-2027 테두리 표 445개 중 383개(86%)가 격자 '행제목: 값' 형식이다.
        assert _infer_render_mode(grid) == "table_grid"

    def test_빈셀_채움(self):
        from app.ai.braille.table_braille import _render_unfold, _render_grid
        assert any("⠿⠿" in l for l in _render_unfold("A | \nC | D"))   # 빈 셀=⠿⠿(BBPG-3.1.2(4))
        assert any("⠿⠿" in l for l in _render_grid("A | \nC | D"))


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
        assert labels == ["풀어쓰기(3칸·2칸)", "격자형", "행↔열 전치", "선형(키:값)"]
        assert bo.selected_idx == 1, "3열 이상 표의 기본은 격자형(labels[1])"
        # ★ 2026-08-06 판정 번복(원장 C-01a). 2026-07-29에는 "코퍼스 14,382줄에 테두리형 0개"를
        #   근거로 뺐는데, 그 표본이 **구판 수능특강 한 종류**였다. 82권으로 재니 정반대다 —
        #   신판 2027 EBS 2.62% · 초등참고서 4.78% · 중등교과서 3.37% · 고등교과서 2.97%.
        assert _TBL_TOP in bo.drafts[1].braille_lines
        assert _TBL_BOT in bo.drafts[1].braille_lines

    def test_격자_규정모드는_테두리_유지(self, monkeypatch):
        """BRAILLE_STYLE=regulation이면 지침형 테두리를 낸다 — 규정 경로 보존."""
        import importlib
        from app.ai.braille import table_braille as tb
        monkeypatch.setenv("BRAILLE_STYLE", "regulation")
        importlib.reload(tb)
        try:
            lines = tb._render_grid("머리|A|B\n행1|1|2")
            assert lines[0] == _TBL_TOP and lines[-1] == _TBL_BOT
        finally:
            monkeypatch.delenv("BRAILLE_STYLE", raising=False)
            importlib.reload(tb)


class TestTitle:
    """표 제목 5칸 — 도서 제작 지침 제3장 5)(1)·(2)."""

    def test_제목_전사(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               table_structure={**_CELLS, "title": "연도별 발행 권수"})
        assert _table_title(ext) == "연도별 발행 권수"          # title 전사(rule-based)
        # structure 쪽에 있어도 인식
        ext2 = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                                table_structure=_CELLS, structure={"title": "표 제목"})
        assert _table_title(ext2) == "표 제목"
        # 없으면 None(기존 동작 보존)
        assert _table_title(ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                                             table_structure=_CELLS)) is None

    def test_제목_opt_전달(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0,
                               table_structure={**_CELLS, "title": "연도별 발행 권수"})
        opt = asyncio.run(TableOpt().optimize([ext], "ZERO"))[0]
        assert opt.table_title == "연도별 발행 권수"

    def test_제목_5칸_위테두리_앞(self):
        grid = {"cells": _CELLS["cells"] + [{"row": 0, "col": 2, "text": "비고"},
                                            {"row": 1, "col": 2, "text": "a"},
                                            {"row": 2, "col": 2, "text": "b"}],
                "title": "연도별 발행 권수"}
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, table_structure=grid)
        opt = asyncio.run(TableOpt().optimize([ext], "ZERO"))
        bo = TableBraille().translate(opt)[0]
        lines = bo.drafts[1].braille_lines                     # 격자형(테두리 있는 대안)
        # 제목 줄이 위 테두리보다 먼저(§3 5)(2)), 5칸 들여(§3 5)(1))
        assert lines[0].startswith(" " * 5) and not lines[0].startswith(" " * 6)
        assert lines[0].strip() and not _is_border(lines[0])
        # 제목 다음 줄이 위 테두리다(§3 5)(2) — 제목이 테두리 **앞**).
        assert lines[1] == _TBL_TOP

    def test_제목_없으면_기존동작(self):
        ext = ExtractedContent(element_id=uuid4(), ocr_confidence=1.0, table_structure=_CELLS)
        opt = asyncio.run(TableOpt().optimize([ext], "ZERO"))
        bo = TableBraille().translate(opt)[0]
        # 제목이 없으면 격자형 첫 줄이 곧 위 테두리다.
        assert bo.drafts[1].braille_lines[0] == _TBL_TOP


def _is_border(line: str) -> bool:
    """지침형 테두리(⠿⠛…⠿·⠿⠶…⠿) 포함 판정."""
    t = line.strip()
    return bool(t) and t[0] == "⠿" and t[-1] == "⠿" and set(t) <= {"⠿", "⠛", "⠶"}
