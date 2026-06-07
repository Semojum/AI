"""만화 rule-based 골격(§5.3) 회귀 — 구조화 입력 → 규정 형식 조립 + 줄별 들여쓰기.

§5.3.1(1) 제목 5칸·§5.3.3(1) 장면 5칸·§5.3.3(2)(3) 대사 3칸·§6.3.4(3) 화자불명 말풍선.
"""
from __future__ import annotations

import asyncio
from uuid import uuid4

from app.ai.braille.cartoon_braille import CartoonBraille
from app.ai.braille.layout_braille import LayoutBraille
from app.ai.llm.cartoon_opt import CartoonOpt, assemble_cartoon
from app.utils.braille_back import decode
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem, LayoutResult

_STRUCT = {
    "title": "우정",
    "panels": [
        {"order": 1, "scene_src": "교실 안", "dialogues": [{"speaker": "학생", "text": "안녕?"}]},
        {"order": 2, "dialogues": [{"speaker": "", "text": "반가워"}]},  # 화자 불명 → 말풍선
    ],
}


class TestAssemble:
    def test_골격_줄_들여쓰기(self):
        text, indents = assemble_cartoon(_STRUCT)
        lines = text.split("\n")
        assert len(indents) == len(lines)
        assert lines[0] == "<!점역자주>만화<!/점역자주> 우정" and indents[0] == 5   # §5.3.1(1)
        assert "<!점역자주>장면 1<!/점역자주>" in lines                             # §5.3.3(1)
        assert indents[lines.index("<!점역자주>장면 1<!/점역자주>")] == 5
        assert "학생:안녕?" in lines and indents[lines.index("학생:안녕?")] == 3     # §5.3.3(2)(3)
        assert "말풍선:반가워" in lines                                             # §6.3.4(3) 화자 불명

    def test_단일장면은_장면번호_없음(self):
        text, _ = assemble_cartoon({"title": "T", "panels": [{"order": 1, "dialogues": []}]})
        assert "장면 1" not in text


class TestEndToEnd:
    def test_조판_줄별_들여쓰기(self, tmp_path, monkeypatch):
        monkeypatch.chdir(tmp_path)
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, structure=_STRUCT)
        opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))
        assert opt[0].line_indents is not None                       # 골격 줄별 들여쓰기 전달
        bo = CartoonBraille().translate(opt)
        lr = LayoutResult(page_id="p", elements=[
            BBoxItem(element_id=eid, type="cartoon", bbox=(0, 0, 0, 0), reading_order=1)])
        LayoutBraille().layout(bo, page_no=1, job_id="cartoon", layout_result=lr)
        result = (tmp_path / "storage/jobs/cartoon/temp/page_001/result/001_result.txt"
                  ).read_text(encoding="utf-8").split("\n")
        dec = decode("\n".join(result))
        for word in ("만화", "우정", "안녕", "반가워", "장면"):
            assert word in dec, f"역점역에 '{word}' 없음: {dec}"
        content = [l for l in result if l.strip()]
        assert any(l.startswith("     ") and not l.startswith("      ") for l in content)  # 5칸(제목/장면)
        assert any(l.startswith("   ") and not l.startswith("    ") for l in content)      # 3칸(대사)


class TestFallback:
    def test_구조_없으면_caption_단일_점역자주(self):
        eid = uuid4()
        ext = ExtractedContent(element_id=eid, ocr_confidence=1.0, corrected_text="두 컷 만화")
        opt = asyncio.run(CartoonOpt().optimize([ext], "ZERO"))
        assert opt[0].line_indents is None
        assert "<!점역자주>" in opt[0].tn_text and "두 컷 만화" in opt[0].tn_text
