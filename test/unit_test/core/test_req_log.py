"""요청 로그 — API 사용량 카운터·단계 컨텍스트 회귀 테스트."""
from pathlib import Path

import pytest

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

    def test_usage_report(self, monkeypatch):
        rl.start_request(); rl.record_llm("a", "claude-sonnet-5", 10, 1)
        self._boom(monkeypatch)
        assert rl.usage_report() == {}


class TestUsageCoercion:
    """`usage`는 외부 SDK 객체다. 이상한 형이 들어와도 집계가 오염되면 안 된다."""

    def test_목_객체가_흘러들어도_숫자로_남는다(self):
        from unittest.mock import MagicMock
        rl.start_request()
        rl.record_anthropic("캡셔닝", "claude-sonnet-5", MagicMock())
        e = rl._cur().entry("캡셔닝", "claude-sonnet-5")
        # 핵심은 **형이 숫자로 남는 것**이다. 목이 섞여 누계가 MagicMock이 되면
        # 이후 usage_report()가 정렬에서 TypeError로 죽고, 그 요청 사용량이 통째로 날아간다.
        assert isinstance(e.input_tokens, int) and isinstance(e.cost, float)
        assert isinstance(rl.usage_report()["cost_usd"], float)

    def test_usage가_None이어도_호출수는_센다(self):
        rl.start_request()
        rl.record_anthropic("캡셔닝", "claude-sonnet-5", None)
        rl.record_openai("분류", "gpt-4o", None)
        assert rl._totals()["llm"] == 2 and rl._totals()["cost"] == 0.0

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
        assert pricing.fx_rate() == pricing._FX_FALLBACK * pricing.card_markup()

    def test_0은_거부한다(self, monkeypatch):
        """0을 통과시키면 원가가 전부 0원으로 보고된다."""
        monkeypatch.setenv("USD_KRW", "0")
        monkeypatch.setattr(pricing, "_warned_env", set())
        assert pricing.fx_rate() == pricing._FX_FALLBACK * pricing.card_markup()

    def test_정상값은_그대로(self, monkeypatch):
        monkeypatch.setenv("USD_KRW", "1400")
        monkeypatch.delenv("FX_CARD_MARKUP", raising=False)
        monkeypatch.setattr(pricing, "_FX_MARKUP_FILE", Path("/없는/markup.json"))
        # env가 있으면 조회하지 않는다. 카드 수수료 배수는 그 위에 곱한다.
        assert pricing.fx_rate() == 1400.0 * pricing._FX_MARKUP_ESTIMATE


class TestCardMarkup:
    """원화는 매매기준율이 아니라 **카드 수수료가 얹힌 값**으로 환산해야 한다."""

    def _no_file(self, monkeypatch):
        monkeypatch.delenv("FX_CARD_MARKUP", raising=False)
        monkeypatch.setattr(pricing, "_FX_MARKUP_FILE", Path("/없는/markup.json"))

    def test_기본은_공시요율_추정이고_그렇다고_밝힌다(self, monkeypatch):
        self._no_file(monkeypatch)
        assert pricing.fx_basis() == "estimated"
        assert pricing.card_markup() == pricing._FX_MARKUP_ESTIMATE

    def test_명세서_실측이_추정을_이긴다(self, monkeypatch, tmp_path):
        self._no_file(monkeypatch)
        monkeypatch.setattr(pricing, "_FX_MARKUP_FILE", tmp_path / "m.json")
        # $100 청구가 141,890원으로 찍혔고 그때 기준환율이 1415.43이었다면
        m = pricing.calibrate(141890, 100, 1415.43)
        assert abs(m - 1.0025) < 1e-3
        assert pricing.fx_basis() == "calibrated" and pricing.card_markup() == m

    def test_env가_최우선(self, monkeypatch, tmp_path):
        monkeypatch.setattr(pricing, "_FX_MARKUP_FILE", tmp_path / "m.json")
        pricing.calibrate(141890, 100, 1415.43)
        monkeypatch.setenv("FX_CARD_MARKUP", "1.05")
        assert pricing.fx_basis() == "env" and pricing.card_markup() == 1.05

    def test_입력_사고는_거부한다(self, monkeypatch, tmp_path):
        """자릿수를 틀리면 배수가 7배가 된다 — 파일에 쓰기 전에 막아야."""
        monkeypatch.setattr(pricing, "_FX_MARKUP_FILE", tmp_path / "m.json")
        with pytest.raises(ValueError):
            pricing.calibrate(1_000_000, 100, 1415.43)
        assert not (tmp_path / "m.json").exists()

    def test_깨진_실측파일은_추정으로_되돌아간다(self, monkeypatch, tmp_path):
        self._no_file(monkeypatch)
        f = tmp_path / "m.json"; f.write_text('{"markup": 99}', encoding="utf-8")
        monkeypatch.setattr(pricing, "_FX_MARKUP_FILE", f)
        assert pricing.fx_basis() == "estimated"


class TestApiCounts:
    def test_초기화_후_0(self):
        rl.start_request()
        assert rl.api_counts() == {"hcxt": 0, "llm": 0}

    def test_증가(self):
        rl.start_request()
        rl.inc_hcxt(); rl.inc_hcxt(); rl.inc_ext_llm()
        c = rl.api_counts()
        assert c["hcxt"] == 2 and c["llm"] == 1

    def test_summary_포맷(self):
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 1000, 100)
        s = rl.api_summary()
        assert "HCXT 0회" in s and "외부LLM 1회" in s and "$" in s

    def test_토큰_모르면_비용_0(self):
        """usage 없는 호출은 **비용을 지어내지 않는다**(구 근사치 1500/500 제거, 2026-08-13)."""
        rl.start_request()
        rl.inc_ext_llm()
        assert rl._totals()["cost"] == 0.0        # 구 버전은 1500/500을 채워 $0.0088로 잡았다
        assert rl._totals()["llm"] == 1         # 호출 수는 센다


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

    def test_usage_report에_환율과_단가판이_실린다(self):
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 100, 10)
        r = rl.usage_report()
        assert r["fx_rate"] > 0 and r["pricing_version"]
        assert [m["model"] for m in r["models"]] == ["claude-sonnet-5"]
        assert r["unpriced_calls"] == 0

    def test_단가표에_없는_모델은_드러난다(self):
        rl.start_request()
        rl.record_llm("a", "claude-지어낸-9", 100, 10)
        assert rl.usage_report()["unpriced_calls"] == 1


class TestStage:
    def test_stage_무예외_note(self):
        with rl.stage("테스트단계") as st:
            st.note = "5요소"
        assert st.note == "5요소"


# ── 쪽당 원가에서 GPU 제외 (2026-08-20 대표 지시) ─────────────────────────
# AWS 서버 비용은 인스턴스 시간으로 따로 매긴다. 쪽마다 안분하면 이중 계상이 된다.
class TestGpuExcludedFromPageCost:
    def test_cost_usd에_GPU가_안_섞인다(self):
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 3000, 500)
        rl.record_hcxt("텍스트", 5.0)
        u = rl.usage_report()
        assert u["cost_usd"] == round(u["llm_cost_usd_nanos"] / 1e9, 9), u["cost_usd"]
        assert u["gpu_cost_usd_nanos"] > 0, "GPU 관측값 자체는 남아야 한다"

    def test_GPU_점유_시간은_계속_기록된다(self):
        """금액에서만 뺀다. 측정값은 BE가 따로 쓸 수 있게 남긴다."""
        rl.start_request()
        rl.record_hcxt("텍스트", 2.0)
        u = rl.usage_report()
        assert u["gpu_time_ms"] == 2000 and u["gpu_seconds"] == 2.0


class TestExtLlmCounter:
    """카운터 이름이 모델 하나를 가리키면 안 된다 — 라우팅이 여러 모델을 쓴다."""

    def test_모델과_무관하게_외부_LLM을_센다(self):
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 100, 10)
        rl.record_llm("분류", "gpt-4o", 100, 10)
        assert rl.api_counts() == {"hcxt": 0, "llm": 2}


class TestGpuSpan:
    """GPU 점유 시간 (2026-08-20 대표 지시).

    종전에는 `gpu_seconds`가 HCXT 시간만 세어 30/30쪽 전부 0이었다. HCXT가 비활성이고
    실제 GPU를 쓰는 것은 MinerU 서브프로세스인데 그 구간을 재는 자리가 없었다.
    """

    def test_gpu_span이_시간을_남긴다(self) -> None:
        import time
        from app.utils import req_log as R
        R.start_request()
        with R.gpu_span("추출"):
            time.sleep(0.05)
        u = R.usage_report()
        assert u["gpu_time_ms"] >= 45, u["gpu_time_ms"]

    def test_gpu는_쪽당_원가에_안_들어간다(self) -> None:
        """AWS 인스턴스 시간으로 따로 매기므로 쪽마다 안분하면 이중 계상이다."""
        import time
        from app.utils import req_log as R
        R.start_request()
        with R.gpu_span("추출"):
            time.sleep(0.02)
        u = R.usage_report()
        assert u["gpu_time_ms"] > 0
        assert u["cost_usd"] == 0, u["cost_usd"]          # GPU는 금액 합계에 안 더한다

    def test_gpu_시간은_HCXT_예산을_안_먹는다(self) -> None:
        """예산이 소진되면 요소가 외부 API 폴백으로 넘어간다 — 즉 출력이 바뀐다.

        MinerU 시간을 예산에 섞으면 추출이 느린 쪽에서만 폴백이 걸려 같은 입력에
        다른 결과가 난다. 2026-08-21에 gpu_span을 배선하면서 한 번 섞였던 자리다.
        """
        import time
        from app.utils import req_log as R
        R.start_request()
        R.set_hcxt_budget(1.0) if hasattr(R, "set_hcxt_budget") else None
        with R.gpu_span("추출"):
            time.sleep(0.05)
        st = R._cur()
        assert st.hcxt_used() == 0.0, st.hcxt_used()
        assert R.usage_report()["gpu_time_ms"] >= 45      # 관측값은 그대로 남는다


class TestMineruLogRotation:
    """MinerU 로그가 무한정 자라지 않는다 (2026-08-21 QA).

    이어붙이기만 하다 16MB까지 자랐다. MinerU가 쪽마다 INFO를 쏟는데, 그러면 정작
    이 로그를 남긴 목적(기동 실패 원인)이 묻힌다.
    """

    def test_상한을_넘으면_직전_한_벌로_밀린다(self, tmp_path, monkeypatch) -> None:
        import subprocess
        from app.ai.parser import mineru_service as MS

        log = tmp_path / "mineru_api.log"
        log.write_bytes(b"x" * 2048)
        monkeypatch.setenv("MINERU_API_LOG", str(log))
        monkeypatch.setenv("MINERU_API_LOG_MAX_MB", "0")     # 0MB = 항상 회전
        # 이미 떠 있는 서비스를 재사용하면 회전 코드까지 안 간다 — 없는 것으로 만든다
        monkeypatch.delenv("MINERU_API_URL", raising=False)
        monkeypatch.setattr(MS, "_health", lambda *a, **k: False)
        monkeypatch.setattr(MS.subprocess, "Popen", lambda *a, **k: (_ for _ in ()).throw(
            RuntimeError("기동은 하지 않는다")))
        try:
            MS.ensure_started()
        except Exception:                                     # noqa: BLE001 — 기동 실패는 무관
            pass
        assert log.with_suffix(".log.1").exists(), "직전 한 벌이 안 남았다"
        assert log.with_suffix(".log.1").read_bytes() == b"x" * 2048


class TestPromptCacheHitRate:
    """프롬프트 캐시 적중률 집계 (2026-08-23, 대표 지시 API비용 2번).

    조건이 "적중 여부를 req_log에 남기고 적중률을 보고할 것"이었다. 분모를 잘못 잡으면
    캐시가 잘 맞을수록 100%를 넘는다 — Anthropic `usage.input_tokens`에 캐시 토큰이
    **안 들어 있어서** 적중할수록 분모가 줄기 때문이다.
    """

    def test_분모는_비캐시_입력과_읽기_쓰기의_합이다(self) -> None:
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 300, 50,
                      cache_read_tokens=1800, cache_write_tokens=0)
        assert rl.cache_hit_rate() == pytest.approx(1800 / 2100)

    def test_첫_호출은_쓰기라_적중률이_0이다(self) -> None:
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 300, 50, cache_write_tokens=1800)
        assert rl.cache_hit_rate() == 0.0

    def test_캐시를_안_쓰면_0이고_줄도_안_나온다(self) -> None:
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 300, 50)
        assert rl.cache_hit_rate() == 0.0
        assert not [ln for ln in rl.breakdown_lines() if "캐시" in ln]

    def test_파트별로_따로_찍는다(self) -> None:
        # 분류는 시스템이 324토큰이라 최소 캐시 길이(1,024)에 못 미쳐 영원히 0이다.
        # 합계로만 보면 그게 캡셔닝 문제인지 분류 문제인지 못 가른다.
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 300, 50, cache_read_tokens=1800)
        rl.record_llm("분류", "claude-sonnet-5", 700, 5)
        lines = [ln for ln in rl.breakdown_lines() if "캐시" in ln]
        assert any("캡셔닝" in ln for ln in lines) and any("분류" in ln for ln in lines)
        assert rl.cache_hit_rate() == pytest.approx(1800 / 2800)

    def test_usage_report에_적중률이_실린다(self) -> None:
        rl.start_request()
        rl.record_llm("캡셔닝", "claude-sonnet-5", 300, 50, cache_read_tokens=1800)
        rep = rl.usage_report()
        assert rep["cache_read_tokens"] == 1800
        assert rep["cache_hit_rate"] == pytest.approx(1800 / 2100, abs=1e-4)
        assert rep["models"][0]["cache_read_tokens"] == 1800
