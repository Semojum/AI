"""HCXT 추론을 별도 vLLM OpenAI 호환 서버로 오프로드하는 클라이언트 (config.hcxt_backend="vllm").

인프로세스 transformers 추론(base_opt.hcxt_generate_sync)의 대체 경로. 14B는 vLLM 서버가 보유하고
(AWQ 양자화 self-host 권장), 파이프라인은 HTTP로 생성만 요청한다. 서버가 배칭/동시성을 처리하므로
GPU 락·페이지 누적 예산이 필요 없다(요소 병렬 추론).

동작 등가성: transformers 경로와 같은 non-think(skip_reasoning)·프리필·stop·그리디(temperature 0)를
쓴다 — 서버가 chat 템플릿을 적용하고, 프리필은 마지막 assistant 메시지 + continue_final_message로 준다.
반환값은 `prefill + 생성분`으로 transformers 경로와 동일하게 맞춰(각 opt의 _extract가 프리필 제거).
"""
from __future__ import annotations

from app.core.config import config

# 문자열 stop은 보조용(vLLM은 특수토큰을 응답에서 지워 실효 없음 — 실제 종료는
# config.hcxt_vllm_stop_token_ids). 텍스트로 노출되는 종료 표지가 있을 때만 잡힌다.
_STOP = ["<|endofturn|>", "<|stop|>"]


async def vllm_generate(prompt: str, max_new_tokens: int = 512, prefill: str = "") -> str:
    """vLLM 서버에 생성 요청. 반환 = prefill + 생성분(없으면 생성분).

    RuntimeError/네트워크 예외는 그대로 올려 호출부(generate_with_retry)가 GPT-4o로 폴백하게 한다.
    """
    import openai

    client = openai.AsyncOpenAI(base_url=config.hcxt_vllm_url, api_key="EMPTY")
    messages: list[dict] = [{"role": "user", "content": prompt}]
    # stop_token_ids 필수: vLLM은 skip_special_tokens=True로 <|endofturn|>/<|stop|> 문자열을
    # 응답에서 지워 문자열 stop이 무효 → id로 끊지 않으면 종료 토큰 넘겨 반복 생성한다.
    extra_body: dict = {
        "chat_template_kwargs": {"skip_reasoning": True},
        "stop_token_ids": config.hcxt_vllm_stop_token_ids,
    }
    if prefill:
        # 답변 시작 강제(포맷 고정) — 마지막 assistant 메시지를 이어쓰기.
        messages.append({"role": "assistant", "content": prefill})
        extra_body["continue_final_message"] = True
        extra_body["add_generation_prompt"] = False

    resp = await client.chat.completions.create(
        model=config.hcxt_vllm_model,
        messages=messages,
        max_tokens=max_new_tokens,
        temperature=0.0,          # 그리디 — transformers do_sample=False와 동일(재현성)
        stop=_STOP,
        extra_body=extra_body,
    )
    gen = (resp.choices[0].message.content or "").strip()
    return (prefill + gen) if prefill else gen
