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
        assert any("⠿⠿" in l for l in _render_unfold("A | \nC | D"))   # 빈 셀=⠿⠿(NLD-3.1.2(4))
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
        assert labels == ["테두리 없음", "테두리+구분선", "행열 바꿈", "테두리만"]
        assert bo.selected_idx == 1, "3열 이상 표의 기본은 테두리+구분선(labels[1])"
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
        # 제목 줄이 위 테두리보다 먼저(§3 5)(2)), **5칸에서 시작 = 앞 빈칸 4**(§3 5)(1)).
        # ★ 2026-08-10 정정(원장 C-21) — 종전 단언은 앞 빈칸 5였다. 지침 자체의 BRF
        #   예3-1이 백틱 4개로 시작하고(도서지침 §3), 예3-5·3-9·3-2·자료지침 예3-4와
        #   코퍼스 `〈표 N〉` 6/6도 모두 앞 빈칸 4다.
        assert lines[0].startswith("⠀" * 4) and not lines[0].startswith("⠀" * 5)
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


class TestAnswerSummaryTable:
    """정답 요약표는 격자가 아니다 (biz B019, dev-2027 실측).

    답지의 "문항번호 정답번호" 요약은 §3.1 이 말하는 표가 아니라 **번호: 값 나열**이다.
    gold 는 표 구분선을 **아예 안 쓰고** 테두리만 둘러 평문으로 적는다.
    표 감사 296건 중 **203건(69%)이 이 한 유형**이고 그중 183건이 한 쪽에 몰려 있다.
    """

    @staticmethod
    def _cells(rows):
        return {"cells": [{"row": r, "col": c, "text": t}
                          for r, row in enumerate(rows) for c, t in enumerate(row)]}

    def test_정답표는_테두리만(self):
        """실물 셀 꼴 — 한 칸에 '번호 답' 이 같이 들어오고 소단원 소제목이 섞인다
        (EBS-E26-004 ans p0003 실측)."""
        from app.ai.llm.table_opt import _infer_render_mode
        st = self._cells([["언어", "01", "01 3", "02 3", "03 2", "04 3"],
                          ["언어", "02", "01 4", "02 4", "03 3", "04 4"]])
        assert _infer_render_mode(st) == "linear"

    def test_긴_머리글이_섞이면_데이터표다(self):
        """넉 자를 넘는 이름이 섞이면 정답 요약표가 아니다 — 실측 반례."""
        from app.ai.llm.table_opt import _infer_render_mode
        st = self._cells([["조음 위치조음 방법", "양순음(입술소리)", "치조음(있몸소리)"],
                          ["파열음", "01 3", "02 3"]])
        assert _infer_render_mode(st) == "table_grid"

    def test_원문자_정답도_같다(self):
        from app.ai.llm.table_opt import _infer_render_mode
        st = self._cells([["1", "④", "2", "④", "3", "②"],
                          ["5", "⑤", "6", "①", "7", "⑤"]])
        assert _infer_render_mode(st) == "linear"

    def test_진짜_데이터표는_격자로_남는다(self):
        """머리글 낱말이 하나라도 있으면 데이터 표다 — 뒤집으면 안 된다."""
        from app.ai.llm.table_opt import _infer_render_mode
        st = self._cells([["구분", "1900", "1950"],
                          ["인구", "12", "20"],
                          ["비율", "3", "5"]])
        assert _infer_render_mode(st) == "table_grid"

    def test_HTML_표에도_걸린다(self):
        """★ 실제로 도는 경로다. d024 경계 파일 60쪽에 `table_structure.cells` 가 든 표는
        **0개**였다 — MinerU 표는 HTML 로 들어온다. 구조 dict 쪽에만 걸면 아무 데도 안 걸린다."""
        from app.ai.llm.table_opt import _infer_render_mode
        html = ("<table><tr><td>언어</td><td>01</td><td>01 3</td></tr>"
                "<tr><td>02 3</td><td>03 2</td><td>04 3</td></tr></table>")
        assert _infer_render_mode(None, html) == "linear"
        data = ("<table><tr><td>구분</td><td>1900</td><td>1950</td></tr>"
                "<tr><td>인구</td><td>12</td><td>20</td></tr></table>")
        assert _infer_render_mode(None, data) == "table_grid"

    def test_작은_표는_안_건드린다(self):
        """셀이 여섯 개도 안 되면 정답 요약표로 보지 않는다(좁게 잡는다)."""
        from app.ai.llm.table_opt import _infer_render_mode
        st = self._cells([["1", "2", "3"], ["4"]])
        assert _infer_render_mode(st) == "table_grid"
