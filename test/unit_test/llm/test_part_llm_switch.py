"""파트별 LLM 끄기 손잡이 (재구조화 0-d · 스위치 대장 2026-09-08).

4단계 A/B 의 되돌리는 길이다. 확인할 것 셋:
  1. **기본은 켬** — 스위치를 안 주면 현행 그대로 LLM 을 부른다(동작 변화 0).
  2. **끄면 호출이 0** — 0/1 로 갈리는 것을 호출 계수로 본다.
  3. **호출 시 읽는다** — import 때 굳으면 프로세스 중간에 바꿔도 안 먹고,
     "껐다고 믿었는데 안 꺼진" 무효 라운드가 난다(2026-09-03 두 번).
"""
import asyncio

import pytest

from app.ai.llm.base_opt import _PART_LLM_DEFAULT, _PART_LLM_SWITCH, part_llm_on


class TestPartLlmOn:
    def test_기본값은_대장대로(self, monkeypatch):
        """스위치를 안 주면 `_PART_LLM_DEFAULT` 대로. A/B 가 끝난 자리만 규칙이 기본이다."""
        for name in _PART_LLM_SWITCH.values():
            monkeypatch.delenv(name, raising=False)
        for kind in _PART_LLM_SWITCH:
            assert part_llm_on(kind) is (_PART_LLM_DEFAULT.get(kind, "1") != "0")

    def test_표는_규칙이_기본(self, monkeypatch):
        """#755 (4-3) — 표 tn 은 점자에 안 실린다. 되돌리는 길은 `TABLE_TN_LLM=1`."""
        monkeypatch.delenv("TABLE_TN_LLM", raising=False)
        assert part_llm_on("표") is False
        monkeypatch.setenv("TABLE_TN_LLM", "1")
        assert part_llm_on("표") is True

    def test_0_이면_끔(self, monkeypatch):
        for kind, name in _PART_LLM_SWITCH.items():
            monkeypatch.setenv(name, "0")
            assert part_llm_on(kind) is False
            monkeypatch.setenv(name, "1")
            assert part_llm_on(kind) is True

    def test_모르는_파트는_늘_켬(self, monkeypatch):
        """스위치가 없는 파트(시각·텍스트)는 이 손잡이가 안 건드린다."""
        monkeypatch.setenv("FORMULA_OPT_LLM", "0")
        assert part_llm_on("텍스트") is True


class TestGenerateWithRetryGate:
    """`generate_with_retry` 는 스위치가 꺼지면 추론을 아예 안 부른다."""

    def _run(self, kind, monkeypatch):
        from app.ai.llm import base_opt

        calls = []

        async def _spy(*a, **kw):
            calls.append(kw.get("kind"))
            return "LLM 이 낸 글"

        monkeypatch.setattr(base_opt, "hcxt_optimize", _spy)
        monkeypatch.setattr(base_opt, "fallback_optimize", _spy)
        out = asyncio.run(base_opt.generate_with_retry(
            "프롬프트", timeout=1.0, element_id="e1", kind=kind))
        return out, calls

    @pytest.mark.parametrize("kind", sorted(k for k in _PART_LLM_SWITCH if k != "태깅"))
    def test_끄면_호출_0(self, kind, monkeypatch):
        monkeypatch.setenv(_PART_LLM_SWITCH[kind], "0")
        out, calls = self._run(kind, monkeypatch)
        assert out == ("", False)
        assert calls == []

    @pytest.mark.parametrize("kind", sorted(k for k in _PART_LLM_SWITCH if k != "태깅"))
    def test_켜면_호출_1(self, kind, monkeypatch):
        monkeypatch.setenv(_PART_LLM_SWITCH[kind], "1")
        out, calls = self._run(kind, monkeypatch)
        assert out == ("LLM 이 낸 글", False)
        assert calls == [kind]

    def test_호출시_읽는다(self, monkeypatch):
        """같은 프로세스 안에서 껐다 켜면 그대로 먹어야 한다(import 때 굳으면 실패)."""
        monkeypatch.setenv("TABLE_TN_LLM", "0")
        assert self._run("표", monkeypatch)[1] == []
        monkeypatch.setenv("TABLE_TN_LLM", "1")
        assert self._run("표", monkeypatch)[1] == ["표"]


class TestLayoutTagGate:
    """레이아웃 태깅은 `generate_with_retry` 를 안 쓴다 — 따로 막는다."""

    def _run(self, monkeypatch):
        from app.ai.llm import text_opt

        calls = []

        async def _spy(*a, **kw):
            calls.append(kw.get("kind"))
            return "<!제목>태그 낀 글"

        monkeypatch.setattr(text_opt, "fallback_optimize", _spy)
        monkeypatch.setattr(text_opt.model_manager, "get_status",
                            lambda: {"hcxt_loaded": False})
        text = "〈보기〉\n□ 첫째 조건\n□ 둘째 조건\n"   # `_TAG_CANDIDATE_RE` 후보 신호
        return asyncio.run(text_opt._tag_layout(text)), calls, text

    def test_끄면_원문_그대로(self, monkeypatch):
        monkeypatch.setenv("LAYOUT_TAG_LLM", "0")
        out, calls, text = self._run(monkeypatch)
        assert out == text
        assert calls == []

    def test_켜면_LLM_을_부른다(self, monkeypatch):
        monkeypatch.delenv("LAYOUT_TAG_LLM", raising=False)
        _, calls, _ = self._run(monkeypatch)
        assert calls == ["태깅"]
