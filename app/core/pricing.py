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

import json
import os
import sys
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

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

_warned_env: set[str] = set()


def _env_float(name: str, default: float, *, positive: bool = True) -> float:
    """환경변수 → 실수. **오타가 서버를 멈추면 안 된다** — 경고 남기고 기본값으로 간다.

    맨 처음 판은 `float(os.getenv(...))`를 모듈 최상단에서 그대로 돌렸다. `.env`에
    `FX_CARD_MARKUP=oops` 한 줄이면 import가 죽고, `req_log`→파이프라인까지 딸려
    죽는다. 원가 **표시용** 설정 오타가 점역을 멈추는 건 값이 맞고 틀리고의 문제가
    아니라 등급이 다른 사고다.
    """
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        v = float(raw)
        if positive and v <= 0:
            raise ValueError(f"{v} <= 0")
        return v
    except ValueError as exc:
        # 한 번만 경고한다. `USD_KRW`는 원가를 찍을 때마다 읽혀서, 매번 경고하면
        # 쪽당 예닐곱 줄이 쌓여 정작 봐야 할 로그를 덮는다.
        if name not in _warned_env:
            _warned_env.add(name)
            logger.warning("%s 값이 잘못됐다(%r: %s) — 기본값 %s 사용", name, raw, exc, default)
        return default


# GPU 시간 단가(USD/h). 서울 리전 g5.xlarge 온디맨드 실단가 — 2026-08-05 다운사이즈
# 적용·가동 확인된 실제 청구 단가다(그전 g5.2xlarge는 $1.4903/h).
# 인스턴스를 바꾸면 `GPU_USD_PER_HOUR`로 덮어쓴다.
_GPU_USD_PER_HOUR = _env_float("GPU_USD_PER_HOUR", 1.2370)

# ── 환율 ────────────────────────────────────────────────────────────────────
# 주 1회 자동 갱신한다(2026-08-15 대표 지시). **크론이 아니라 지연 갱신(TTL)이다** —
# 크론은 기계마다 따로 걸어야 하는데(개발 PJ14 · 운영 AWS), 하나만 빠뜨려도 그 기계는
# 옛 환율로 원가를 보고한다. 캐시 파일이 7일 넘으면 다음 호출이 알아서 받아 온다.
#
# ⚠ **원화는 원리상 청구서와 정확히 못 맞춘다. 정확한 건 USD다.**
#   Anthropic·OpenAI는 USD로 청구하고, 원화 환산은 카드사가 **매입일**(결제일이 아니라
#   며칠 뒤) 환율로 한다. 우리가 요청 시점에 아는 환율과 다를 수밖에 없다.
#   그래서 `cost_usd`가 정본이고 `cost_krw`는 참고값이다 — 대조는 USD로 한다.
#
#   원화 오차 중 **줄일 수 있는 부분은 수수료**다. 해외 카드결제는 매매기준율에
#   두 가지가 얹힌다(공시 요율):
#       국제브랜드 수수료   VISA·Mastercard 1.0%
#       카드사 해외서비스료  0.18 ~ 0.35% (발급사마다 다름)
#   합쳐 1.18~1.35%. 기본값은 원가를 낮게 잡지 않도록 위쪽(1.3%)을 쓴다 —
#   원가를 실제보다 싸게 보고하면 가격 결정이 틀어진다.
#
#   명세서로 실측하면 그 값이 이긴다: `python -m app.core.pricing --calibrate <원화> <USD>`
#   (해당 기간 매입일 환율을 세 번째 인자로 주면 더 정확하다.)
_FX_MARKUP_ESTIMATE = 1.013           # 공시 요율 기반 추정(브랜드 1.0% + 발급사 0.3%)
_FX_MARKUP_FILE = Path(os.getenv("FX_MARKUP_PATH", "storage/fx_markup.json"))
_FX_FALLBACK = 1380.0                 # 조회도 캐시도 없을 때만 쓰는 최후값
_FX_MIN, _FX_MAX = 500.0, 5000.0      # 이 밖은 자릿수 사고로 보고 거부
_FX_TTL_S = 7 * 86400                 # 주 1회
_FX_RETRY_S = 3600                    # 조회 실패 시 재시도 간격(매 호출 재시도 방지)
_FX_URL = "https://open.er-api.com/v6/latest/USD"
_FX_CACHE = Path(os.getenv("FX_CACHE_PATH", "storage/fx_rate.json"))


def _markup() -> tuple[float, str]:
    """(카드 수수료 배수, 근거). 우선순위: 환경변수 > 명세서 실측 > 공시요율 추정.

    근거를 같이 돌려주는 이유: 추정치를 실측인 양 넘기면 대시보드가 원가를 사실로
    믿는다. `fx_basis`로 보고해 "이건 아직 추정"임을 드러낸다.
    """
    if os.getenv("FX_CARD_MARKUP"):
        return _env_float("FX_CARD_MARKUP", _FX_MARKUP_ESTIMATE), "env"
    try:
        d = json.loads(_FX_MARKUP_FILE.read_text(encoding="utf-8"))
        m = float(d["markup"])
        if 1.0 <= m < 1.2:            # 20% 넘는 수수료는 입력 사고다
            return m, "calibrated"
    except Exception:  # noqa: BLE001 — 실측 없음이 정상 상태
        pass
    return _FX_MARKUP_ESTIMATE, "estimated"

_fx_cached: tuple[float, float] | None = None   # (rate, fetched_at epoch)
_fx_last_try = 0.0


def _fx_read_cache() -> tuple[float, float] | None:
    try:
        d = json.loads(_FX_CACHE.read_text(encoding="utf-8"))
        rate = float(d["rate"])
        if not _FX_MIN < rate < _FX_MAX:   # 깨진 캐시(0·음수·자릿수 사고)를 믿지 않는다
            raise ValueError(f"캐시 환율 이상값 {rate}")
        return rate, float(d["fetched_at"])
    except Exception:  # noqa: BLE001 — 캐시 없음/깨짐은 정상 경로(그냥 받아 온다)
        return None


def _fx_fetch() -> tuple[float, float] | None:
    """USD→KRW 조회. 실패는 None — **절대 예외를 올리지 않는다**(원가는 파이프라인을 막지 않는다)."""
    try:
        import urllib.request
        with urllib.request.urlopen(_FX_URL, timeout=5) as r:
            d = json.loads(r.read().decode())
        rate = float(d["rates"]["KRW"])
        if not _FX_MIN < rate < _FX_MAX:   # 자릿수 사고·이상값 방어
            raise ValueError(f"환율 이상값 {rate}")
    except Exception as exc:  # noqa: BLE001
        logger.warning("환율 조회 실패(직전 값 유지): %s", exc)
        return None

    # 캐시 쓰기 실패는 조회 실패가 **아니다.** 받아온 값은 그대로 쓴다 — 여기서 같이
    # 버리면 읽기전용 스토리지에서 매번 새로 받고도 영영 최후값으로 계산한다.
    now = time.time()
    try:
        _FX_CACHE.parent.mkdir(parents=True, exist_ok=True)
        _FX_CACHE.write_text(json.dumps(
            {"rate": rate, "fetched_at": now, "source": _FX_URL,
             "fetched_at_kst": time.strftime("%Y-%m-%d %H:%M", time.localtime(now))},
            ensure_ascii=False), encoding="utf-8")
    except OSError as exc:
        logger.warning("환율 캐시 기록 실패(값은 사용): %s", exc)
    logger.info("환율 갱신: USD 1 = %.2f KRW (%s)", rate, _FX_URL)
    return rate, now


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


def fx_rate(*, force: bool = False) -> float:
    """USD→KRW 환율. 7일 지나면 조회해 갱신하고, 실패하면 직전 값을 그대로 쓴다.

    `USD_KRW`가 설정돼 있으면 **조회하지 않는다** — 값을 못 박고 싶을 때(재현 가능한
    측정, 폐쇄망)를 위한 탈출구다.
    """
    global _fx_cached, _fx_last_try
    if os.getenv("USD_KRW"):
        return _env_float("USD_KRW", _FX_FALLBACK) * _markup()[0]

    if _fx_cached is None:
        _fx_cached = _fx_read_cache()

    now = time.time()
    # 시계가 뒤로 튀면(NTP 보정·스냅샷 복원) age가 음수가 된다. abs로 보면 그때도
    # 낡은 것으로 쳐서 다시 받는다 — 부호를 안 보면 영영 갱신 안 되는 상태로 굳는다.
    stale = _fx_cached is None or abs(now - _fx_cached[1]) > _FX_TTL_S
    # 조회가 죽어 있을 때 매 호출 재시도하면 페이지마다 5초씩 문다.
    if (force or stale) and (now - _fx_last_try) > _FX_RETRY_S:
        _fx_last_try = now
        got = _fx_fetch()
        if got:
            _fx_cached = got

    rate = _fx_cached[0] if _fx_cached else _FX_FALLBACK
    return rate * _markup()[0]


def fx_age_days() -> float | None:
    """캐시된 환율이 며칠 됐나. None이면 조회한 적 없음(최후값 사용 중)."""
    if os.getenv("USD_KRW"):
        return 0.0
    c = _fx_cached or _fx_read_cache()
    return max(0.0, (time.time() - c[1]) / 86400) if c else None


def fx_basis() -> str:
    """원화 환산 근거 — `env` / `calibrated`(명세서 실측) / `estimated`(공시요율 추정).

    대시보드가 추정치를 사실로 오해하지 않게 함께 내보낸다.
    """
    return _markup()[1]


def card_markup() -> float:
    return _markup()[0]


def calibrate(krw: float, usd: float, settled_rate: float | None = None) -> float:
    """명세서 실측으로 수수료 배수를 확정한다.

        markup = (청구 원화 / 청구 USD) / 그 시점 매매기준율

    `settled_rate`(매입일 환율)를 주면 정확하다. 안 주면 오늘 환율로 나누는데,
    그 사이 환율이 움직인 만큼 배수에 섞여 든다 — 그래서 되도록 주라고 안내한다.
    """
    if usd <= 0 or krw <= 0:
        raise ValueError("원화·USD 모두 0보다 커야 한다")
    base = settled_rate or fx_rate()
    markup = (krw / usd) / base
    if not 1.0 <= markup < 1.2:
        raise ValueError(f"수수료 배수 {markup:.4f} — 입력이나 기준환율을 다시 보라 "
                         f"(정상 범위 1.00~1.20)")
    _FX_MARKUP_FILE.parent.mkdir(parents=True, exist_ok=True)
    _FX_MARKUP_FILE.write_text(json.dumps(
        {"markup": markup, "krw": krw, "usd": usd, "base_rate": base,
         "effective_rate": krw / usd,
         "measured_at_kst": time.strftime("%Y-%m-%d %H:%M")},
        ensure_ascii=False), encoding="utf-8")
    return markup


def to_krw(usd: float) -> int:
    return round(usd * fx_rate())


def gpu_usd_per_hour() -> float:
    return _GPU_USD_PER_HOUR


def pricing_version() -> str:
    """단가표 판 — 청구서와 대조할 때 '어느 표로 계산했는지' 식별자."""
    return "2026-08-13"


if __name__ == "__main__" and "--calibrate" in sys.argv:
    # 사용: --calibrate <청구원화> <청구USD> [매입일환율]
    a = sys.argv[sys.argv.index("--calibrate") + 1:]
    if not 2 <= len(a) <= 3:
        print("사용: python -m app.core.pricing --calibrate <청구원화> <청구USD> [매입일환율]")
        raise SystemExit(2)
    m = calibrate(float(a[0]), float(a[1]), float(a[2]) if len(a) == 3 else None)
    print(f"수수료 배수 {m:.4f} ({(m - 1) * 100:.2f}%) 확정 — {_FX_MARKUP_FILE}")
    print(f"실효환율 USD 1 = {float(a[0]) / float(a[1]):.2f} KRW")
    raise SystemExit(0)

if __name__ == "__main__" and "--fx" in sys.argv:  # 수동/크론 강제 갱신
    print(f"USD 1 = {fx_rate(force=True):.2f} KRW  (캐시 {_FX_CACHE}, "
          f"{fx_age_days():.2f}일 전 갱신, 수수료배수 {_markup()[0]:g}[{_markup()[1]}])")
    raise SystemExit(0)

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
    # 환율: 조회가 죽어도 원가 계산이 멈추면 안 된다. 캐시도 없애고 강제로 태운다 —
    # 캐시가 신선하면 조회를 건너뛰어 실패 경로를 안 본다(첫 판 자체점검의 구멍이었다).
    _FX_URL = "http://127.0.0.1:9/없는주소"          # noqa: F811 — 일부러 죽인다
    _FX_CACHE = Path("/없는/경로/fx.json")           # noqa: F811
    _fx_cached, _fx_last_try = None, 0.0
    assert fx_rate(force=True) == _FX_FALLBACK * _markup()[0], "조회·캐시 모두 실패하면 최후값이어야"
    # 잘못된 env가 서버를 죽이면 안 된다(원가 표시용 설정이다)
    os.environ["FX_CARD_MARKUP"] = "oops"
    assert _env_float("FX_CARD_MARKUP", 1.0) == 1.0
    os.environ["USD_KRW"] = "0"            # 0이면 원가가 전부 0원이 된다 — 거부해야
    assert _env_float("USD_KRW", 1380.0) == 1380.0
    del os.environ["FX_CARD_MARKUP"], os.environ["USD_KRW"]

    # 캐시 쓰기가 막혀도(읽기전용 스토리지) **받아온 값은 써야 한다** — 같이 버리면
    # 매번 새로 받고도 영영 최후값으로 계산한다(첫 판의 실제 버그).
    # 망이 없는 곳에서 돌릴 수도 있으니 조회 성공을 전제하지 않는다.
    _FX_URL = "https://open.er-api.com/v6/latest/USD"
    _fx_last_try = 0.0
    if _fx_fetch():
        _fx_cached, _fx_last_try = None, 0.0
        assert fx_rate(force=True) != _FX_FALLBACK * _markup()[0], \
            "쓰기 실패로 조회값을 버리면 안 된다"
    else:
        print("  (망 없음 — 조회 성공 경로는 건너뜀)")
    # 수수료 배수: 추정 → 실측 전환과 이상값 거부
    assert _markup() == (_FX_MARKUP_ESTIMATE, "estimated")
    _FX_MARKUP_FILE = Path("/tmp/claude-1000/_fx_markup_selfcheck.json")  # noqa: F811
    assert abs(calibrate(141890, 100, 1415.43) - 1.0025) < 1e-3
    assert _markup()[1] == "calibrated"
    try:
        calibrate(1_000_000, 100)      # 배수 7배 — 입력 사고는 막아야
        raise AssertionError("이상값을 통과시켰다")
    except ValueError:
        pass
    _FX_MARKUP_FILE.unlink(missing_ok=True)
    print("pricing 자체 점검 통과")
