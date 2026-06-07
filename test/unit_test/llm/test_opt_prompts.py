"""opt 프롬프트 .format 무결성 — 중괄호 이스케이프 누락 시 KeyError 회귀 방지."""
import pytest


class TestPromptFormat:
    def test_image_prompt_formats(self):
        from app.ai.llm.image_opt import _PROMPT, _PREFILL
        out = _PROMPT.format(caption="원 안에 삼각형")   # KeyError 나면 실패
        assert "원 안에 삼각형" in out
        assert _PREFILL.startswith("[방식1]")

    def test_cartoon_is_rule_based(self):
        # 만화는 자유 프롬프트가 아니라 규정 골격(§5.3) rule-based 조립이다.
        from app.ai.llm.cartoon_opt import assemble_cartoon
        text, indents = assemble_cartoon({"title": "T", "panels": [
            {"order": 1, "dialogues": [{"speaker": "갑", "text": "안녕"}]}]})
        assert "<!점역자주>만화<!/점역자주>" in text and "갑:안녕" in text
        assert len(indents) == len(text.split("\n"))

    @pytest.mark.parametrize("mod", ["text_opt", "table_opt", "chart_graph_opt"])
    def test_other_opt_prompts_format(self, mod):
        import importlib
        m = importlib.import_module(f"app.ai.llm.{mod}")
        for name in dir(m):
            if name.startswith("_PROMPT"):
                tmpl = getattr(m, name)
                if not isinstance(tmpl, str) or "{" not in tmpl:
                    continue
                # caption/text/table_text/ocr_confidence 등 흔한 필드로 포맷 시도(KeyError 없어야)
                try:
                    tmpl.format(caption="x", text="x", table_text="x", latex="x", ocr_confidence=0.5)
                except KeyError as e:
                    pytest.fail(f"{mod}.{name} 미이스케이프 중괄호: {e}")
