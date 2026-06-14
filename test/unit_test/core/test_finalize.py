"""마감 조판 /finalize 단위 테스트.

점역사가 편집한 블록(이미 32칸 줄)을 BBPG 규정대로 페이지 조립.
재-wrap 없이 빈 줄·25줄 페이지·페이지행만 적용 — 점자 규정은 AI 소유, BE/FE는 호출만.
"""
from __future__ import annotations

import asyncio

from app.ai.braille.layout_braille import LayoutBraille, _COLS, _ROWS


def _blocks():
    return [
        {"id": "t", "type": "title", "heading_level": 1, "order": 1, "lines": ["⠦⠕⠂⠊⠥"]},
        {"id": "b", "type": "text", "heading_level": 0, "order": 2,
         "lines": ["⠠⠕⠂⠦⠕⠂⠊⠥", "⠊⠲"]},
        {"id": "pn", "type": "page_number", "order": 0, "lines": ["⠼⠁"]},
        {"id": "hf", "type": "header_footer", "order": 0, "lines": ["⠈⠪⠐⠕⠢"]},
    ]


class TestFinalizeAssembly:
    def test_페이지_규격_32x25(self):
        pages = LayoutBraille().finalize(_blocks(), page_no=1)
        assert pages and len(pages) >= 1
        for pg in pages:
            assert len(pg) == _ROWS, f"페이지가 {len(pg)}줄 (기대 {_ROWS})"
            for ln in pg:
                assert len(ln) <= _COLS, f"32칸 초과: {ln!r}"

    def test_페이지행_점자번호_원본번호(self):
        pages = LayoutBraille().finalize(_blocks(), page_no=1)
        page_row = pages[0][-1]                 # 마지막 줄 = 페이지행
        assert len(page_row) == _COLS
        assert page_row.startswith("⠼⠁")        # 좌: 원본 페이지번호
        assert page_row.rstrip().endswith("⠼⠁")  # 우: 점자 페이지번호 ⠼1 (마침표 없음)
        assert "⠈⠪⠐⠕⠢" in page_row              # 가운데: 꼬리말

    def test_본문_보존(self):
        pages = LayoutBraille().finalize(_blocks(), page_no=1)
        joined = "\n".join(pages[0])
        assert "⠦⠕⠂⠊⠥" in joined                # 제목
        assert "⠠⠕⠂⠦⠕⠂⠊⠥" in joined            # 본문

    def test_재wrap_없음_줄보존(self):
        # 이미 28칸인 줄을 편집본으로 주면 그대로 보존(재-wrap·변형 금지)
        line28 = "⠁" * 28
        pages = LayoutBraille().finalize(
            [{"type": "text", "heading_level": 0, "order": 1, "lines": [line28]}], page_no=1
        )
        assert any(line28 == ln for pg in pages for ln in pg), "편집 줄이 변형됨"

    def test_읽기순서_정렬(self):
        # order가 뒤섞여 들어와도 order대로 조립
        blocks = [
            {"type": "text", "heading_level": 0, "order": 2, "lines": ["⠃⠃"]},
            {"type": "text", "heading_level": 0, "order": 1, "lines": ["⠁⠁"]},
        ]
        pages = LayoutBraille().finalize(blocks, page_no=1)
        body = [ln for ln in pages[0] if ln.strip()][:2]
        assert body[0] == "⠁⠁" and body[1] == "⠃⠃"


class TestFinalizeEndpoint:
    def test_endpoint_응답구조(self):
        from app.core.routes import FinalizeRequest, finalize_page

        req = FinalizeRequest(job_id="j", page_no=1, total_pages=1,
                              blocks=_blocks())
        resp = asyncio.run(finalize_page(req))
        assert resp.job_id == "j"
        assert resp.page_number == 1
        assert resp.pages and all(len(p.lines) == _ROWS for p in resp.pages)
        assert resp.pages[0].page_no == 1
        assert resp.brf and "\n".join(resp.pages[0].lines) in resp.brf
