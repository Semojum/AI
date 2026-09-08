"""opt 프롬프트 .format 무결성 — 중괄호 이스케이프 누락 시 KeyError 회귀 방지."""
import pytest


class TestPromptFormat:
    def test_시각_4안에는_프롬프트가_없다(self):
        """L8 LLM 팔은 2026-09-08 재구조화 5단계에서 지웠다 — 4안은 규칙 전사뿐이다."""
        from app.ai.llm import visual_drafts as vd
        assert not [n for n in dir(vd) if "PROMPT" in n], dir(vd)
        assert not hasattr(vd, "generate_with_retry")

    @pytest.mark.parametrize("mod", ["text_opt", "table_opt", "chart_graph_opt"])
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
