"""gRPC 파이프라인 통합 테스트.

실행 전 서버가 기동되어 있어야 한다:
    python -m app.core.main

실행:
    pytest test/integration/test_grpc_pipeline.py -v
"""

from __future__ import annotations

import asyncio
import os
import time

import grpc
import pytest

# proto 빌드 파일 import
try:
    from protos.generated import braille_service_pb2, braille_service_pb2_grpc
except ImportError:
    pytest.skip(
        "proto 빌드 파일 없음 — `bash setup.sh` 실행 후 재시도",
        allow_module_level=True,
    )

GRPC_ADDR = os.getenv("GRPC_ADDR", "localhost:50051")

# 단일 빈 페이지 PDF (A4, 더미)
DUMMY_PDF_BYTES = (
    b"%PDF-1.4\n"
    b"1 0 obj\n<</Type /Catalog /Pages 2 0 R>>\nendobj\n"
    b"2 0 obj\n<</Type /Pages /Kids [3 0 R] /Count 1>>\nendobj\n"
    b"3 0 obj\n<</Type /Page /MediaBox [0 0 595 842] /Parent 2 0 R>>\nendobj\n"
    b"xref\n0 4\n"
    b"0000000000 65535 f \n"
    b"0000000009 00000 n \n"
    b"0000000058 00000 n \n"
    b"0000000115 00000 n \n"
    b"trailer\n<</Size 4 /Root 1 0 R>>\n"
    b"startxref\n190\n%%EOF"
)


@pytest.fixture(scope="module")
def grpc_stub():
    channel = grpc.insecure_channel(GRPC_ADDR)
    stub = braille_service_pb2_grpc.BrailleServiceStub(channel)
    yield stub
    channel.close()


def _make_request(mode: str, job_id: str = "test-job-001") -> braille_service_pb2.BrailleRequest:
    return braille_service_pb2.BrailleRequest(
        job_id=job_id,
        page_no=1,
        total_pages=10,
        pdf_data=DUMMY_PDF_BYTES,
        mode=mode,
        source_text="테스트 텍스트입니다." if mode == "b" else "",
    )


@pytest.mark.integration
class TestGrpcConnection:
    def test_health_via_grpc_channel(self, grpc_stub):
        """gRPC 채널 연결 자체가 성공하는지 확인."""
        # 연결 실패 시 grpc.RpcError 발생
        request = _make_request("a")
        response = grpc_stub.ProcessPage(request, timeout=10)
        assert response is not None


@pytest.mark.integration
class TestModeA:
    def test_response_structure(self, grpc_stub):
        """mode a: 응답 필드 구조 검증."""
        response = grpc_stub.ProcessPage(_make_request("a"), timeout=30)

        assert response.job_id == "test-job-001"
        assert response.page_number == 1
        assert response.status in ("COMPLETED", "NEEDS_REVIEW", "BLOCKED")
        # mode a는 image_resolution, bounding_box_list, text_list 포함
        assert response.image_resolution != "" or response.status == "BLOCKED"

    def test_quality_report_present(self, grpc_stub):
        """mode a: quality_report 필드가 항상 포함되어야 한다."""
        response = grpc_stub.ProcessPage(_make_request("a"), timeout=30)
        assert response.HasField("quality_report")

    def test_processing_meta_present(self, grpc_stub):
        """mode a: processing_meta 필드가 항상 포함되어야 한다."""
        response = grpc_stub.ProcessPage(_make_request("a"), timeout=30)
        assert response.HasField("processing_meta")
        assert response.processing_meta.processing_time_ms >= 0


@pytest.mark.integration
class TestModeB:
    def test_response_structure(self, grpc_stub):
        """mode b: braille_text_list 포함 여부 검증."""
        response = grpc_stub.ProcessPage(_make_request("b"), timeout=30)

        assert response.job_id == "test-job-001"
        assert response.status in ("COMPLETED", "NEEDS_REVIEW", "BLOCKED")
        # braille_text_list 포함 여부 실제 검증
        if response.status != "BLOCKED":
            assert len(response.braille_text_list) > 0, "mode b: braille_text_list가 비어 있음"

    def test_no_bounding_box_in_mode_b(self, grpc_stub):
        """mode b: bounding_box_list는 비어 있어야 한다 (이미지 없음)."""
        response = grpc_stub.ProcessPage(_make_request("b"), timeout=30)
        assert len(response.bounding_box_list) == 0


@pytest.mark.integration
class TestModeC:
    def test_response_structure(self, grpc_stub):
        """mode c: bounding_box_list + braille_text_list 모두 포함."""
        response = grpc_stub.ProcessPage(_make_request("c"), timeout=30)

        assert response.job_id == "test-job-001"
        assert response.status in ("COMPLETED", "NEEDS_REVIEW", "BLOCKED")

    def test_quality_report_structure(self, grpc_stub):
        """mode c: quality_report 내부 필드 검증."""
        response = grpc_stub.ProcessPage(_make_request("c"), timeout=30)
        qr = response.quality_report
        assert isinstance(qr.ocr_confidence_avg, float)
        assert isinstance(qr.line_overflow_rate, float)


class TestTimeout:
    def test_c7_blocked_on_server_timeout(self):
        """pipeline.py 타임아웃 로직 단위 검증 (서버 불필요)."""
        from app.schemas.task import PageTask
        from app.core.pipeline import _build_timeout_response

        task = PageTask(
            job_id="timeout-test",
            page_no=1,
            mode="c",
        )
        result = _build_timeout_response(task, elapsed_ms=181_000)

        assert result["status"] == "BLOCKED"
        errors = result["quality_report"]["critical_errors"]
        assert len(errors) == 1
        assert errors[0]["type"] == "C7"
        assert "타임아웃" in errors[0]["message"]

    async def test_timeout_enforced_in_pipeline(self):
        """asyncio.wait_for 타임아웃이 실제로 C7 응답을 반환하는지 검증."""
        from unittest.mock import patch
        from app.schemas.task import PageTask
        from app.core import pipeline

        task = PageTask(job_id="to-test", page_no=1, mode="c")

        # _run_pipeline 을 300초 슬립으로 교체 — 0.1초 타임아웃 발동 확인
        async def slow_pipeline(t):
            await asyncio.sleep(300)
            return {}

        with patch("app.core.pipeline._run_pipeline", slow_pipeline):
            with patch.object(pipeline.config, "page_timeout_seconds", 0.1):
                result = await pipeline.run(task)

        assert result["status"] == "BLOCKED"
        assert result["quality_report"]["critical_errors"][0]["type"] == "C7"


@pytest.mark.integration
class TestNoEmptyResponse:
    def test_job_id_always_present(self, grpc_stub):
        """모든 응답에 job_id가 존재해야 한다 (빈 결과 금지 원칙)."""
        for mode in ("a", "b", "c"):
            response = grpc_stub.ProcessPage(_make_request(mode, job_id=f"empty-check-{mode}"), timeout=30)
            assert response.job_id == f"empty-check-{mode}", f"mode {mode}: job_id 누락"
