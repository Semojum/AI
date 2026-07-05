"""opt 프롬프트 .format 무결성 — 중괄호 이스케이프 누락 시 KeyError 회귀 방지."""
import pytest


class TestPromptFormat:
    def test_visual_drafts_prompt_formats(self):
        # 시각자료 4안 공통 프롬프트는 {label}·{caption}을 받는다(KeyError 나면 실패).
        from app.ai.llm.visual_drafts import _PROMPT, _PREFILL
        out = _PROMPT.format(label="그림", caption="원 안에 삼각형")
        assert "원 안에 삼각형" in out and "그림" in out
        assert _PREFILL.startswith("[개조식]")   # 최적화 프롬프트: 개조식·줄글만 LLM 담당

    @pytest.mark.parametrize("mod", ["text_opt", "table_opt", "chart_graph_opt", "visual_drafts"])
    def test_other_opt_prompts_format(self, mod):
        import importlib
        m = importlib.import_module(f"app.ai.llm.{mod}")
        for name in dir(m):
            if name.startswith("_PROMPT"):
                tmpl = getattr(m, name)
                if not isinstance(tmpl, str) or "{" not in tmpl:
                    continue
                # 흔한 필드로 포맷 시도(KeyError 없어야) — label/caption/text/table_text 등
                try:
                    tmpl.format(label="x", caption="x", text="x", table_text="x",
                                latex="x", ocr_confidence=0.5)
                except KeyError as e:
                    pytest.fail(f"{mod}.{name} 미이스케이프 중괄호: {e}")
