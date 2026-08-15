"""LLM·GPU 단가 정본 — "청구서에 찍히는 값"을 계산하는 유일한 자리.

## 왜 분리했나 (2026-08-13 대표 지시: "실제 청구되는 값이랑 거의 일치해야 해")

단가가 `req_log.py` 안에 하드코딩돼 있었고, 그 값이 **gpt-4o 단가 하나뿐**이었다.
그런데 우리가 실제로 부르는 모델은 claude-sonnet-5(캡셔닝·분류·폴백)와
claude-opus-4-8(Opus 추출 폴백)이다. Claude를 부르면서 GPT-4o 단가를 곱하고 있었다.

여기 모아 두면 단가가 바뀔 때 고칠 자리가 하나다. 값을 바꿀 때는 **출처와 날짜를
주석으로 남긴다** — 나중에 청구서와 어긋났을 때 어느 값을 의심할지 알 수 있어야 한다.

## 기간 한정가를 왜 다루나

claude-sonnet-5는 **2026-08-31까지 도입가($2/$10)**, 그 뒤 정가($3/$15)다. 오늘 청구되는
값은 도입가다. 정가로 계산하면 50% 과대 보고가 된다 — "거의 일치"가 깨진다. 그래서
단가는 날짜를 받아 결정한다(`_rate(model, on)`).

## 캐시 토큰

Anthropic `usage`는 `input_tokens`에 **캐시 토큰을 포함하지 않는다.**
`cache_read_input_tokens`(정가 0.1배)·`cache_creation_input_tokens`(5분 TTL 1.25배)가
따로 온다. 지금 우리 코드는 `cache_control`을 안 쓰지만(2026-08-13 기준 0건), 넣는
순간 집계가 조용히 어긋나므로 계산식에 미리 넣어 둔다.
"""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import date

from app.utils.logger import get_logger

logger = get_logger("app.pricing")

_MTOK = 1_000_000


@dataclass(frozen=True)
class _Rate:
    """USD / 1M 토큰. 캐시 배수는 그 시점 입력 단가에 곱한다."""
    input: float
    output: float
    cache_read_mult: float = 0.1     # Anthropic 캐시 읽기 = 입력의 0.1배
    cache_write_mult: float = 1.25   # 5분 TTL 쓰기 = 1.25배 (1시간 TTL은 2.0배)
    promo_until: date | None = None
    promo_input: float = 0.0
    promo_output: float = 0.0


# 단가표 — Anthropic/OpenAI 공식 요금표 기준(2026-08-13 확인).
# ⚠ 모델을 새로 쓰기 시작하면 **여기 먼저 추가한다.** 없는 모델은 아래 _FALLBACK로
#   계산되고 경고가 뜬다(조용히 0원으로 새지 않게).
_RATES: dict[str, _Rate] = {
    # 캡셔닝·분류·opt 폴백의 기본 모델. 도입가가 2026-08-31까지다.
    "claude-sonnet-5": _Rate(3.00, 15.00,
                             promo_until=date(2026, 8, 31),
                             promo_input=2.00, promo_output=10.00),
    "claude-sonnet-4-6": _Rate(3.00, 15.00),
    # Opus 추출 폴백(app/ai/parser/opus_fallback.py, OPUS_EXTRACT_MODEL 기본값).
    "claude-opus-4-8": _Rate(5.00, 25.00),
    "claude-opus-5": _Rate(5.00, 25.00),
    "claude-haiku-4-5": _Rate(1.00, 5.00),
    # OpenAI 경로(CAPTION_BACKEND != anthropic, 또는 ANTHROPIC 키 없을 때의 폴백).
    # OpenAI는 캐시 쓰기 과금이 없고 캐시 입력이 정가의 0.5배다.
    "gpt-4o": _Rate(2.50, 10.00, cache_read_mult=0.5, cache_write_mult=0.0),
}

# 표에 없는 모델. **가장 비싼 축으로 잡는다** — 과소 보고보다 과대 보고가 낫다
# (원가를 실제보다 싸게 보고하면 가격 결정이 틀어진다). 경고로 드러낸다.
_FALLBACK = _Rate(5.00, 25.00)

_warned: set[str] = set()

# GPU 시간 단가(USD/h). 서울 리전 g5.xlarge 온디맨드 실단가 — 2026-08-05 다운사이즈
# 적용·가동 확인된 실제 청구 단가다(그전 g5.2xlarge는 $1.4903/h).
# 인스턴스를 바꾸면 `GPU_USD_PER_HOUR`로 덮어쓴다.
_GPU_USD_PER_HOUR = float(os.getenv("GPU_USD_PER_HOUR", "1.2370"))

# 환율. **자동 조회하지 않는다** — 조회 실패가 곧 원가 오류가 되면 안 된다.
# 운영에서 `USD_KRW`로 넣고, 보고 응답에 이 값을 함께 실어 "무슨 환율 기준인지" 밝힌다.
_USD_KRW = float(os.getenv("USD_KRW", "1380"))


def _rate(model: str, on: date) -> _Rate:
    r = _RATES.get(model)
    if r is None:
        if model not in _warned:
            _warned.add(model)
            logger.warning("단가표에 없는 모델 '%s' — 임시로 Opus 단가로 계산한다. "
                           "app/core/pricing.py의 _RATES에 추가할 것.", model)
        return _FALLBACK
    if r.promo_until and on <= r.promo_until:
        return _Rate(r.promo_input, r.promo_output,
                     r.cache_read_mult, r.cache_write_mult)
    return r


def is_priced(model: str) -> bool:
    """단가표에 있는 모델인가 — 보고서가 '단가 미상 N건'을 표시할 때 쓴다."""
    return model in _RATES


def llm_cost_usd(model: str, input_tokens: int, output_tokens: int,
                 cache_read_tokens: int = 0, cache_write_tokens: int = 0,
                 *, on: date | None = None) -> float:
    """토큰 수 → 실비용(USD). 날짜를 주면 그날 단가로 계산(기간 한정가 대응)."""
    r = _rate(model, on or date.today())
    return (input_tokens * r.input
            + output_tokens * r.output
            + cache_read_tokens * r.input * r.cache_read_mult
            + cache_write_tokens * r.input * r.cache_write_mult) / _MTOK


def gpu_cost_usd(seconds: float) -> float:
    """GPU 점유 시간 → 비용(USD).

    ⚠ 이건 **인스턴스 시간의 안분**이지 요청마다 청구되는 값이 아니다. 인스턴스는 놀아도
    24시간 과금되므로(2026-08-05 실측: CPU 점유 0.31%인데 하루 $35.77), 여기 합계와
    월 청구서는 가동률만큼 벌어진다. 요청 단가 감각을 잡는 용도다.
    """
    return max(0.0, seconds) * _GPU_USD_PER_HOUR / 3600.0


def fx_rate() -> float:
    """USD→KRW 환율. 응답에 함께 실어 어느 환율 기준인지 밝힌다."""
    return _USD_KRW


def to_krw(usd: float) -> int:
    return round(usd * _USD_KRW)


def gpu_usd_per_hour() -> float:
    return _GPU_USD_PER_HOUR


def pricing_version() -> str:
    """단가표 판 — 청구서와 대조할 때 '어느 표로 계산했는지' 식별자."""
    return "2026-08-13"


if __name__ == "__main__":  # 자체 점검: 기간 한정가·캐시·GPU가 실제로 갈리는지
    promo = llm_cost_usd("claude-sonnet-5", 1_000_000, 0, on=date(2026, 8, 15))
    full = llm_cost_usd("claude-sonnet-5", 1_000_000, 0, on=date(2026, 9, 1))
    assert abs(promo - 2.00) < 1e-9, promo          # 도입가
    assert abs(full - 3.00) < 1e-9, full            # 만료 후 정가
    assert abs(llm_cost_usd("gpt-4o", 0, 1_000_000) - 10.00) < 1e-9
    # 캐시 읽기는 입력의 0.1배 — 캐시를 켜면 여기가 살아난다
    assert abs(llm_cost_usd("claude-sonnet-5", 0, 0, cache_read_tokens=1_000_000,
                            on=date(2026, 9, 1)) - 0.30) < 1e-9
    assert abs(gpu_cost_usd(3600) - _GPU_USD_PER_HOUR) < 1e-9
    assert not is_priced("claude-made-up-9")        # 미상 모델은 표에 없다고 답해야
    print("pricing 자체 점검 통과")
