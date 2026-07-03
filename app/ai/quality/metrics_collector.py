"""메트릭 수집 (PART 11 후반).

페이지 처리 결과에서 운영 메트릭을 뽑아 JSONL로 누적 기록한다.
    storage/metrics/ai_metrics.jsonl  (1줄 = 1페이지 처리)

plan은 TimescaleDB ai_metrics 하이퍼테이블을 지정하지만, DB 미기동 환경(로컬
평가·테스트)에서도 파이프라인이 죽지 않아야 하므로 파일 sink를 기본으로 하고
DB 적재는 배포 인프라 확정 후 sink 교체로 붙인다. 기록 실패는 경고만 남기고
파이프라인에 전파하지 않는다(메트릭은 관측용 — 처리 결과에 영향 금지).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from app.utils.logger import get_logger
from app.utils.req_log import api_counts

logger = get_logger(__name__)

_METRICS_PATH = Path("storage/metrics/ai_metrics.jsonl")


class MetricsCollector:
    """페이지 응답 dict → 메트릭 레코드 추출·기록."""

    def __init__(self, sink_path: Path = _METRICS_PATH) -> None:
        self.sink_path = sink_path

    def build_record(self, result: dict, *, elapsed_ms: int) -> dict:
        qr = result.get("quality_report") or {}
        meta = result.get("processing_meta") or {}
        text_list = result.get("text_list") or []
        api = api_counts()
        n_elements = len(text_list)
        n_blocked = sum(1 for t in text_list if t.get("is_blocked"))
        return {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "job_id": result.get("job_id", ""),
            "page_number": result.get("page_number", 0),
            "status": result.get("status", ""),
            "processing_time_ms": elapsed_ms,
            "routing_tier": meta.get("routing_tier_used", ""),
            "ocr_confidence_avg": qr.get("ocr_confidence_avg", 0.0),
            "line_overflow_rate": qr.get("line_overflow_rate", 0.0),
            "critical_count": len(qr.get("critical_errors") or []),
            "review_count": len(qr.get("review_flags") or []),
            "element_count": n_elements,
            "blocked_element_count": n_blocked,
            "fallback_ratio": (n_blocked / n_elements) if n_elements else 0.0,
            "hcxt_calls": api.get("hcxt", 0),
            "gpt4o_calls": api.get("gpt4o", 0),
        }

    def record(self, result: dict, *, elapsed_ms: int) -> dict:
        """메트릭 레코드를 만들어 sink에 append. 실패해도 예외 전파 안 함."""
        rec = self.build_record(result, elapsed_ms=elapsed_ms)
        try:
            self.sink_path.parent.mkdir(parents=True, exist_ok=True)
            with self.sink_path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("메트릭 기록 실패(무시): %s", exc)
        return rec
