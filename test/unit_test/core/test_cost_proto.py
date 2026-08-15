"""CostReport proto 계약 회귀 — **BE와의 약속이라 조용히 바뀌면 안 된다.**

여기서 지키는 것은 "값이 맞나"가 아니라 "계약이 그대로인가"다. 필드가 사라지거나
축이 뭉개지거나 단위가 바뀌면 BE 대시보드가 말없이 틀린 숫자를 보여준다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "protos" / "generated"))

import braille_service_pb2 as pb  # noqa: E402

import app.utils.req_log as rl  # noqa: E402
from app.core.grpc_server import _build_proto_response  # noqa: E402


def _resp(status="COMPLETED"):
    return _build_proto_response(
        {"job_id": "j", "status": status, "page_number": 1, "cost": rl.cost_report()})


class TestReprice:
    """단가가 틀렸을 때 **과거 데이터를 다시 계산할 수 있어야 한다.**

    실제로 Claude를 부르면서 gpt-4o 단가를 곱하던 버그가 있었다(issue #176).
    금액만 저장했다면 그 값이 영구히 남았을 것이다.
    """

    def test_파트가_같아도_모델이_다르면_따로_남는다(self):
        # 캡셔닝이 sonnet으로 돌다 opus로 폴백하는 실제 경로.
        # 파트로만 묶으면 토큰이 뭉개져 청구서(모델별)와 대조가 안 된다.
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        rl.record_llm("캡셔닝", "claude-opus-4-8", 4000, 600)
        entries = _resp().cost_report.entries
        assert len(entries) == 2, "모델별로 갈려야 한다"
        assert {e.model for e in entries} == {"claude-sonnet-5", "claude-opus-4-8"}
        assert all(e.part == pb.COST_PART_CAPTION for e in entries)
        by_model = {e.model: e for e in entries}
        assert by_model["claude-sonnet-5"].input_tokens == 3131
        assert by_model["claude-opus-4-8"].output_tokens == 600

    def test_토큰이_그대로_실린다(self):
        """BE가 이 값으로 재계산한다 — 반올림하거나 뭉개면 안 된다."""
        rl.start_request()
        rl.record_llm("분류", "claude-sonnet-5", 2900, 3, 100, 50)
        e = _resp().cost_report.entries[0]
        assert (e.input_tokens, e.output_tokens) == (2900, 3)
        assert (e.cache_read_tokens, e.cache_write_tokens) == (100, 50)
        assert e.calls == 1


class TestUnits:
    def test_금액은_나노_정수다(self):
        """센트·원으로 반올림하면 10만 쪽에서 수만 원이 어긋난다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)   # $0.007472
        c = _resp().cost_report
        assert c.llm_cost_usd_nanos == 7_472_000
        assert isinstance(c.llm_cost_usd_nanos, int)
        assert c.llm_cost_krw_nanos > 0                        # 원화도 소수 유지

    def test_GPU는_LLM과_섞이지_않는다(self):
        """인스턴스는 놀아도 24시간 과금된다 — 안분값을 API 원가와 합치면 둘 다 못 믿는다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 100, 10)
        rl.record_hcxt("텍스트", 5.0)
        c = _resp().cost_report
        assert c.llm_cost_usd_nanos > 0 and c.gpu_cost_usd_nanos > 0
        assert len(c.entries) == 1 and len(c.gpu) == 1
        assert c.gpu[0].busy_millis == 5000
        assert c.gpu[0].part == pb.COST_PART_TEXT


class TestContract:
    def test_막힌_쪽에도_원가가_실린다(self):
        """BLOCKED여도 API는 이미 불렀다 — 돈은 나갔다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        assert _resp("BLOCKED").cost_report.llm_cost_usd_nanos > 0

    def test_LLM을_안_쓴_쪽도_메시지는_온다(self):
        """안 보내는 것과 0원인 것은 다르다. BE가 그 둘을 구분하려 애쓸 이유가 없다."""
        rl.start_request()
        c = _resp().cost_report
        assert c.llm_cost_usd_nanos == 0 and len(c.entries) == 0
        assert c.pricing_version, "단가표 판은 늘 실린다"

    def test_환산_근거가_함께_온다(self):
        """청구서와 어긋났을 때 무엇을 의심할지 알 수 있어야 한다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 100, 10)
        c = _resp().cost_report
        assert c.fx_rate > 0 and c.card_markup >= 1.0
        assert c.fx_basis != pb.FX_BASIS_UNSPECIFIED
        assert c.request_started_at_ms > 0, "재시도를 구분할 수 있어야 한다"

    def test_모르는_파트는_OTHER로_떨어지고_값은_안_잃는다(self):
        rl.start_request()
        rl.record_llm("아직없는파트", "claude-sonnet-5", 100, 10)
        e = _resp().cost_report.entries[0]
        assert e.part == pb.COST_PART_OTHER and e.input_tokens == 100

    def test_단가표에_없는_모델은_추정치로_표시된다(self):
        """조용히 0원으로 새거나, 추정치를 사실인 양 내보내면 안 된다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-지어낸-9", 1000, 100)
        e = _resp().cost_report.entries[0]
        assert e.unpriced is True and e.cost_usd_nanos > 0

    def test_원가가_터져도_응답은_나간다(self, monkeypatch):
        monkeypatch.setattr(rl, "_totals",
                            lambda: (_ for _ in ()).throw(RuntimeError("집계 폭발")))
        rl.start_request()
        r = _resp()
        assert r.status == "COMPLETED"          # 페이지는 살아 있다
        assert r.cost_report.llm_cost_usd_nanos == 0
