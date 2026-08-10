"""PDF 도착 바이트 진단·방어 + PUA 라우팅 회귀 테스트.

BE↔AI 전송 변질(base64·경로문자열·빈/garbage)을 사람이 읽는 메시지로 진단하고,
base64는 자동복구한다. PUA 과다 텍스트레이어는 STANDARD(MinerU)로 라우팅한다.
"""
import base64

import fitz
import pytest

from app.ai.preprocessor.pdf_analyzer import (
    InvalidPDFError,
    _coerce_pdf_bytes,
    _pua_ratio,
    analyze_pdf,
    diagnose_pdf_bytes,
    mangled_glyph_chars,
)


def _make_pdf(text: str) -> bytes:
    d = fitz.open()
    p = d.new_page()
    p.insert_text((72, 72), text)
    return d.tobytes()


VALID = _make_pdf("안녕하세요 점자 테스트 문서입니다 abc 123")


class TestDiagnose:
    def test_유효pdf_통과(self):
        assert diagnose_pdf_bytes(VALID) is None

    def test_base64_탐지(self):
        msg = diagnose_pdf_bytes(base64.b64encode(VALID))
        assert msg and "base64" in msg

    def test_빈데이터(self):
        assert "길이 0" in diagnose_pdf_bytes(b"")

    def test_경로문자열(self):
        assert "경로" in diagnose_pdf_bytes(b"/home/user/file.pdf")

    def test_garbage(self):
        assert "매직" in diagnose_pdf_bytes(b"\x89PNG\r\n\x1a\nrandom")


class TestCoerce:
    def test_base64_자동복구(self):
        out = _coerce_pdf_bytes(base64.b64encode(VALID))
        assert out[:5] == b"%PDF-"

    def test_garbage_거부(self):
        with pytest.raises(InvalidPDFError):
            _coerce_pdf_bytes(b"not a pdf at all")

    def test_빈_거부(self):
        with pytest.raises(InvalidPDFError):
            _coerce_pdf_bytes(b"")


class TestMangledGlyphs:
    """글꼴 매핑이 어긋난 PDF 탐지 (2026-08-09). PUA는 0%인데 글자가 틀리는 유형.

    표본은 전부 코퍼스 1,131쪽에서 **렌더로 눈 확인**한 실물이다 —
    수학2 `x¤`=x² · STkyak `…`=≤ · STkboNA `∂`=√ · 외국어 `䤋`=글머리 기호.
    """

    def test_정상_교과서_문자는_안_걸린다(self):
        # ° · × ÷ … ‘’ ① ㉠ → ★ □ ℃ 한자(U+4E00~)는 본문 글꼴에서 정상으로 나온다.
        ok = "사회·문화 25°C A×B÷C … ‘보기’ ① ㉠ → ★ □ ℃ 因果關係 abc 123"
        layer, symbol = mangled_glyph_chars(ok)
        assert not layer and not symbol

    def test_수식글꼴_깨짐은_레이어_폐기(self):
        # 수학2 p004 실물: `x¤ -4` = x²-4 (¤ = 윗첨자 2)
        layer, _ = mangled_glyph_chars("다음분수방정식의근을구하시오 x¤ -4")
        assert layer == {"¤": 1}

    def test_기호만_어긋난_것은_레이어_폐기_아님(self):
        # 외국어 p012 실물: `䤋compress 압축하다` — 글머리 기호가 한자 확장A 자리로.
        layer, symbol = mangled_glyph_chars("䤋compress 압축하다")
        assert not layer          # 본문은 멀쩡 → STANDARD로 돌리지 않는다
        assert symbol == {"䤋": 1}

    def test_매핑없는_glyph는_레이어_폐기(self):
        layer, _ = mangled_glyph_chars("갑국\x00A 집단")
        assert layer == {"\x00": 1}

    def test_라우팅_STANDARD로_바뀐다(self):
        # ¤ 한 글자만 있어도 그 쪽 텍스트레이어는 못 믿는다(비율은 1% 미만이다).
        meta, text = analyze_pdf(_make_pdf("분수방정식의 근을 구하시오 x¤ -4 " * 3), 1)
        assert meta.routing_tier == "STANDARD"
        assert text == ""


class TestPUARouting:
    def test_pua비율(self):
        assert _pua_ratio("abc") == 0.0
        assert _pua_ratio(chr(0xE000) + "a") == pytest.approx(0.5)

    def test_정상텍스트_ZERO(self):
        meta, text = analyze_pdf(VALID, 1)
        assert meta.routing_tier == "ZERO"
        assert text

    def test_PUA과다_임계초과(self):
        # 실 PDF(수능수학)는 PUA 28~46% → 임계(10%) 초과로 STANDARD 라우팅됨(E2E 검증).
        # 여기선 _pua_ratio가 임계를 넘기는지 단위로 확인(라우팅 분기 입력).
        from app.ai.preprocessor.pdf_analyzer import PUA_RATIO_THRESHOLD
        pua_text = "".join(chr(0xE000 + i % 100) for i in range(40)) + "가나다라"
        assert _pua_ratio(pua_text) >= PUA_RATIO_THRESHOLD

    def test_base64로_와도_분석성공(self):
        meta, text = analyze_pdf(base64.b64encode(VALID), 1)
        assert meta.routing_tier == "ZERO" and text


class TestSinglePagePageNo:
    """proto상 pdf_data는 단일 페이지. page_no>1이어도 IndexError 없이 그 페이지를 읽어야."""

    def test_단일페이지_page_no_2_무예외(self):
        # BE는 페이지마다 1장 PDF를 보내며 page_no는 원본 페이지 번호
        meta, text = analyze_pdf(VALID, page_no=2)  # 이전엔 IndexError: page 1 not in document
        assert meta.routing_tier == "ZERO" and text

    def test_단일페이지_큰_page_no_무예외(self):
        meta, _ = analyze_pdf(VALID, page_no=99)
        assert meta.routing_tier in ("ZERO", "STANDARD")

    def test_멀티페이지_page_no로_해당페이지(self):
        # ASCII 내용(기본 폰트가 한글을 임베드 못 해 추출이 깨지는 것 회피)으로 페이지 구분 확인
        d = fitz.open()
        for i in range(3):
            d.new_page().insert_text((72, 72), f"this is page number {i + 1} content body")
        multi = d.tobytes()
        d.close()
        _, t2 = analyze_pdf(multi, page_no=2)
        _, t3 = analyze_pdf(multi, page_no=3)
        assert "page number 2" in t2 and "page number 3" in t3
