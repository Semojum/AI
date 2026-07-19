"""opt 공통 베이스 — 모든 점역 최적화(PART 4-2~9-2)가 공유하는 구조.

각 opt 모듈(text/formula/table/image/cartoon/chart_graph)은 **자신에 최적화된 프롬프트만**
정의하고, HCLOVA X 추론·FALLBACK·재시도·티어 결정 같은 공통(rule-based) 기계는 전부 여기에 둔다.

- `hcxt_generate_sync` / `hcxt_optimize` : 단일 GPU 모델 직렬 추론(프리필 옵션).
- `fallback_optimize`                   : GPT-4o 폴백.
- `generate_with_retry`                 : 3회 재시도 후 폴백 (모든 opt 동일 루프).
- `decide_tier_timeout`                 : ocr_confidence → (tier, timeout).
- `BaseOpt`                             : optimize() = 요소별 _optimize_one gather.
  (시각자료 대체텍스트 4안 공통 흐름은 `visual_drafts.build_visual_drafts`로 분리됨.)
"""

from __future__ import annotations

import asyncio
import os
import logging
import re
import time
from typing import Callable, Optional

from app.core.config import config
from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent, LLMOutput
from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

FALLBACK_TIMEOUT = 45.0  # GPT-4o 폴백 제한
_HCXT_MIN_SLICE = 3.0    # 이보다 예산이 적게 남으면 HCXT를 건너뛰고 바로 폴백(무의미한 짧은 추론 방지)


class HcxtBudgetExceeded(Exception):
    """페이지 누적 HCXT 예산 소진 — 이 요소는 HCXT를 건너뛰고 GPT-4o로 폴백."""


def hcxt_generate_sync(prompt: str, max_new_tokens: int = 512, prefill: str = "") -> str:
    """HyperCLOVA X 동기 추론. prefill이 있으면 답변 시작을 강제해 포맷을 고정한다.

    호출 집계(req_log)는 스레드 밖(async 컨텍스트)의 hcxt_optimize에서 한다 — 이 함수는
    asyncio.to_thread로 별도 스레드에서 돌아 contextvar 쓰기가 요청 통계에 반영되지 않는다.
    """
    import torch

    model = model_manager.hcxt_model
    tokenizer = model_manager.hcxt_tokenizer
    device = next(model.parameters()).device
    messages = [{"role": "user", "content": prompt}]
    enc = tokenizer.apply_chat_template(
        messages, add_generation_prompt=True, skip_reasoning=True,
        return_dict=True, return_tensors="pt",
    )
    input_ids = enc["input_ids"]
    if prefill:  # 답변 시작을 강제(포맷 고정 → Think 모델 추론 람블 방지)
        pf = tokenizer(prefill, return_tensors="pt", add_special_tokens=False)["input_ids"]
        input_ids = torch.cat([input_ids, pf], dim=1)
    input_ids = input_ids.to(device)
    with torch.no_grad():
        out = model.generate(
            input_ids=input_ids,
            attention_mask=torch.ones_like(input_ids),
            max_new_tokens=max_new_tokens,
            do_sample=False,
            pad_token_id=tokenizer.eos_token_id,
            stop_strings=["<|endofturn|>", "<|stop|>"],
            tokenizer=tokenizer,
            use_cache=True,
        )
    generated = tokenizer.decode(out[0][input_ids.shape[1]:], skip_special_tokens=True).strip()
    return (prefill + generated) if prefill else generated


async def hcxt_optimize(
    prompt: str, timeout: float, *,
    prefill: str = "", max_new_tokens: int = 512, kind: str = "요소",
) -> str:
    """HCXT 추론 + 타임아웃. 백엔드에 따라 경로가 갈린다(config.hcxt_backend).

    - vllm: 별도 vLLM 서버로 오프로드. 서버가 배칭/동시성을 처리하므로 GPU 락·페이지 예산
      없이 요소들이 병렬로 돈다. 타임아웃만 건다.
    - transformers(기본): 인프로세스 단일 GPU 직렬(inference_lock 공유). 락 안에서만 실제 추론
      시간을 재 파트별 사용량(req_log)에 기록한다(대기 시간 제외). 페이지 누적 예산도 여기서만.
    """
    from app.utils.req_log import record_hcxt

    if config.hcxt_backend == "vllm":
        from app.ai.llm.hcxt_client import vllm_generate
        t0 = time.monotonic()
        try:
            out = await asyncio.wait_for(
                vllm_generate(prompt, max_new_tokens, prefill), timeout=timeout)
            record_hcxt(kind, time.monotonic() - t0)
            return out
        except asyncio.TimeoutError:
            record_hcxt(kind, time.monotonic() - t0, timed_out=True)
            logger.warning("HCXT(vLLM) %s 타임아웃 (%.0fs)", kind, timeout)
            raise
        except Exception:
            record_hcxt(kind, time.monotonic() - t0, failed=True)
            raise

    from app.ai.llm.inference_lock import hcxt_lock
    from app.utils.req_log import hcxt_budget_remaining
    async with hcxt_lock():
        # 페이지 누적 HCXT 예산 확인(락 획득 후 — 대기 중 다른 요소가 예산을 소진했을 수 있음).
        # 예산이 거의 없으면 즉시 폴백, 남았으면 요소 상한을 남은 예산으로 클램프.
        remaining = hcxt_budget_remaining()
        if remaining is not None and remaining < _HCXT_MIN_SLICE:
            logger.info("HCXT 페이지 예산 소진 → %s는 폴백(남은 %.1fs)", kind, remaining)
            raise HcxtBudgetExceeded(kind)
        eff_timeout = timeout if remaining is None else max(_HCXT_MIN_SLICE, min(timeout, remaining))
        t0 = time.monotonic()
        try:
            out = await asyncio.wait_for(
                asyncio.to_thread(hcxt_generate_sync, prompt, max_new_tokens, prefill),
                timeout=eff_timeout,
            )
            record_hcxt(kind, time.monotonic() - t0)
            return out
        except asyncio.TimeoutError:
            record_hcxt(kind, time.monotonic() - t0, timed_out=True)
            logger.warning("HyperCLOVA X %s 최적화 타임아웃 (%.0fs)", kind, eff_timeout)
            raise
        except Exception:
            record_hcxt(kind, time.monotonic() - t0, failed=True)
            raise


async def fallback_optimize(prompt: str, *, max_tokens: int = 300, kind: str = "요소") -> str:
    """LLM 폴백 — Anthropic(claude-sonnet-5) 우선, 없으면 GPT-4o, 둘 다 없으면 "".

    태민 지시(2026-07-17): openai 대신 anthropic을 쓴다. OpenAI 경로는 무료 티어(RPM 3)
    호환용으로만 남긴다. usage는 파트별 req_log에 기록(카운터 이름은 record_gpt4o지만 공용).

    ★ 오프라인 차단 스위치(2026-07-19): `DISABLE_LLM_FALLBACK=1`이면 호출하지 않는다.
      측정·재추출 같은 오프라인 배치는 HCXT가 없어 요소마다 이 폴백을 타는데, 키가 환경에
      남아 있으면 그대로 과금된다(실제 사고: 재추출 도구 2개가 키를 안 비워 폴백 790회
      ≈$9.5 발생, 원장과 청구액이 $12 어긋남). 도구마다 키를 비우는 규약은 하나만
      빠뜨려도 뚫리므로, 호출 길목에서 한 번에 막는다.
    """
    from app.utils.req_log import record_gpt4o

    if os.environ.get("DISABLE_LLM_FALLBACK") == "1":
        logger.warning("LLM 폴백 차단됨(DISABLE_LLM_FALLBACK=1) — %s", kind)
        return ""

    if config.anthropic_api_key:
        import anthropic
        client = anthropic.AsyncAnthropic(api_key=config.anthropic_api_key)
        try:
            resp = await asyncio.wait_for(
                client.messages.create(
                    model=os.environ.get("FALLBACK_MODEL", "claude-sonnet-5"),
                    max_tokens=max_tokens,
                    messages=[{"role": "user", "content": prompt}],
                ),
                timeout=FALLBACK_TIMEOUT,
            )
            u = getattr(resp, "usage", None)
            record_gpt4o(kind, getattr(u, "input_tokens", 0) or 0,
                         getattr(u, "output_tokens", 0) or 0)
            return "".join(b.text for b in resp.content if b.type == "text").strip()
        except Exception as exc:  # noqa: BLE001 — 폴백 실패는 원문 폴백으로 격리
            record_gpt4o(kind)
            logger.error("FALLBACK(anthropic) %s 최적화 실패: %s", kind, exc)
            return ""

    if not config.openai_api_key:
        logger.error("FALLBACK: ANTHROPIC/OPENAI_API_KEY 모두 미설정")
        return ""
    import openai
    client = openai.AsyncOpenAI(api_key=config.openai_api_key)
    try:
        resp = await asyncio.wait_for(
            client.chat.completions.create(
                model="gpt-4o",
                messages=[{"role": "user", "content": prompt}],
                max_tokens=max_tokens,
                temperature=0.0,
            ),
            timeout=FALLBACK_TIMEOUT,
        )
        usage = getattr(resp, "usage", None)
        record_gpt4o(kind, getattr(usage, "prompt_tokens", 0) or 0,
                     getattr(usage, "completion_tokens", 0) or 0)
        return resp.choices[0].message.content.strip()
    except Exception as exc:  # noqa: BLE001
        record_gpt4o(kind)
        logger.error("FALLBACK %s 최적화 실패: %s", kind, exc)
        return ""


def numbers_grounded(original: str, output: str) -> bool:
    """원본의 수치가 출력에 모두 존재하는지(환각·변조 방지). 시각 opt 수치 그라운딩 공통."""
    nums_in = set(re.findall(r"\d+(?:\.\d+)?", original))
    nums_out = set(re.findall(r"\d+(?:\.\d+)?", output))
    return nums_in.issubset(nums_out)


def decide_tier_timeout(
    ocr_confidence: float,
    standard_timeout: float | None = None,
    quality_timeout: float | None = None,
) -> tuple[str, float]:
    """ocr_confidence → (routing_tier, 요소당 HCXT 상한). 저신뢰=QUALITY, 그 외=STANDARD.

    상한 기본값은 config(hcxt_element/quality_timeout_seconds) — 단일 GPU 직렬이라 작게 둔다.
    호출부가 값을 주면 그 값을 쓰되(테스트/특수 케이스), 운영은 config 기본을 쓴다.
    """
    if ocr_confidence < config.ocr_confidence_threshold:
        return "QUALITY", quality_timeout if quality_timeout is not None else config.hcxt_quality_timeout_seconds
    return "STANDARD", standard_timeout if standard_timeout is not None else config.hcxt_element_timeout_seconds


# 일시적 예외(OOM 순간·CUDA 재시도 등) 재시도 횟수. 타임아웃은 여기 포함 안 됨.
_TRANSIENT_RETRIES = 2


async def generate_with_retry(
    prompt: str, *,
    timeout: float, element_id, kind: str,
    prefill: str = "", max_new_tokens: int = 512, fallback_max_tokens: int = 300,
    transform: Optional[Callable[[str], str]] = None,
) -> tuple[str, bool]:
    """HCLOVA X 추론 → 실패 시 GPT-4o 폴백. 반환: (응답, 폴백사용여부).

    타임아웃 처리(성능 핵심): 타임아웃은 **재시도하지 않고 즉시 폴백**한다. hcxt_optimize는
    GPU 락을 잡은 뒤에야 타이머를 시작하므로(대기 시간 제외), 타임아웃은 "이 요소 추론이
    실제로 timeout보다 오래 걸린다"는 뜻 — 같은 예산으로 재시도하면 락을 잡은 채 timeout을
    N배 낭비할 뿐이다(1페이지 요소 수십 개 직렬화 → 페이지 타임아웃의 주범이었다).
    일시적 예외(OOM 순간 등)만 소수 재시도한다.

    transform은 HCLOVA X 응답에만 적용한다(폴백 응답은 그대로 — 기존 동작 보존).
    """
    attempt = 0
    while True:
        try:
            resp = await hcxt_optimize(
                prompt, timeout, prefill=prefill, max_new_tokens=max_new_tokens, kind=kind
            )
            return (transform(resp) if transform else resp), False
        except (asyncio.TimeoutError, HcxtBudgetExceeded) as exc:
            # 느린 추론/예산 소진 재시도 금지 → 곧바로 폴백(락 점유 시간 최소화).
            reason = "예산 소진" if isinstance(exc, HcxtBudgetExceeded) else "타임아웃"
            logger.warning("HyperCLOVA X %s %s → 즉시 FALLBACK id=%s", kind, reason, element_id)
            resp = await fallback_optimize(prompt, max_tokens=fallback_max_tokens, kind=kind)
            return resp, True
        except Exception as exc:
            attempt += 1
            logger.warning("HyperCLOVA X %s 실패 #%d id=%s: %s", kind, attempt, element_id, exc)
            if attempt > _TRANSIENT_RETRIES:
                logger.warning("FALLBACK 전환 id=%s", element_id)
                resp = await fallback_optimize(prompt, max_tokens=fallback_max_tokens, kind=kind)
                return resp, True


class BaseOpt:
    """opt 공통 진입점. optimize() = 요소별 _optimize_one을 격리 없이 gather."""

    async def optimize(
        self,
        extracted: list[ExtractedContent],
        routing_tier: str,
        layout: Optional[LayoutResult] = None,
    ) -> list[LLMOutput]:
        return await asyncio.gather(*[self._optimize_one(e, routing_tier) for e in extracted])

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        raise NotImplementedError
