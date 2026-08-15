"""요청 로그 — API 사용량 카운터·단계 컨텍스트 회귀 테스트."""
import app.utils.req_log as rl


class TestApiCounts:
    def test_초기화_후_0(self):
        rl.start_request()
        assert rl.api_counts() == {"hcxt": 0, "gpt4o": 0}

    def test_증가(self):
        rl.start_request()
        rl.inc_hcxt(); rl.inc_hcxt(); rl.inc_gpt4o()
        c = rl.api_counts()
        assert c["hcxt"] == 2 and c["gpt4o"] == 1

    def test_summary_포맷(self):
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 1000, 100)
        s = rl.api_summary()
        assert "HCXT 0회" in s and "외부LLM 1회" in s and "$" in s

    def test_토큰_모르면_비용_0(self):
        """usage 없는 호출은 **비용을 지어내지 않는다**(구 근사치 1500/500 제거, 2026-08-13)."""
        rl.start_request()
        rl.inc_gpt4o()
        assert rl._totals()["cost"] == 0.0        # 구 버전은 1500/500을 채워 $0.0088로 잡았다
        assert rl._totals()["gpt4o"] == 1         # 호출 수는 센다


class TestCost:
    """단가는 모델별이다 — Claude를 부르고 gpt-4o 단가를 곱하던 버그의 회귀 방지."""

    def test_모델별_단가가_다르다(self):
        rl.start_request()
        rl.record_llm("a", "claude-opus-4-8", 1_000_000, 0)
        opus = rl._totals()["cost"]
        rl.start_request()
        rl.record_llm("a", "gpt-4o", 1_000_000, 0)
        assert opus == 5.00 and rl._totals()["cost"] == 2.50

    def test_GPU_시간이_비용에_들어간다(self):
        rl.start_request()
        rl.record_hcxt("텍스트", 3600.0)
        assert rl._totals()["gpu_cost"] > 0  # 구 버전은 0원이었다

    def test_cost_report에_환율과_단가판이_실린다(self):
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 100, 10)
        r = rl.cost_report()
        assert r["fx_rate"] > 0 and r["pricing_version"] and r["models"] == ["claude-sonnet-5"]
        assert r["unpriced_calls"] == 0

    def test_단가표에_없는_모델은_드러난다(self):
        rl.start_request()
        rl.record_llm("a", "claude-지어낸-9", 100, 10)
        assert rl.cost_report()["unpriced_calls"] == 1


class TestStage:
    def test_stage_무예외_note(self):
        with rl.stage("테스트단계") as st:
            st.note = "5요소"
        assert st.note == "5요소"
