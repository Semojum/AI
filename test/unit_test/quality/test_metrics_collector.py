"""PART 11 후반 MetricsCollector — 레코드 추출·JSONL 기록·비전파."""
import json

from app.ai.quality.metrics_collector import MetricsCollector


def _result(status="COMPLETED"):
    return {
        "job_id": "job-1",
        "status": status,
        "page_number": 3,
        "processing_meta": {"routing_tier_used": "ZERO"},
        "quality_report": {
            "ocr_confidence_avg": 0.97,
            "line_overflow_rate": 0.02,
            "critical_errors": [{"type": "C2"}],
            "review_flags": [],
        },
        "text_list": [
            {"is_blocked": False},
            {"is_blocked": True},
        ],
    }


class TestBuildRecord:
    def test_fields(self):
        rec = MetricsCollector().build_record(_result(), elapsed_ms=1234)
        assert rec["job_id"] == "job-1"
        assert rec["page_number"] == 3
        assert rec["status"] == "COMPLETED"
        assert rec["processing_time_ms"] == 1234
        assert rec["routing_tier"] == "ZERO"
        assert rec["critical_count"] == 1
        assert rec["element_count"] == 2
        assert rec["blocked_element_count"] == 1
        assert rec["fallback_ratio"] == 0.5

    def test_empty_result_safe(self):
        rec = MetricsCollector().build_record({}, elapsed_ms=0)
        assert rec["element_count"] == 0
        assert rec["fallback_ratio"] == 0.0


class TestRecord:
    def test_appends_jsonl(self, tmp_path):
        sink = tmp_path / "m.jsonl"
        col = MetricsCollector(sink_path=sink)
        col.record(_result(), elapsed_ms=10)
        col.record(_result("BLOCKED"), elapsed_ms=20)
        lines = sink.read_text(encoding="utf-8").strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[1])["status"] == "BLOCKED"

    def test_sink_failure_not_raised(self, tmp_path):
        # 디렉토리 경로를 sink로 → OSError. 예외가 전파되면 안 된다.
        col = MetricsCollector(sink_path=tmp_path)
        rec = col.record(_result(), elapsed_ms=10)
        assert rec["job_id"] == "job-1"
