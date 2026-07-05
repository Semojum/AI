"""요청별 진행도·단계 소요시간·API 사용량·GPU 점유 로깅 (통합 테스트 로그 정리용).

서버 터미널/통합 테스트 로그가 한눈에 읽히고 디버깅이 쉽도록 요청 단위(contextvar)로:
  - 단계(추출/분해/점역/조판)마다 시작 ▶ / 종료 ✓ 소요시간을 실시간으로 찍는다(stage).
  - 7체인 중 진행 단계를 `[3/7] 표` 형태로 찍는다(step).
  - GPT-4o(외부 API)를 **파트별**로 실제 토큰(prompt/completion)·실비용($)까지 집계한다.
  - HyperCLOVA X(로컬 GPU)를 **파트별** 호출 수·소요시간·타임아웃 수로 집계한다.
  - GPU 메모리 점유(로컬 LLM)를 조회해 단계 로그·요약에 싣는다.
요청 종료 시 `breakdown_lines()`로 파트별 표를 출력해 "어느 파트가 얼마나 먹었는지" 바로 본다.

토큰 집계: OpenAI 응답의 `usage`(prompt_tokens/completion_tokens)를 그대로 받아 누적하고,
gpt-4o 단가로 실비용을 계산한다. usage가 없으면(구버전 응답) 근사 토큰으로 채운다.
"""
from __future__ import annotations

import contextvars
import time
from dataclasses import dataclass, field

from app.utils.logger import get_logger

logger = get_logger("app.progress")

# gpt-4o 단가(2024-11, USD/토큰). 입력 $2.5/1M · 출력 $10/1M.
_GPT4O_IN_PER_TOK = 2.5 / 1_000_000
_GPT4O_OUT_PER_TOK = 10.0 / 1_000_000
# usage가 없을 때만 쓰는 근사(입력 1.5K·출력 0.5K 가정).
_APPROX_IN, _APPROX_OUT = 1500, 500


@dataclass
class _PartApi:
    """한 파트(kind)의 외부/로컬 LLM 사용 누계."""
    gpt4o_calls: int = 0
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cost: float = 0.0
    hcxt_calls: int = 0
    hcxt_time_s: float = 0.0
    hcxt_timeouts: int = 0
    hcxt_fails: int = 0


@dataclass
class _ReqStats:
    parts: dict[str, _PartApi] = field(default_factory=dict)
    stages: list[tuple[str, float, str]] = field(default_factory=list)
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

def record_gpt4o(kind: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """GPT-4o 호출 1건 기록. usage(prompt/completion 토큰)가 있으면 실비용까지 계산.

    토큰이 0(usage 없음)이면 근사치로 채워 비용 감각을 유지한다(정확 청구 아님).
    """
    st = _cur()
    if st is None:
        return
    if not prompt_tokens and not completion_tokens:
        prompt_tokens, completion_tokens = _APPROX_IN, _APPROX_OUT
    cost = prompt_tokens * _GPT4O_IN_PER_TOK + completion_tokens * _GPT4O_OUT_PER_TOK
    p = st.part(kind)
    p.gpt4o_calls += 1
    p.prompt_tokens += prompt_tokens
    p.completion_tokens += completion_tokens
    p.cost += cost


# ── 로컬 LLM(HCXT) 기록 — 파트별 호출 수·시간·타임아웃 ──────────────────────

def record_hcxt(kind: str, elapsed_s: float = 0.0, *, timed_out: bool = False, failed: bool = False) -> None:
    """HyperCLOVA X 호출 1건 기록(소요시간·타임아웃·실패)."""
    st = _cur()
    if st is None:
        return
    p = st.part(kind)
    p.hcxt_calls += 1
    p.hcxt_time_s += elapsed_s
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
        return {"hcxt": 0, "gpt4o": 0, "prompt_tokens": 0, "completion_tokens": 0, "cost": 0.0}
    hcxt = sum(p.hcxt_calls for p in st.parts.values())
    gpt4o = sum(p.gpt4o_calls for p in st.parts.values())
    pt = sum(p.prompt_tokens for p in st.parts.values())
    ct = sum(p.completion_tokens for p in st.parts.values())
    cost = sum(p.cost for p in st.parts.values())
    return {"hcxt": hcxt, "gpt4o": gpt4o, "prompt_tokens": pt, "completion_tokens": ct, "cost": cost}


def api_counts() -> dict:
    """하위호환: {'hcxt': n, 'gpt4o': n}."""
    t = _totals()
    return {"hcxt": t["hcxt"], "gpt4o": t["gpt4o"]}


def api_summary() -> str:
    """한 줄 요약(요청 총계)."""
    t = _totals()
    s = f"HCXT {t['hcxt']}회 · GPT-4o {t['gpt4o']}회"
    if t["gpt4o"]:
        tok = t["prompt_tokens"] + t["completion_tokens"]
        s += f"({tok:,}토큰 ~${t['cost']:.4f})"
    return s


def breakdown_lines() -> list[str]:
    """파트별 LLM 사용 내역(요청 종료 로그용). 사용 없으면 빈 리스트."""
    st = _cur()
    if st is None or not st.parts:
        return []
    lines = ["── 파트별 LLM 사용 내역 ──"]
    header = f"  {'파트':<10} {'HCXT':>10} {'GPT-4o':>8} {'토큰(in/out)':>16} {'비용$':>9}"
    lines.append(header)
    for kind, p in sorted(st.parts.items(), key=lambda kv: -(kv[1].cost + kv[1].hcxt_time_s)):
        if not p.hcxt_calls and not p.gpt4o_calls:
            continue
        hcxt = f"{p.hcxt_calls}회/{p.hcxt_time_s:.1f}s"
        if p.hcxt_timeouts:
            hcxt += f"⏱{p.hcxt_timeouts}"
        tok = f"{p.prompt_tokens:,}/{p.completion_tokens:,}" if p.gpt4o_calls else "-"
        cost = f"${p.cost:.4f}" if p.gpt4o_calls else "-"
        lines.append(f"  {kind:<10} {hcxt:>10} {p.gpt4o_calls:>8} {tok:>16} {cost:>9}")
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
            st.stages.append((self.label, dt, self.note))


def stage(label: str, prefix: str = "  ", *, gpu: bool = False) -> _Stage:
    return _Stage(label, prefix, gpu=gpu)


def step(idx: int, total: int, label: str, note: str = "") -> None:
    """7체인 등 세부 파트 진행도(%가 아닌 단계 진행). 예: [3/7] 표  (2요소)."""
    tail = f"  ({note})" if note else ""
    logger.info("    [%d/%d] %s%s", idx, total, label, tail)
