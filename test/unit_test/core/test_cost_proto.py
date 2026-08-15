"""CostReport proto 계약 회귀 — **BE와의 약속이라 조용히 바뀌면 안 된다.**

기획서(관리자 대시보드 V11)가 AI 소관으로 못 박은 것은 셋뿐이다:
  · 쪽별 원가          → 금액 필드
  · 쪽 대표 레이아웃 유형 → layout_type (T1-2 유형별 평균 원가 · T1-4 쪽별 결과 표)
  · 원가 환산 단가표     → pricing.py (AI 내부)
그 밖의 것을 proto에 얹지 않는다. 파트별 내역·환율 근거는 메트릭 JSONL에만 남긴다.
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
    result["cost"] = {**rl.cost_report(), "layout_type": _page_layout_type(result)}
    return _build_proto_response(result)


class TestLayoutType:
    """대시보드 집계 축. 한 쪽에 섞여 있으면 **비싼 쪽이 이긴다**.

    실측 원가가 그림 94 > 표 58 > 수식 46 > 본문 21원/쪽이라 이 순서다.
    개수로 세면 비싼 요소가 본문에 묻혀 유형별 평균이 흐려진다.
    """

    def test_그림이_하나라도_있으면_그림_쪽이다(self):
        rl.start_request()
        c = _resp(text_list=[{"type": "text"}] * 8 + [{"type": "table"}, {"type": "image"}])
        assert c.cost_report.layout_type == pb.PAGE_LAYOUT_VISUAL

    def test_그림이_없으면_표(self):
        rl.start_request()
        c = _resp(text_list=[{"type": "text"}] * 8 + [{"type": "table"}])
        assert c.cost_report.layout_type == pb.PAGE_LAYOUT_TABLE

    def test_수식과_본문(self):
        rl.start_request()
        assert _resp(text_list=[{"type": "text"}, {"type": "formula"}]).cost_report.layout_type \
            == pb.PAGE_LAYOUT_FORMULA
        assert _resp(text_list=[{"type": "text"}]).cost_report.layout_type \
            == pb.PAGE_LAYOUT_TEXT

    def test_시각_4종은_모두_그림으로_묶인다(self):
        for t in ("image", "cartoon", "chart_graph", "diagram"):
            rl.start_request()
            assert _resp(text_list=[{"type": t}]).cost_report.layout_type \
                == pb.PAGE_LAYOUT_VISUAL, t

    def test_요소가_없으면_미정(self):
        """BLOCKED 쪽 — 유형을 지어내지 않는다."""
        rl.start_request()
        assert _resp("BLOCKED").cost_report.layout_type == pb.PAGE_LAYOUT_UNSPECIFIED


class TestReprice:
    """단가가 틀렸을 때 **과거 데이터를 다시 계산할 수 있어야 한다.**

    실제로 Claude를 부르면서 gpt-4o 단가를 곱하던 버그가 있었다(issue #176).
    금액만 저장했다면 그 값이 영구히 남았을 것이다. BE는 평상시 이 값으로 계산하지
    않는다 — 보관용이다(기획서: "백엔드는 저장하고 더하기만 합니다").
    """

    def test_모델별로_갈린다(self):
        """축이 모델인 이유는 **청구서가 모델별로 나오기 때문**이다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        rl.record_llm("opus추출", "claude-opus-4-8", 4000, 600)
        models = {m.model: m for m in _resp().cost_report.models}
        assert set(models) == {"claude-sonnet-5", "claude-opus-4-8"}
        assert models["claude-opus-4-8"].output_tokens == 600

    def test_같은_모델은_파트가_달라도_합쳐진다(self):
        """파트 축은 proto로 안 나간다 — 대시보드가 안 쓴다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        rl.record_llm("분류", "claude-sonnet-5", 2900, 3)
        models = _resp().cost_report.models
        assert len(models) == 1
        assert models[0].calls == 2
        assert models[0].input_tokens == 6031 and models[0].output_tokens == 124


class TestUnits:
    def test_USD는_나노_원은_밀리다(self):
        """쪽당 ₩21~94이라 원 단위로 반올림하면 수만 쪽에서 눈에 띄게 어긋난다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)   # $0.007472
        c = _resp().cost_report
        assert c.llm_cost_usd_nanos == 7_472_000
        assert c.cost_krw_milli > 0 and isinstance(c.cost_krw_milli, int)

    def test_GPU는_따로_낸다(self):
        """인스턴스는 놀아도 24시간 과금된다 — 합치면 어느 쪽도 청구서와 못 맞춘다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 100, 10)
        rl.record_hcxt("텍스트", 5.0)
        c = _resp().cost_report
        assert c.llm_cost_usd_nanos > 0 and c.gpu_cost_usd_nanos > 0
        assert c.cost_krw_milli > 0          # 화면 표시용 총액은 둘을 합친 값


class TestContract:
    def test_막힌_쪽에도_원가가_실린다(self):
        """BLOCKED여도 API는 이미 불렀다 — 돈은 나갔다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        assert _resp("BLOCKED").cost_report.llm_cost_usd_nanos > 0

    def test_LLM을_안_쓴_쪽도_메시지는_온다(self):
        """안 보내는 것과 0원인 것은 다르다. BE가 그 둘을 구분하려 애쓸 이유가 없다."""
        rl.start_request()
        c = _resp(text_list=[{"type": "text"}]).cost_report
        assert c.llm_cost_usd_nanos == 0 and len(c.models) == 0
        assert c.pricing_version, "단가표 판은 늘 실린다"
        assert c.layout_type == pb.PAGE_LAYOUT_TEXT

    def test_원가가_터져도_응답은_나간다(self, monkeypatch):
        monkeypatch.setattr(rl, "_totals",
                            lambda: (_ for _ in ()).throw(RuntimeError("집계 폭발")))
        rl.start_request()
        r = _resp()
        assert r.status == "COMPLETED"          # 페이지는 살아 있다
        assert r.cost_report.llm_cost_usd_nanos == 0

    def test_페이로드가_작다(self):
        """쪽마다 붙는 값이라 커지면 안 된다."""
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3131, 121)
        rl.record_llm("opus추출", "claude-opus-4-8", 4000, 600)
        rl.record_hcxt("텍스트", 5.0)
        n = len(_resp(text_list=[{"type": "image"}]).SerializeToString())
        assert n < 200, f"{n} bytes — 계약이 다시 부풀었다"
