"""요청별 진행도·단계 소요시간·API 사용량·GPU 점유 로깅 (통합 테스트 로그 정리용).

서버 터미널/통합 테스트 로그가 한눈에 읽히고 디버깅이 쉽도록 요청 단위(contextvar)로:
  - 단계(추출/분해/점역/조판)마다 시작 ▶ / 종료 ✓ 소요시간을 실시간으로 찍는다(stage).
  - 7체인 중 진행 단계를 `[3/7] 표` 형태로 찍는다(step).
  - 외부 LLM(Claude·GPT-4o)을 **파트별**로 실제 토큰·실비용($)까지 집계한다.
  - HyperCLOVA X(로컬 GPU)를 **파트별** 호출 수·소요시간·타임아웃 수·GPU 시간비용으로 집계한다.
  - GPU 메모리 점유(로컬 LLM)를 조회해 단계 로그·요약에 싣는다.
요청 종료 시 `breakdown_lines()`로 파트별 표를 출력해 "어느 파트가 얼마나 먹었는지" 바로 본다.

## 토큰·단가 규약 (2026-08-13 개정 — "실제 청구값과 거의 일치")

- 토큰은 **응답 `usage`의 실값만** 쓴다. 근사치(구 `_APPROX_IN/_OUT` 1500/500)는 제거했다 —
  가장 비싼 항목이 가짜 숫자면 그 위에 무엇을 쌓아도 틀린다.
- 단가는 `app/core/pricing.py`가 정본. 모델마다 다르고 기간 한정가가 있다. 여기서 곱하지 않는다.
  (구 버전은 Claude를 부르면서 gpt-4o 단가를 곱하고 있었다.)
- `usage`가 없는 호출(예외로 끝난 폴백)은 **토큰 0·비용 0**으로 남긴다. 실제로 얼마 나갔는지
  모르는 걸 지어내지 않는다. 호출 수만 센다.
"""
from __future__ import annotations

import contextvars
import functools
import time
from dataclasses import dataclass, field

from app.core import pricing
from app.utils.logger import get_logger

logger = get_logger("app.progress")


def _never_raises(fallback):
    """관측 함수를 감싼다 — **로그가 페이지를 죽이면 안 된다.**

    `api_summary()`/`breakdown_lines()`는 pipeline의 **성공 로그** 안에서 불린다. 거기서
    예외가 나면 `except Exception`이 잡아, 점역이 다 끝난 결과를 버리고 C1 BLOCKED로
    뒤집는다. 원가 표시 하나 때문에 페이지가 막히는 건 등급이 다른 사고라 길목에서
    막는다(계산이 틀리는 것과 파이프라인이 죽는 것은 다른 문제다).
    """
    def deco(fn):
        @functools.wraps(fn)
        def wrap(*a, **kw):
            try:
                return fn(*a, **kw)
            except Exception as exc:  # noqa: BLE001
                logger.warning("%s 실패(로그만 생략): %s", fn.__name__, exc)
                return fallback() if callable(fallback) else fallback
        return wrap
    return deco


@dataclass
class _PartApi:
    """한 파트(kind)의 외부/로컬 LLM 사용 누계."""
    gpt4o_calls: int = 0          # 이름은 하위호환. 실제로는 '외부 LLM 호출 수'
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    cost: float = 0.0             # 외부 LLM 토큰 비용(USD)
    models: set[str] = field(default_factory=set)
    unpriced_calls: int = 0       # 단가표에 없는 모델로 계산한 호출 수
    hcxt_calls: int = 0
    hcxt_time_s: float = 0.0
    hcxt_timeouts: int = 0
    hcxt_fails: int = 0
    gpu_cost: float = 0.0         # HCXT 점유 시간 안분(USD)


@dataclass
class _ReqStats:
    parts: dict[str, _PartApi] = field(default_factory=dict)
    # (라벨, 소요초, 비고, 요청 시작 기준 시작 오프셋초).
    # 오프셋이 있어야 "어느 파트가 언제 점유했는가"를 그릴 수 있다(E2E 병렬 측정, S4).
    stages: list[tuple[str, float, str, float]] = field(default_factory=list)
    t0: float = 0.0                      # 요청 시작 monotonic
    hcxt_budget_s: float | None = None   # 페이지 누적 HCXT 상한(초). None=무제한

    def part(self, kind: str) -> _PartApi:
        return self.parts.setdefault(kind or "기타", _PartApi())

    def hcxt_used(self) -> float:
        return sum(p.hcxt_time_s for p in self.parts.values())


# 요청 단위 통계(async-safe, contextvar).
_stats: contextvars.ContextVar[_ReqStats | None] = contextvars.ContextVar("req_stats", default=None)


def start_request() -> None:
    """요청 시작 시 통계 초기화(gRPC 핸들러/파이프라인이 호출)."""
    _stats.set(_ReqStats(t0=time.monotonic()))


def elapsed() -> float:
    """요청 시작 이후 경과(초). 통계 없으면 0."""
    st = _cur()
    return (time.monotonic() - st.t0) if st and st.t0 else 0.0


def set_hcxt_budget(seconds: float) -> None:
    """이번 페이지의 누적 HCXT 시간 상한을 설정(점역 단계 시작 시 호출)."""
    st = _cur()
    if st is not None:
        st.hcxt_budget_s = max(0.0, seconds)


def hcxt_budget_remaining() -> float | None:
    """남은 HCXT 예산(초). 예산 미설정이면 None(무제한)."""
    st = _cur()
    if st is None or st.hcxt_budget_s is None:
        return None
    return st.hcxt_budget_s - st.hcxt_used()


def _cur() -> _ReqStats | None:
    return _stats.get()


# ── 외부 API(GPT-4o) 기록 — 파트별 실토큰·실비용 ────────────────────────────

def _as_int(v) -> int:
    """토큰 수를 정수로 강제. 숫자가 아니면 0.

    `usage`는 **외부 SDK가 주는 객체**다. 형이 바뀌거나(버전업) 목 객체가 섞이면
    그 값이 그대로 누계에 더해져 이후 이 요청의 원가가 통째로 못 쓰게 된다
    (실제로 테스트에서 MagicMock이 흘러들어 집계가 오염됐다). 입구에서 막는다.
    """
    try:
        return max(0, int(v))
    except (TypeError, ValueError):
        return 0


def record_llm(kind: str, model: str, input_tokens: int = 0, output_tokens: int = 0,
               cache_read_tokens: int = 0, cache_write_tokens: int = 0) -> None:
    """외부 LLM 호출 1건 기록 — **모델별 단가**로 실비용을 계산한다.

    토큰은 응답 `usage`의 실값만 넘긴다. 모르면 0으로 두라(지어내지 말 것).
    """
    st = _cur()
    if st is None:
        return
    input_tokens, output_tokens = _as_int(input_tokens), _as_int(output_tokens)
    cache_read_tokens = _as_int(cache_read_tokens)
    cache_write_tokens = _as_int(cache_write_tokens)
    p = st.part(kind)
    p.gpt4o_calls += 1
    p.models.add(str(model))
    p.prompt_tokens += input_tokens
    p.completion_tokens += output_tokens
    p.cache_read_tokens += cache_read_tokens
    p.cache_write_tokens += cache_write_tokens
    p.cost += pricing.llm_cost_usd(model, input_tokens, output_tokens,
                                   cache_read_tokens, cache_write_tokens)
    if not pricing.is_priced(model):
        p.unpriced_calls += 1


def record_anthropic(kind: str, model: str, usage) -> None:
    """Anthropic 응답 `usage` 객체를 그대로 받아 기록(캐시 토큰 포함).

    `input_tokens`에 캐시 토큰이 **안 들어 있어서** 따로 더해야 한다 — 캐시를 켜는 순간
    조용히 과소 집계되는 자리라 여기서 한 번에 처리한다.
    """
    g = lambda name: getattr(usage, name, 0) or 0 if usage is not None else 0  # noqa: E731
    record_llm(kind, model, g("input_tokens"), g("output_tokens"),
               g("cache_read_input_tokens"), g("cache_creation_input_tokens"))


def record_openai(kind: str, model: str, usage) -> None:
    """OpenAI 응답 `usage`(prompt_tokens/completion_tokens)를 받아 기록."""
    if usage is None:
        record_llm(kind, model)
        return
    prompt = getattr(usage, "prompt_tokens", 0) or 0
    cached = 0
    details = getattr(usage, "prompt_tokens_details", None)
    if details is not None:
        cached = getattr(details, "cached_tokens", 0) or 0
    # OpenAI의 prompt_tokens는 캐시분을 **포함**한다(Anthropic과 반대) — 중복 계산 방지.
    record_llm(kind, model, max(0, prompt - cached),
               getattr(usage, "completion_tokens", 0) or 0, cached, 0)


def record_gpt4o(kind: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """하위호환 — 모델을 안 밝힌 구 호출부. gpt-4o 단가로 계산한다."""
    record_llm(kind, "gpt-4o", prompt_tokens, completion_tokens)


# ── 로컬 LLM(HCXT) 기록 — 파트별 호출 수·시간·타임아웃 ──────────────────────

def record_hcxt(kind: str, elapsed_s: float = 0.0, *, timed_out: bool = False, failed: bool = False) -> None:
    """HyperCLOVA X 호출 1건 기록(소요시간·타임아웃·실패)."""
    st = _cur()
    if st is None:
        return
    p = st.part(kind)
    p.hcxt_calls += 1
    p.hcxt_time_s += elapsed_s
    p.gpu_cost += pricing.gpu_cost_usd(elapsed_s)
    if timed_out:
        p.hcxt_timeouts += 1
    if failed:
        p.hcxt_fails += 1


# ── 하위호환 shim(구 호출부) ────────────────────────────────────────────────

def inc_hcxt() -> None:
    record_hcxt("기타")


def inc_gpt4o() -> None:
    record_gpt4o("기타")


# ── 집계 조회 ───────────────────────────────────────────────────────────────

def _totals() -> dict:
    st = _cur()
    if st is None:
        return {"hcxt": 0, "gpt4o": 0, "prompt_tokens": 0, "completion_tokens": 0,
                "cache_read_tokens": 0, "cache_write_tokens": 0, "cost": 0.0,
                "gpu_cost": 0.0, "gpu_seconds": 0.0, "unpriced_calls": 0, "models": []}
    add = lambda f: sum(f(p) for p in st.parts.values())  # noqa: E731
    return {
        "hcxt": add(lambda p: p.hcxt_calls),
        "gpt4o": add(lambda p: p.gpt4o_calls),
        "prompt_tokens": add(lambda p: p.prompt_tokens),
        "completion_tokens": add(lambda p: p.completion_tokens),
        "cache_read_tokens": add(lambda p: p.cache_read_tokens),
        "cache_write_tokens": add(lambda p: p.cache_write_tokens),
        "cost": add(lambda p: p.cost),
        "gpu_cost": add(lambda p: p.gpu_cost),
        "gpu_seconds": add(lambda p: p.hcxt_time_s),
        "unpriced_calls": add(lambda p: p.unpriced_calls),
        "models": sorted({m for p in st.parts.values() for m in p.models}),
    }


@_never_raises(dict)
def cost_report() -> dict:
    """이번 요청의 원가 내역 — BE 응답(CostReport)·대시보드가 그대로 쓴다.

    `fx_rate`·`pricing_version`을 함께 실어 **어느 환율·어느 단가표로 계산했는지** 밝힌다.
    나중에 청구서와 어긋났을 때 무엇을 의심할지 알 수 있어야 한다.
    """
    t = _totals()
    total_usd = t["cost"] + t["gpu_cost"]
    st = _cur()
    parts = []
    for kind, p in sorted((st.parts if st else {}).items(), key=lambda kv: -(kv[1].cost + kv[1].gpu_cost)):
        if not p.gpt4o_calls and not p.hcxt_calls:
            continue
        parts.append({
            "kind": kind,
            "llm_calls": p.gpt4o_calls,
            "models": sorted(p.models),
            "input_tokens": p.prompt_tokens,
            "output_tokens": p.completion_tokens,
            "cache_read_tokens": p.cache_read_tokens,
            "cache_write_tokens": p.cache_write_tokens,
            "llm_cost_usd": round(p.cost, 6),
            "gpu_seconds": round(p.hcxt_time_s, 2),
            "gpu_cost_usd": round(p.gpu_cost, 6),
        })
    return {
        "cost_usd": round(total_usd, 6),
        "cost_krw": pricing.to_krw(total_usd),
        "llm_cost_usd": round(t["cost"], 6),
        "gpu_cost_usd": round(t["gpu_cost"], 6),
        "gpu_seconds": round(t["gpu_seconds"], 2),
        "fx_rate": pricing.fx_rate(),
        "fx_age_days": pricing.fx_age_days(),    # 며칠 된 환율인지 — 오래되면 대시보드가 경고
        "gpu_usd_per_hour": pricing.gpu_usd_per_hour(),
        "pricing_version": pricing.pricing_version(),
        "unpriced_calls": t["unpriced_calls"],   # >0이면 단가표에 없는 모델을 썼다
        "models": t["models"],
        "parts": parts,
    }


def api_counts() -> dict:
    """하위호환: {'hcxt': n, 'gpt4o': n}."""
    t = _totals()
    return {"hcxt": t["hcxt"], "gpt4o": t["gpt4o"]}


@_never_raises("")
def api_summary() -> str:
    """한 줄 요약(요청 총계)."""
    t = _totals()
    s = f"HCXT {t['hcxt']}회 · 외부LLM {t['gpt4o']}회"
    if t["gpt4o"]:
        tok = t["prompt_tokens"] + t["completion_tokens"]
        s += f"({tok:,}토큰 ${t['cost']:.4f})"
    if t["gpu_cost"]:
        s += f" · GPU {t['gpu_seconds']:.0f}s ${t['gpu_cost']:.4f}"
    total = t["cost"] + t["gpu_cost"]
    if total:
        s += f" = ${total:.4f}(₩{pricing.to_krw(total):,})"
    return s


@_never_raises(list)
def stage_timeline() -> list[dict]:
    """이 요청의 단계별 점유 구간. E2E 병렬 측정(S4)이 메트릭에 싣는다.

    반환 `[{"label", "start_ms", "ms", "note"}]` — start_ms는 요청 시작 기준이다.
    여러 페이지의 구간을 겹쳐 그리면 어느 자원이 언제 붐비는지 바로 보인다.
    """
    st = _cur()
    if st is None:
        return []
    return [{"label": lbl, "start_ms": round(off * 1000), "ms": round(dt * 1000),
             "note": note}
            for lbl, dt, note, off in st.stages]


@_never_raises(list)
def breakdown_lines() -> list[str]:
    """파트별 LLM 사용 내역(요청 종료 로그용). 사용 없으면 빈 리스트."""
    st = _cur()
    if st is None or not st.parts:
        return []
    lines = ["── 파트별 LLM 사용 내역 ──"]
    lines.append(f"  {'파트':<10} {'HCXT':>12} {'LLM':>5} {'토큰(in/out)':>16} {'모델':<18} {'비용$':>9}")
    for kind, p in sorted(st.parts.items(), key=lambda kv: -(kv[1].cost + kv[1].gpu_cost)):
        if not p.hcxt_calls and not p.gpt4o_calls:
            continue
        hcxt = f"{p.hcxt_calls}회/{p.hcxt_time_s:.1f}s" if p.hcxt_calls else "-"
        if p.hcxt_timeouts:
            hcxt += f"⏱{p.hcxt_timeouts}"
        tok = f"{p.prompt_tokens:,}/{p.completion_tokens:,}" if p.gpt4o_calls else "-"
        model = ",".join(sorted(p.models)) or "-"
        lines.append(f"  {kind:<10} {hcxt:>12} {p.gpt4o_calls:>5} {tok:>16} {model:<18} "
                     f"${p.cost + p.gpu_cost:>8.4f}")
    t = _totals()
    total = t["cost"] + t["gpu_cost"]
    lines.append(f"  합계 LLM ${t['cost']:.4f} + GPU ${t['gpu_cost']:.4f} = ${total:.4f} "
                 f"(₩{pricing.to_krw(total):,} @ {pricing.fx_rate():g})")
    if t["unpriced_calls"]:
        lines.append(f"  ⚠ 단가표에 없는 모델 호출 {t['unpriced_calls']}건 — 비용 추정치다")
    return lines


# ── GPU 점유(로컬 LLM) ──────────────────────────────────────────────────────

def gpu_note(device: int | None = None) -> str:
    """로컬 LLM GPU 메모리 점유 문자열. torch 미가용/CPU면 빈 문자열.

    이용률(%)은 pynvml이 있으면 덧붙인다(없으면 메모리만). 실패는 조용히 무시.
    """
    try:
        import torch
        if not torch.cuda.is_available():
            return ""
        if device is None:
            from app.core.config import config
            device = config.hcxt_gpu_device
        alloc = torch.cuda.memory_allocated(device) / 1024**3
        reserved = torch.cuda.memory_reserved(device) / 1024**3
        total = torch.cuda.get_device_properties(device).total_memory / 1024**3
        s = f"GPU{device} {alloc:.1f}/{total:.0f}GB(예약 {reserved:.1f})"
        util = _gpu_util(device)
        if util is not None:
            s += f" util {util}%"
        return s
    except Exception:  # noqa: BLE001 — 로깅 보조라 실패해도 무시
        return ""


def _gpu_util(device: int) -> int | None:
    try:
        import pynvml
        pynvml.nvmlInit()
        h = pynvml.nvmlDeviceGetHandleByIndex(device)
        return int(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
    except Exception:  # noqa: BLE001
        return None


# ── 단계·진행 로그 ──────────────────────────────────────────────────────────

class _Stage:
    """단계 시작/종료를 실시간 로그로 남기는 컨텍스트 매니저.

        with stage('추출') as st:
            ...
            st.note = '22요소 · STANDARD'

    gpu=True면 종료 로그에 GPU 점유를 덧붙인다(로컬 모델을 쓰는 단계).
    """

    def __init__(self, label: str, prefix: str = "  ", gpu: bool = False) -> None:
        self.label = label
        self.prefix = prefix
        self.gpu = gpu
        self.note = ""
        self._t0 = 0.0

    def __enter__(self) -> "_Stage":
        self._t0 = time.monotonic()
        logger.info("%s▶ %s …", self.prefix, self.label)
        return self

    def __exit__(self, *exc) -> None:
        dt = time.monotonic() - self._t0
        bits = [self.note] if self.note else []
        if self.gpu:
            g = gpu_note()
            if g:
                bits.append(g)
        tail = f"  ({' · '.join(bits)})" if bits else ""
        logger.info("%s✓ %s  %.1fs%s", self.prefix, self.label, dt, tail)
        st = _cur()
        if st is not None:
            st.stages.append((self.label, dt, self.note,
                              max(0.0, self._t0 - st.t0) if st.t0 else 0.0))


def stage(label: str, prefix: str = "  ", *, gpu: bool = False) -> _Stage:
    return _Stage(label, prefix, gpu=gpu)


def step(idx: int, total: int, label: str, note: str = "") -> None:
    """7체인 등 세부 파트 진행도(%가 아닌 단계 진행). 예: [3/7] 표  (2요소)."""
    tail = f"  ({note})" if note else ""
    logger.info("    [%d/%d] %s%s", idx, total, label, tail)
