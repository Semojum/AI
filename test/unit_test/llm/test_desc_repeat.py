"""개조식 설명이 같은 말을 되풀이하지 않는다 (2026-08-27).

개조식은 제목 줄 · 유형+짧은 설명 줄 · 전사 항목으로 선다. 캡셔너가 제목과 같은 말을
항목으로 또 내면 점역사가 지워야 할 줄이 생긴다.

실측(시연 12쪽 개조식 12개): 두 줄이 그대로 겹쳤다.
    그래프: $y=g(x)$의 그래프
    y=g(x)의 그래프        ← 지울 줄
`desc != title` 로만 걸러서는 못 잡는다 — 수식 구분자·공백·문장부호만 달라도 통과한다.
"""
import pytest

from app.ai.llm.visual_drafts import _outline_text_indents, _same_gist


def _plain(text):
    import re
    return [re.sub(r"<!/?[^>]*>", "", l).strip()
            for l in text.splitlines() if re.sub(r"<!/?[^>]*>", "", l).strip()]


class TestGist:
    @pytest.mark.parametrize("a,b", [
        ("$y=g(x)$의 그래프", "y=g(x)의 그래프"),
        ("비파형 동검 사진", "비파형 동검 사진"),
        ("‘가’의 구조", "가의 구조"),
    ])
    def test_구분자만_다르면_같은_말이다(self, a, b):
        assert _same_gist(a, b) is True

    @pytest.mark.parametrize("a,b", [
        ("두 삼각함수와 직선의 교점", "정의역 0~2π에서 교점 위치"),
        ("그래프", "표"),
        ("", "무엇"),
    ])
    def test_내용이_다르면_다른_말이다(self, a, b):
        assert _same_gist(a, b) is False


class TestOutline:
    def test_제목을_되풀이한_항목은_지운다(self):
        text, _ = _outline_text_indents(
            "그래프", "$y=g(x)$의 그래프", "y=g(x)의 그래프",
            [(0, "y=g(x)의 그래프"), (0, "직선 y=-x 형태")])
        lines = _plain(text)
        assert lines.count("y=g(x)의 그래프") == 0      # 제목 줄은 $ 가 붙어 따로 남는다
        assert "직선 y=-x 형태" in lines

    def test_내용이_있는_항목은_남긴다(self):
        text, indents = _outline_text_indents(
            "그래프", "두 삼각함수와 직선의 교점", "정의역 0~2π에서 교점 위치",
            [(0, "x=π/6: 모두 만남"), (1, "x=7π/6: 두 곡선만")])
        lines = _plain(text)
        assert "x=π/6: 모두 만남" in lines and "x=7π/6: 두 곡선만" in lines
        assert len(indents) == len(lines)

    def test_유형_줄은_제목과_같으면_유형어만_남는다(self):
        text, _ = _outline_text_indents("그림", "비파형 동검 사진", "비파형 동검 사진", [])
        lines = _plain(text)
        assert lines == ["비파형 동검 사진", "그림"]
