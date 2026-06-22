"""요청별 진행도·단계 소요시간·API 사용량 로깅 (서버 로그 정리용).

서버 터미널이 한눈에 읽히도록:
  - 단계(추출/분해/점역/조판)마다 시작 ▶ / 종료 ✓ 소요시간을 실시간으로 찍는다.
  - OpenAI(GPT-4o)·HCXT 호출 수를 요청 단위(contextvar)로 집계해 마지막 요약에 싣는다.

GPT-4o 단가(2024-11, gpt-4o): 입력 $2.5/1M·출력 $10/1M 토큰. 토큰 집계가 없어
호출 수만 세고 대략 비용은 호출당 평균치로 근사 표기한다(정확 청구 아님, 사용량 감각용).
"""
from __future__ import annotations

import contextvars
import time

from app.utils.logger import get_logger

logger = get_logger("app.progress")

# 요청 단위 API 호출 카운터(async-safe, contextvar).
_api: contextvars.ContextVar[dict | None] = contextvars.ContextVar("api_counts", default=None)

# gpt-4o 호출당 대략 비용(USD) — 호출 평균 토큰 가정(입력 1.5K·출력 0.5K)으로 근사.
_GPT4O_APPROX_COST = 0.0088


def start_request() -> None:
    """요청 시작 시 카운터 초기화(gRPC 핸들러가 호출)."""
    _api.set({"hcxt": 0, "gpt4o": 0})


def _inc(key: str) -> None:
    d = _api.get()
    if d is not None:
        d[key] = d.get(key, 0) + 1


def inc_hcxt() -> None:
    _inc("hcxt")


def inc_gpt4o() -> None:
    _inc("gpt4o")


def api_counts() -> dict:
    return dict(_api.get() or {"hcxt": 0, "gpt4o": 0})


def api_summary() -> str:
    c = api_counts()
    s = f"HCXT {c['hcxt']}회 · GPT-4o {c['gpt4o']}회"
    if c["gpt4o"]:
        s += f"(~${c['gpt4o'] * _GPT4O_APPROX_COST:.3f})"
    return s


class _Stage:
    """단계 시작/종료를 실시간 로그로 남기는 컨텍스트 매니저.

        with stage('추출') as st:
            ...
            st.note = '22요소 · STANDARD'
    """

    def __init__(self, label: str, prefix: str = "  ") -> None:
        self.label = label
        self.prefix = prefix
        self.note = ""
        self._t0 = 0.0

    def __enter__(self) -> "_Stage":
        self._t0 = time.monotonic()
        logger.info("%s▶ %s …", self.prefix, self.label)
        return self

    def __exit__(self, *exc) -> None:
        dt = time.monotonic() - self._t0
        tail = f"  ({self.note})" if self.note else ""
        logger.info("%s✓ %s  %.1fs%s", self.prefix, self.label, dt, tail)


def stage(label: str, prefix: str = "  ") -> _Stage:
    return _Stage(label, prefix)
