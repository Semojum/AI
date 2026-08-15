"""요청 로그 — API 사용량 카운터·단계 컨텍스트 회귀 테스트."""
import app.utils.req_log as rl
from app.core import pricing


class TestObservabilityNeverRaises:
    """관측 함수는 예외를 올리면 안 된다.

    `api_summary()`/`breakdown_lines()`는 pipeline **성공 로그** 안에서 불린다. 거기서
    예외가 나면 `except Exception`이 잡아, 점역이 끝난 결과를 버리고 C1 BLOCKED로
    뒤집는다 — 원가 표시 하나가 페이지를 막는다.
    """

    def _boom(self, monkeypatch):
        monkeypatch.setattr(pricing, "fx_rate",
                            lambda **k: (_ for _ in ()).throw(RuntimeError("환율 폭발")))

    def test_api_summary(self, monkeypatch):
        rl.start_request(); rl.record_llm("a", "claude-sonnet-5", 10, 1)
        self._boom(monkeypatch)
        assert rl.api_summary() == ""

    def test_breakdown_lines(self, monkeypatch):
        rl.start_request(); rl.record_llm("a", "claude-sonnet-5", 10, 1)
        self._boom(monkeypatch)
        assert rl.breakdown_lines() == []

    def test_cost_report(self, monkeypatch):
        rl.start_request(); rl.record_llm("a", "claude-sonnet-5", 10, 1)
        self._boom(monkeypatch)
        assert rl.cost_report() == {}


class TestUsageCoercion:
    """`usage`는 외부 SDK 객체다. 이상한 형이 들어와도 집계가 오염되면 안 된다."""

    def test_목_객체가_흘러들어도_숫자로_남는다(self):
        from unittest.mock import MagicMock
        rl.start_request()
        rl.record_anthropic("캡셔닝", "claude-sonnet-5", MagicMock())
        p = rl._cur().part("캡셔닝")
        # 핵심은 **형이 숫자로 남는 것**이다. 목이 섞여 누계가 MagicMock이 되면
        # 이후 cost_report()가 정렬에서 TypeError로 죽고, 그 요청 원가가 통째로 날아간다.
        assert isinstance(p.prompt_tokens, int) and isinstance(p.cost, float)
        assert isinstance(rl.cost_report()["cost_usd"], float)

    def test_usage가_None이어도_호출수는_센다(self):
        rl.start_request()
        rl.record_anthropic("캡셔닝", "claude-sonnet-5", None)
        rl.record_openai("분류", "gpt-4o", None)
        assert rl._totals()["gpt4o"] == 2 and rl._totals()["cost"] == 0.0

    def test_음수_토큰은_0으로(self):
        rl.start_request()
        rl.record_llm("a", "gpt-4o", -5, -5)
        assert rl._totals()["cost"] == 0.0


class TestBadEnvDoesNotKillServer:
    """원가 **표시용** 환경변수 오타가 파이프라인을 죽이면 안 된다.

    첫 판은 모듈 최상단에서 `float(os.getenv(...))`를 그대로 돌려, `.env`에
    `FX_CARD_MARKUP=oops` 한 줄이면 import가 죽고 req_log→파이프라인까지 딸려 죽었다.
    """

    def test_잘못된_값은_기본값으로(self, monkeypatch):
        monkeypatch.setenv("USD_KRW", "abc")
        monkeypatch.setattr(pricing, "_warned_env", set())   # 경고 억제 상태 초기화
        assert pricing.fx_rate() == pricing._FX_FALLBACK

    def test_0은_거부한다(self, monkeypatch):
        """0을 통과시키면 원가가 전부 0원으로 보고된다."""
        monkeypatch.setenv("USD_KRW", "0")
        monkeypatch.setattr(pricing, "_warned_env", set())
        assert pricing.fx_rate() == pricing._FX_FALLBACK

    def test_정상값은_그대로(self, monkeypatch):
        monkeypatch.setenv("USD_KRW", "1400")
        assert pricing.fx_rate() == 1400.0        # env가 있으면 조회하지 않는다


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
