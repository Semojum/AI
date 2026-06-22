"""opt 공통 베이스 — 모든 점역 최적화(PART 4-2~9-2)가 공유하는 구조.

각 opt 모듈(text/formula/table/image/cartoon/chart_graph)은 **자신에 최적화된 프롬프트만**
정의하고, HCLOVA X 추론·FALLBACK·재시도·티어 결정 같은 공통(rule-based) 기계는 전부 여기에 둔다.

- `hcxt_generate_sync` / `hcxt_optimize` : 단일 GPU 모델 직렬 추론(프리필 옵션).
- `fallback_optimize`                   : GPT-4o 폴백.
- `generate_with_retry`                 : 3회 재시도 후 폴백 (모든 opt 동일 루프).
- `decide_tier_timeout`                 : ocr_confidence → (tier, timeout).
- `BaseOpt`                             : optimize() = 요소별 _optimize_one gather.
- `VisualDraftOpt`                      : 시각자료 3안 생성 공통 흐름(이미지·만화·차트 공유).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Callable, Optional

from app.ai.braille.regulations import make_rule
from app.ai.llm.draft_utils import parse_labeled_drafts, single_draft
from app.core.config import config
from app.core.model_manager import model_manager
from app.schemas.content import ExtractedContent, LLMOutput, RuleApplication
from app.schemas.layout import LayoutResult

logger = logging.getLogger(__name__)

FALLBACK_TIMEOUT = 45.0  # GPT-4o 폴백 제한


def hcxt_generate_sync(prompt: str, max_new_tokens: int = 512, prefill: str = "") -> str:
    """HyperCLOVA X 동기 추론. prefill이 있으면 답변 시작을 강제해 포맷을 고정한다."""
    import torch

    from app.utils.req_log import inc_hcxt
    inc_hcxt()
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
    """단일 GPU 모델 추론 직렬화(inference_lock 공유) + 타임아웃."""
    from app.ai.llm.inference_lock import hcxt_lock
    async with hcxt_lock():
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(hcxt_generate_sync, prompt, max_new_tokens, prefill),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.warning("HyperCLOVA X %s 최적화 타임아웃 (%.0fs)", kind, timeout)
            raise


async def fallback_optimize(prompt: str, *, max_tokens: int = 300, kind: str = "요소") -> str:
    """GPT-4o 폴백. 실패 시 빈 문자열 반환(호출부가 원문으로 폴백)."""
    if not config.openai_api_key:
        logger.error("FALLBACK: OPENAI_API_KEY 미설정")
        return ""
    import openai

    from app.utils.req_log import inc_gpt4o
    inc_gpt4o()
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
        return resp.choices[0].message.content.strip()
    except Exception as exc:
        logger.error("FALLBACK %s 최적화 실패: %s", kind, exc)
        return ""


def numbers_grounded(original: str, output: str) -> bool:
    """원본의 수치가 출력에 모두 존재하는지(환각·변조 방지). 시각 opt 수치 그라운딩 공통."""
    nums_in = set(re.findall(r"\d+(?:\.\d+)?", original))
    nums_out = set(re.findall(r"\d+(?:\.\d+)?", output))
    return nums_in.issubset(nums_out)


def decide_tier_timeout(
    ocr_confidence: float, standard_timeout: float, quality_timeout: float
) -> tuple[str, float]:
    """ocr_confidence → (routing_tier, timeout). 저신뢰=QUALITY, 그 외=STANDARD."""
    if ocr_confidence < config.ocr_confidence_threshold:
        return "QUALITY", quality_timeout
    return "STANDARD", standard_timeout


async def generate_with_retry(
    prompt: str, *,
    timeout: float, element_id, kind: str,
    prefill: str = "", max_new_tokens: int = 512, fallback_max_tokens: int = 300,
    transform: Optional[Callable[[str], str]] = None,
) -> tuple[str, bool]:
    """HCLOVA X 추론 3회 재시도 → 실패 시 GPT-4o 폴백. 반환: (응답, 폴백사용여부).

    transform은 HCLOVA X 응답에만 적용한다(폴백 응답은 그대로 — 기존 동작 보존).
    """
    fail = 0
    while fail < 3:
        try:
            resp = await hcxt_optimize(
                prompt, timeout, prefill=prefill, max_new_tokens=max_new_tokens, kind=kind
            )
            return (transform(resp) if transform else resp), False
        except Exception as exc:
            fail += 1
            logger.warning("HyperCLOVA X %s 실패 #%d id=%s: %s", kind, fail, element_id, exc)
            if fail >= 3:
                logger.warning("FALLBACK 전환 id=%s", element_id)
                resp = await fallback_optimize(prompt, max_tokens=fallback_max_tokens, kind=kind)
                return resp, True
    return "", True  # 도달하지 않음


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


class VisualDraftOpt(BaseOpt):
    """시각자료 3안 생성 공통 흐름(이미지·만화·차트). 하위 클래스는 프롬프트·라벨만 정의한다.

    하위 클래스 설정 항목:
      PROMPT             : {caption} 1개를 받는 프롬프트 문자열 (필수)
      PREFILL            : 답변 프리필 (없으면 "")
      METHODS            : [(render_mode, label), ...] 3안 (필수)
      RULE_ID            : rule_trail 규정 id (필수)
      EMPTY_MSG          : 캡션 없음 플레이스홀더
      DEFAULT_LABEL      : 파싱 실패 시 단일안 라벨
      KIND               : 로그용 유형명
      STANDARD/QUALITY_TIMEOUT, FALLBACK_MAX_TOKENS, MAX_NEW_TOKENS
    """

    PROMPT: str = ""
    PREFILL: str = ""
    METHODS: list[tuple[str, str]] = []
    RULE_ID: str = ""
    EMPTY_MSG: str = "[처리 불가: 캡션 없음]"
    DEFAULT_LABEL: str = "단일"
    KIND: str = "시각자료"
    STANDARD_TIMEOUT: float = 15.0
    QUALITY_TIMEOUT: float = 60.0
    FALLBACK_MAX_TOKENS: int = 300
    MAX_NEW_TOKENS: int = 512
    GROUND_NUMBERS: bool = False   # True면 초안에 원본 수치 누락 시 R5 표시(수치 변조 검출)

    def _trail(self, text: str) -> list[RuleApplication]:
        return [make_rule(self.RULE_ID)]

    async def _optimize_one(self, ext: ExtractedContent, routing_tier: str) -> LLMOutput:
        caption = ext.corrected_text or ""
        start = time.monotonic()

        if not caption.strip():
            return LLMOutput(
                element_id=ext.element_id,
                corrected_text=self.EMPTY_MSG,
                render_mode="narrative",
                routing_tier="FALLBACK",
                processing_time_ms=0,
                rule_trail=self._trail(self.EMPTY_MSG),
            )

        # ZERO/모델 미사용: 단일안으로 격리(생성 품질은 비ZERO에서만)
        if routing_tier == "ZERO":
            return self._build(ext.element_id, single_draft(caption[:120], "narrative", "원본"), "ZERO", 0)

        tier, timeout = decide_tier_timeout(ext.ocr_confidence, self.STANDARD_TIMEOUT, self.QUALITY_TIMEOUT)
        response, used_fb = await generate_with_retry(
            self.PROMPT.format(caption=caption),
            timeout=timeout, element_id=ext.element_id, kind=self.KIND,
            prefill=self.PREFILL, max_new_tokens=self.MAX_NEW_TOKENS,
            fallback_max_tokens=self.FALLBACK_MAX_TOKENS,
        )
        if used_fb:
            tier = "FALLBACK"

        drafts = parse_labeled_drafts(response, self.METHODS)
        if not drafts:  # 파싱 실패 → 응답(또는 원본 캡션 전체) 단일안 — 캡션을 자르지 않는다
            drafts = single_draft(response or caption, "narrative", self.DEFAULT_LABEL)

        self._post_process(ext, caption, drafts)
        elapsed_ms = int((time.monotonic() - start) * 1000)
        return self._build(ext.element_id, drafts, tier, elapsed_ms)

    def _post_process(self, ext: ExtractedContent, caption: str, drafts) -> None:
        """초안 후처리 훅. GROUND_NUMBERS=True면 수치 누락 초안에 R5 표시(공통 안전망).

        모델이 시각 캡션의 수치를 변조/누락(예: '3'→'5')해도 점역사가 R5로 검토하게 한다.
        초안을 원본으로 덮어쓰지 않는다(방식별 수치 표현 차이 보존 — chart 방식2 등).
        """
        if self.GROUND_NUMBERS and any(not numbers_grounded(caption, d.text) for d in drafts):
            logger.warning("수치 검증 경고 id=%s — 일부 초안에 원본 수치 누락 (R5)", ext.element_id)
            ext.flags = list(getattr(ext, "flags", None) or []) + ["R5"]

    def _build(self, element_id, drafts, tier, elapsed_ms) -> LLMOutput:
        return LLMOutput(
            element_id=element_id,
            corrected_text=drafts[0].text,
            render_mode=drafts[0].render_mode,
            tn_text=drafts[0].text,
            routing_tier=tier,
            processing_time_ms=elapsed_ms,
            rule_trail=self._trail(drafts[0].text),
            drafts=drafts,
            selected_idx=0,
        )
