"""UsageReport proto 계약 회귀 — **BE와의 약속이라 조용히 바뀌면 안 된다.**

★ 금액은 나가지 않는다(BE 협의 2026-08-18, 구 CostReport 대체). AI 소관은 **측정값 셋**뿐이다:
  · layout_type   쪽 대표 유형 (크레딧 배율의 축)
  · models        모델별 토큰 (BE 단가표와 곱한다)
  · gpu_time_ms   로컬 GPU 점유 시간 (BE 시간당 단가와 곱한다)
단가표·환율·카드 수수료·크레딧 배율은 BE의 관리 변수다 — 관리자 페이지에서 수시로 바뀌는
값이라 AI에 두면 재배포해야 바뀐다. AI 쪽 원가 추정치는 메트릭 JSONL에만 남는다(정본 아님).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "protos" / "generated"))

import braille_service_pb2 as pb  # noqa: E402

import app.utils.req_log as rl  # noqa: E402
from app.core.grpc_server import _build_proto_response  # noqa: E402
from app.core.pipeline import _page_layout_type  # noqa: E402


def _resp(status="COMPLETED", text_list=None):
    result = {"job_id": "j", "status": status, "page_number": 1,
              "text_list": text_list or []}
    result["usage"] = {**rl.usage_report(), "layout_type": _page_layout_type(result)}
    return _build_proto_response(result)


class TestNoMoney:
    """금액 필드가 되살아나면 계약 위반이다 — BE가 두 번 계산하게 된다."""

    def test_금액_필드가_없다(self):
        names = {f.name for f in pb.UsageReport.DESCRIPTOR.fields}
        assert names == {"layout_type", "models", "gpu_time_ms"}, names

    def test_구_CostReport는_사라졌다(self):
        assert not hasattr(pb, "CostReport")
        assert "cost_report" not in {f.name for f in pb.BrailleResponse.DESCRIPTOR.fields}


class TestLayoutType:
    """크레딧 배율의 축. 한 쪽에 섞여 있으면 **비싼 쪽이 이긴다**.

    실측 원가가 그림 94 > 표 58 > 수식 46 > 본문 21원/쪽이라 이 순서다.
    개수로 세면 비싼 요소가 본문에 묻혀 유형별 평균이 흐려진다.
    """

    def test_그림이_하나라도_있으면_그림_쪽이다(self):
        rl.start_request()
        c = _resp(text_list=[{"type": "text"}] * 8 + [{"type": "table"}, {"type": "image"}])
        assert c.usage_report.layout_type == pb.PAGE_LAYOUT_VISUAL

    def test_그림이_없으면_표(self):
        rl.start_request()
        c = _resp(text_list=[{"type": "text"}] * 8 + [{"type": "table"}])
        assert c.usage_report.layout_type == pb.PAGE_LAYOUT_TABLE

    def test_수식과_본문(self):
        rl.start_request()
        assert _resp(text_list=[{"type": "text"}, {"type": "formula"}]).usage_report.layout_type \
            == pb.PAGE_LAYOUT_FORMULA
        assert _resp(text_list=[{"type": "text"}]).usage_report.layout_type \
            == pb.PAGE_LAYOUT_TEXT

    def test_시각_4종은_모두_그림으로_묶인다(self):
        for t in ("image", "cartoon", "chart_graph", "diagram"):
            rl.start_request()
            assert _resp(text_list=[{"type": t}]).usage_report.layout_type \
                == pb.PAGE_LAYOUT_VISUAL, t

    def test_요소가_없으면_미정(self):
        """BLOCKED 쪽 — 유형을 지어내지 않는다. BE는 이 값에 크레딧 0을 매긴다."""
        rl.start_request()
        assert _resp("BLOCKED").usage_report.layout_type == pb.PAGE_LAYOUT_UNSPECIFIED


class TestModels:
    """BE가 단가표와 곱할 원본. 축이 모델인 이유는 **청구서가 모델별로 나오기 때문**이다.

    금액이 아니라 토큰을 보내므로, 단가가 틀렸던 게 나중에 드러나도 **과거 데이터를
    다시 계산할 수 있다**(실제로 Claude를 부르며 gpt-4o 단가를 곱하던 버그가 있었다, #176).
    """

    def test_모델별로_갈린다(self):
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        rl.record_llm("opus추출", "claude-opus-4-8", 4000, 600)
        models = {m.model: m for m in _resp().usage_report.models}
        assert set(models) == {"claude-sonnet-5", "claude-opus-4-8"}
        assert models["claude-opus-4-8"].output_tokens == 600

    def test_같은_모델은_파트가_달라도_합쳐진다(self):
        """파트 축은 proto로 안 나간다 — BE가 안 쓴다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        rl.record_llm("분류", "claude-sonnet-5", 2900, 3)
        models = _resp().usage_report.models
        assert len(models) == 1
        assert models[0].calls == 2
        assert models[0].input_tokens == 6031 and models[0].output_tokens == 124


class TestGpuTime:
    def test_GPU는_밀리초로_보낸다(self):
        """BE가 곱셈만 하면 되게 ms로 준다 — GPU 원가 = 이 값 × 시간당 단가."""
        rl.start_request()
        rl.record_hcxt("텍스트", 5.0)
        assert _resp().usage_report.gpu_time_ms == 5000

    def test_LLM만_쓴_쪽은_GPU가_0이다(self):
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 100, 10)
        u = _resp().usage_report
        assert u.gpu_time_ms == 0 and len(u.models) == 1


class TestContract:
    def test_막힌_쪽에도_사용량이_실린다(self):
        """BLOCKED여도 API는 이미 불렀다 — 자원은 썼다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        assert _resp("BLOCKED").usage_report.models[0].input_tokens == 3131

    def test_LLM을_안_쓴_쪽도_메시지는_온다(self):
        """안 보내는 것과 0인 것은 다르다. BE가 그 둘을 구분하려 애쓸 이유가 없다."""
        rl.start_request()
        u = _resp(text_list=[{"type": "text"}]).usage_report
        assert len(u.models) == 0 and u.gpu_time_ms == 0
        assert u.layout_type == pb.PAGE_LAYOUT_TEXT

    def test_집계가_터져도_응답은_나간다(self, monkeypatch):
        monkeypatch.setattr(rl, "_totals",
                            lambda: (_ for _ in ()).throw(RuntimeError("집계 폭발")))
        rl.start_request()
        r = _resp()
        assert r.status == "COMPLETED"          # 페이지는 살아 있다
        assert len(r.usage_report.models) == 0

    def test_페이로드가_작다(self):
        """쪽마다 붙는 값이라 커지면 안 된다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        rl.record_llm("opus추출", "claude-opus-4-8", 4000, 600)
        rl.record_hcxt("텍스트", 5.0)
        n = len(_resp(text_list=[{"type": "image"}]).SerializeToString())
        assert n < 200, f"{n} bytes — 계약이 다시 부풀었다"


class TestBlockedPath:
    """하드 오류 경로(`_build_error_response`)도 사용량을 싣는다.

    파이프라인이 자체 예외 처리(C1·C7)를 못 하고 통째로 터진 자리다. 드물지만 그때도
    LLM은 이미 불렸을 수 있고, proto가 "BLOCKED에도 실림"이라고 약속한다.
    """

    def test_파이프라인이_터져도_쓴_토큰은_실린다(self):
        from app.core.grpc_server import _build_error_response
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        rl.record_hcxt("텍스트", 2.0)
        r = _build_error_response("j", 1, "파이프라인 오류: RuntimeError: 폭발")
        assert r.status == "BLOCKED"
        assert r.usage_report.models[0].input_tokens == 3131
        assert r.usage_report.gpu_time_ms == 2000
        # 요소를 못 봤으니 유형은 지어내지 않는다
        assert r.usage_report.layout_type == pb.PAGE_LAYOUT_UNSPECIFIED
