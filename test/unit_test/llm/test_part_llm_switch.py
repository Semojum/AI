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
    def test_기본값은_대장이_정한다(self, monkeypatch):
        """A/B 가 안 끝난 파트는 켬, 규칙이 이긴 파트는 `_PART_LLM_DEFAULT` 가 끔으로 뒤집는다."""
        for name in _PART_LLM_SWITCH.values():
            monkeypatch.delenv(name, raising=False)
        for k in _PART_LLM_SWITCH:
            assert part_llm_on(k) is (_PART_LLM_DEFAULT.get(k, "1") != "0")
        assert _PART_LLM_DEFAULT["태깅"] == "0"      # 4-4 판정(#754)

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
        monkeypatch.delenv(_PART_LLM_SWITCH[kind], raising=False)
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

    def test_끄면_규칙_팔이_돈다(self, monkeypatch):
        """LLM 은 안 부르고, 규정이 정한 자리는 태그된다(재구조화 4-4)."""
        monkeypatch.setenv("LAYOUT_TAG_LLM", "0")
        out, calls, _text = self._run(monkeypatch)
        assert calls == []
        assert out.startswith("<!상자>〈보기〉<!/상자>")       # 지침 1장5 2)(4)②
        assert "<!네모>" not in out                             # □ 는 안 건드린다(아래 참조)
        assert out.rstrip().endswith("<!상자끝><!/상자끝>")


    def test_기본은_규칙_팔(self, monkeypatch):
        """4-4 판정 뒤 태깅은 **규칙이 기본**이다 — 스위치가 없으면 LLM 을 안 부른다."""
        monkeypatch.delenv("LAYOUT_TAG_LLM", raising=False)
        _, calls, _ = self._run(monkeypatch)
        assert calls == []

    def test_1로_켜야_LLM_을_부른다(self, monkeypatch):
        monkeypatch.setenv("LAYOUT_TAG_LLM", "1")
        _, calls, _ = self._run(monkeypatch)
        assert calls == ["태깅"]


class TestTagByRule:
    """규칙 팔 단독 — 조문이 정한 자리만 태그하고 나머지는 손대지 않는다."""

    @pytest.fixture(autouse=True)
    def _mod(self):
        from app.ai.llm import text_opt
        self.text_opt = text_opt

    def test_밑줄_빈칸만_태그한다(self):
        """제73항 밑줄 빈칸은 태그하고, 글자 `□` 는 그대로 둔다.

        `□` 는 조문 조건("**채워 넣어야 할** 빈칸")이 글자만으로 안 서고, 실물에서는
        기호 인용·범례·가림이 대부분이다(2027 dev·val 822쪽 전수: 적중 0 · 초과 142).
        """
        out = self.text_opt._tag_by_rule("고성____ 그리고 기호 '□'는 남자다")
        assert out == "고성<!밑줄> 그리고 기호 '□'는 남자다"

    def test_표지_뒤에_글자가_붙으면_참조라_안_감싼다(self):
        src = "다음 설명만을 <보기>에서 고른 것은?"
        assert self.text_opt._tag_by_rule(src) == src

    def test_표지만_있고_내용이_없으면_안_감싼다(self):
        """몸통이 다른 요소에 있다 — 감싸면 빈 테두리 두 줄만 나간다."""
        assert self.text_opt._tag_by_rule("< 보 기 >") == "< 보 기 >"

    def test_이미_붙은_테두리는_안_겹친다(self):
        src = "<!상자2><자료 1><!/상자2>\n내용"
        assert self.text_opt._tag_by_rule(src) == src

    def test_관문을_통과하지_못하면_원문(self, monkeypatch):
        monkeypatch.setattr(self.text_opt, "_validate_tagging", lambda *_: False)
        assert self.text_opt._tag_by_rule("빈칸 ____ 하나") == "빈칸 ____ 하나"
