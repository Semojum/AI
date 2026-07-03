"""E1(C9): MinerU 서브 타임아웃 + 텍스트레이어 폴백 — 무거운 페이지 BLOCKED 방지.

무거운 페이지에서 MinerU가 페이지 예산(C7)을 다 태우는 대신:
  ① subprocess 타임아웃으로 추출을 먼저 끊고
  ② 텍스트레이어가 있으면 PyMuPDF 폴백으로 본문을 살려 NEEDS_REVIEW로 응답한다.
"""
import asyncio
import subprocess
from unittest.mock import patch

import fitz
import pytest

from app.core.config import config
from app.schemas.layout import DocumentMeta
from app.schemas.task import PageTask


def _text_pdf_bytes(text: str = "Hello braille fallback test page") -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    page.insert_text((72, 72), text, fontsize=11)
    data = doc.tobytes()
    doc.close()
    return data


class TestMineruTimeout:
    def test_subprocess_timeout_raises_runtimeerror(self, tmp_path):
        from app.ai.parser.mineru_runner import _run_mineru

        def _fake_run(cmd, **kwargs):
            raise subprocess.TimeoutExpired(cmd=cmd, timeout=kwargs.get("timeout"))

        with patch("app.ai.parser.mineru_runner.subprocess.run", _fake_run), \
             patch("app.ai.parser.mineru_service.get_url", return_value=None):
            with pytest.raises(RuntimeError, match="타임아웃"):
                _run_mineru(tmp_path / "x.pdf", tmp_path, 0, timeout=1.0)

    def test_timeout_passed_to_subprocess(self, tmp_path):
        from app.ai.parser.mineru_runner import _run_mineru
        seen = {}

        class _OK:
            returncode = 0

        def _fake_run(cmd, **kwargs):
            seen["timeout"] = kwargs.get("timeout")
            return _OK()

        with patch("app.ai.parser.mineru_runner.subprocess.run", _fake_run), \
             patch("app.ai.parser.mineru_service.get_url", return_value=None):
            _run_mineru(tmp_path / "x.pdf", tmp_path, 0, timeout=123.0)
        assert seen["timeout"] == 123.0

    def test_config_auto_budget(self):
        # 0(자동) → 페이지 예산 - 60초, 최소 60초
        assert config.mineru_timeout_resolved == max(60.0, config.page_timeout_seconds - 60.0)


class TestTextLayerFallback:
    def _meta(self, scan_only: bool) -> DocumentMeta:
        return DocumentMeta(pdf_confidence=0.7, routing_tier="STANDARD", scan_only=scan_only)

    def test_fallback_extracts_text_layer(self):
        from app.core import pipeline

        task = PageTask(job_id="test-mineru-fb", page_no=1, mode="c",
                        pdf_data=_text_pdf_bytes())
        with patch("app.ai.parser.mineru_runner.run",
                   side_effect=RuntimeError("MinerU 추출 타임아웃 (>240s)")):
            elements, w, h = asyncio.run(
                pipeline._extract_via_models(task, self._meta(scan_only=False))
            )
        assert elements, "텍스트레이어 폴백이 요소를 살려야 한다"
        assert all(el["flags"] == ["C2_FALLBACK"] for el in elements)
        assert "Hello" in elements[0]["content"]
        assert w > 0 and h > 0

    def test_scan_only_returns_empty(self):
        from app.core import pipeline

        task = PageTask(job_id="test-mineru-fb", page_no=1, mode="c",
                        pdf_data=_text_pdf_bytes())
        with patch("app.ai.parser.mineru_runner.run",
                   side_effect=RuntimeError("MinerU 실행 실패")):
            elements, w, h = asyncio.run(
                pipeline._extract_via_models(task, self._meta(scan_only=True))
            )
        assert elements == []

    def test_fallback_page_needs_review_e2e(self, tmp_path):
        """폴백 요소(C2_FALLBACK)가 QualityChecker R1 → 페이지 NEEDS_REVIEW로 흐른다."""
        from app.core import pipeline

        task = PageTask(job_id="test-mineru-fb-e2e", page_no=1, mode="c",
                        pdf_data=_text_pdf_bytes())
        # 경계 파일 캐시가 남아 있으면 추출을 건너뛰므로 격리된 job 저장소 사용
        import shutil
        shutil.rmtree("storage/jobs/test-mineru-fb-e2e", ignore_errors=True)

        zero_meta = DocumentMeta(pdf_confidence=0.7, routing_tier="STANDARD", scan_only=False)
        with patch("app.ai.preprocessor.pdf_analyzer.analyze_pdf",
                   return_value=(zero_meta, "")), \
             patch("app.ai.parser.mineru_runner.run",
                   side_effect=RuntimeError("MinerU 추출 타임아웃")):
            result = asyncio.run(pipeline._run_pipeline(task))

        assert result["status"] == "NEEDS_REVIEW", result["quality_report"]
        flags = result["quality_report"]["review_flags"]
        assert any(f["type"] == "R1" for f in flags)
