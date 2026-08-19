

# ── 회전 지면 bbox 보정 (2026-08-20) ────────────────────────────────────────
# PyMuPDF의 텍스트 블록 좌표는 회전 전(mediabox) 좌표계인데 page.rect는 회전 후 크기다.
# 그대로 쓰면 270° 쪽에서 x가 쪽 폭을 넘고 종횡비가 뒤집힌다. 외국어 코퍼스 실측
# 회전 쪽 518개·블록 11,821개 중 21.8%가 쪽 밖이었다.
class TestRotatedPageBbox:
    def _rotated_pdf(self, rotation=270):
        import fitz
        doc = fitz.open()
        page = doc.new_page(width=737, height=583)     # 가로로 긴 지면
        page.insert_text((60, 100), "Hello rotated world", fontsize=11)
        page.set_rotation(rotation)
        data = doc.tobytes()
        doc.close()
        return data

    def test_회전_쪽에서_bbox가_쪽_밖으로_안_나간다(self):
        from app.ai.preprocessor.pdf_analyzer import extract_text_blocks
        blocks, w, h = extract_text_blocks(self._rotated_pdf(), 1)
        assert blocks, "블록이 하나도 없다"
        for b in blocks:
            x0, y0, x1, y1 = b["bbox"]
            assert 0 <= x0 <= x1 <= w + 2, (b["bbox"], w, h)
            assert 0 <= y0 <= y1 <= h + 2, (b["bbox"], w, h)

    def test_회전_없는_쪽은_그대로다(self):
        from app.ai.preprocessor.pdf_analyzer import extract_text_blocks
        blocks, w, h = extract_text_blocks(self._rotated_pdf(0), 1)
        for b in blocks:
            x0, y0, x1, y1 = b["bbox"]
            assert 0 <= x1 <= w + 2 and 0 <= y1 <= h + 2, (b["bbox"], w, h)
