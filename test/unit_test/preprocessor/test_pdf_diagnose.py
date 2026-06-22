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
