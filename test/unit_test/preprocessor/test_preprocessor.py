

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


class Test문단병합가드:
    """단 오른쪽 끝과 잇지 말아야 할 자리 (2026-08-20, 영역 구분).

    실물 910쪽에서 확인한 두 결함을 못박는다.
      · 꼬리말 한 줄이 단 끝을 부풀려 그 단의 본문이 통째로 과분절됐다 → col_right는 분위수
      · 선택지·보기 표지와 수식 줄이 앞 문단에 붙었다 → _par_blocked
    """

    def test_항목_표지로_시작하면_안_잇는다(self) -> None:
        from app.ai.preprocessor.pdf_analyzer import _par_blocked
        assert _par_blocked("동일한 현상이라도 개별 사회의 특수성을 고려하는 태도", "③   자신의 주장과")
        assert _par_blocked("앞 문장", "ㄱ.\t미량의 신호 물질 X를")
        assert _par_blocked("표 머리", "<!강조>①<!/강조>  <!강조>비슷하다<!/강조>")

    def test_수식_줄은_안_잇는다(self) -> None:
        from app.ai.preprocessor.pdf_analyzer import _par_blocked
        assert _par_blocked("점 C는 선분 BD의 수직이등분선 위의 점이므로", "BCÓ=DCÓ")

    def test_문장_경계는_그대로_잇는다(self) -> None:
        """한 문단 안의 문장 경계까지 끊으면 안 된다 — 실물 표본의 45%가 그 오차단이었다."""
        from app.ai.preprocessor.pdf_analyzer import _par_blocked
        assert not _par_blocked("B는 헌팅턴 무도병이다.", "나머지 A는 낭성 섬유증이고")
        assert not _par_blocked("P의 ㉮~㉰의 유전자형은", "AAXõXºDd이다.")
        assert not _par_blocked("표에서 ⓐ는 여자이고,", "ⓑ는 남자이다.")

    def test_꼬리말이_단_끝을_부풀리지_않는다(self) -> None:
        """좁은 단의 줄들(끝 x=132)에 꼬리말 한 줄(끝 x=160)이 섞여도 문단이 이어져야 한다."""
        from app.ai.preprocessor.pdf_analyzer import _merge_paragraph_blocks
        # ⚠ 줄이 20개는 넘어야 한다. 95분위는 원소가 적으면 정의상 최댓값이라
        #   작은 단에서는 이 보호가 안 걸린다 — 실물 p0008의 그 단은 31줄이었다.
        blocks = [{"content": f"조각{i}", "bbox": [45, 20 + i * 12, 132, 30 + i * 12]}
                  for i in range(24)]
        blocks[-1]["bbox"][2] = 115                              # 문단 마지막 줄은 짧게
        blocks.append({"content": "8  2027학년도 EBS 수능특강", "bbox": [45, 400, 160, 410]})
        out = _merge_paragraph_blocks(blocks)
        assert len(out) == 2, [o["content"] for o in out]        # 문단 하나 + 꼬리말
        assert out[0]["content"].startswith("조각0") and "조각23" in out[0]["content"]
