"""gRPC 배압(M2, 2026-08-02) 단위 테스트 — 동시 처리 상한 admission 제어.

상한 초과 시 gRPC 큐에 조용히 세우는 대신 즉시 RESOURCE_EXHAUSTED로 거절하는지,
상한 이하일 때는 정상 처리되고 _in_flight가 원복되는지 확인한다.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import grpc
import pytest

from app.core import grpc_server
from app.core.config import config
from protos.generated import braille_service_pb2


def _make_request(job_id: str = "test-job") -> braille_service_pb2.BrailleRequest:
    return braille_service_pb2.BrailleRequest(
        job_id=job_id, page_no=1, total_pages=1, pdf_data=b"", mode="b", source_text="x",
    )


def _make_context() -> MagicMock:
    # grpc.aio.ServicerContext.peer()는 동기 메서드, abort()는 코루틴 — 실제 API와 맞춘다.
    ctx = MagicMock()
    ctx.peer.return_value = "ipv4:127.0.0.1:1234"
    ctx.abort = AsyncMock()
    return ctx


@pytest.fixture(autouse=True)
def _reset_in_flight():
    """모듈 전역 카운터는 테스트 간 공유되므로 매 테스트 후 0으로 되돌린다."""
    grpc_server._in_flight = 0
    yield
    grpc_server._in_flight = 0


class TestBackpressure:
    @pytest.mark.asyncio
    async def test_rejects_when_at_cap(self):
        grpc_server._in_flight = config.max_concurrent_pages
        servicer = grpc_server.BrailleServiceServicer()
        context = _make_context()

        with patch.object(grpc_server.pipeline, "run", new=AsyncMock()) as mock_run:
            await servicer.ProcessPage(_make_request(), context)

        context.abort.assert_awaited_once()
        args, _ = context.abort.await_args
        assert args[0] == grpc.StatusCode.RESOURCE_EXHAUSTED
        mock_run.assert_not_called()
        # 거절 경로는 admission 전에 빠지므로 카운터가 늘어난 채로 남지 않는다.
        assert grpc_server._in_flight == config.max_concurrent_pages

    @pytest.mark.asyncio
    async def test_allows_when_under_cap_and_releases_slot(self):
        grpc_server._in_flight = 0
        servicer = grpc_server.BrailleServiceServicer()
        context = _make_context()

        fake_result = {
            "job_id": "test-job", "status": "COMPLETED", "page_number": 1,
            "text_list": [], "braille_text_list": [],
        }
        with patch.object(grpc_server.pipeline, "run", new=AsyncMock(return_value=fake_result)) as mock_run:
            resp = await servicer.ProcessPage(_make_request(), context)

        mock_run.assert_awaited_once()
        context.abort.assert_not_awaited()
        assert resp.job_id == "test-job"
        # 처리 완료 후 슬롯이 반납되어야 다음 요청을 받을 수 있다.
        assert grpc_server._in_flight == 0

    @pytest.mark.asyncio
    async def test_slot_released_even_on_pipeline_error(self):
        grpc_server._in_flight = 0
        servicer = grpc_server.BrailleServiceServicer()
        context = _make_context()

        with patch.object(grpc_server.pipeline, "run", new=AsyncMock(side_effect=RuntimeError("boom"))):
            resp = await servicer.ProcessPage(_make_request(), context)

        assert resp.status == "BLOCKED"  # _build_error_response 경로
        assert grpc_server._in_flight == 0
