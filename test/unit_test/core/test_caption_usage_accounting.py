"""캡셔닝 원가 집계 구멍 — 풀 스레드로 간 호출이 사라지던 것 (2026-08-23 실측).

`req_log`는 요청 통계를 `contextvars`에 담는데 `ThreadPoolExecutor.submit`은 컨텍스트를
전파하지 않는다. 그래서 시각 요소가 **둘 이상**인 쪽의 캡셔닝·분류 호출이 통째로
집계에서 빠졌다(요소가 하나인 쪽은 부르는 스레드에서 그대로 돌아 집계됐다).

실측 dev 100쪽 재추출: 크롭 72장 → 기대 호출 144건인데 `usage` 에 잡힌 것은 32건뿐이고
캡션 캐시 파일은 142개가 쌓였다. 그만큼 원가 보고가 과소였다.
"""
from __future__ import annotations

from unittest.mock import patch

import app.utils.req_log as rl
from app.ai.builder import result_builder as RB


def _fake_caption(el: dict):
    """실제 API 대신 사용량만 기록한다 — 이 테스트가 보는 것은 집계뿐이다."""
    rl.record_llm("캡셔닝", "claude-sonnet-5", 100, 10)
    return ("그림: 하나", el["type"], True, None)


class TestCaptionUsageReachesRequestStats:
    def _run(self, n_elements: int, workers: str) -> int:
        rl.start_request()
        vis = [{"type": "image", "element_id": f"e{i}", "image_path": f"/x/{i}.jpg"}
               for i in range(n_elements)]
        with patch.object(RB, "_do_caption_logged", _fake_caption), \
             patch.dict("os.environ", {"CAPTION_CONCURRENCY": workers}), \
             patch.object(RB, "log_backend_status", lambda *a, **k: None):
            RB._caption_all(vis)
        return rl.usage_report().get("models", [{}])[0].get("calls", 0)

    def test_한_요소는_종전에도_잡혔다(self) -> None:
        assert self._run(1, "4") == 1

    def test_여러_요소도_잡힌다(self) -> None:
        """이 줄이 깨지면 원가 보고가 다시 과소가 된다 — 조용히 틀리는 자리다."""
        assert self._run(4, "4") == 4
