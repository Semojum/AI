"""체인 내부 요소 격리 회귀 테스트 (D-2).

버그: braille 모듈의 translate가 요소 목록을 한 번에 처리해, 한 요소의 점역이
예외를 던지면 같은 체인의 다른 요소까지 모두 잃었다(6-체인 단위 격리는 있었으나
체인 *내부* 격리가 없었음). 한 요소만 [처리 불가] placeholder로 격리되고 나머지는
정상 점역돼야 한다(불변 규칙 1·3).
"""
from __future__ import annotations

from uuid import uuid4

from app.ai.braille import text_braille as _tb
from app.ai.braille.isolation import safe_translate
from app.ai.braille.text_braille import TextBraille
from app.schemas.content import BrailleOutput, LLMOutput


def _opt(text: str) -> LLMOutput:
    return LLMOutput(element_id=uuid4(), corrected_text=text, routing_tier="ZERO")


class TestSafeTranslate:
    def test_한_요소_실패가_다른_요소를_막지_않음(self):
        opts = [_opt("정상1"), _opt("BAD"), _opt("정상2")]

        def translate_one(opt: LLMOutput) -> BrailleOutput:
            if opt.corrected_text == "BAD":
                raise ValueError("Invalid character")
            return BrailleOutput(element_id=opt.element_id, braille_lines=[opt.corrected_text])

        out = safe_translate(opts, translate_one)
        assert len(out) == 3                                  # 길이·순서 보존
        assert out[0].braille_lines == ["정상1"]
        assert out[2].braille_lines == ["정상2"]
        assert "[처리 불가" in "".join(out[1].braille_lines)  # 실패 요소만 placeholder
        assert out[1].element_id == opts[1].element_id        # element_id 보존
        assert out[1].rule_trail and out[1].rule_trail[0].rule_id  # 리뷰 #5: placeholder도 rule_trail 필수

    def test_전부_정상이면_placeholder_없음(self):
        opts = [_opt("가"), _opt("나")]
        out = safe_translate(
            opts, lambda o: BrailleOutput(element_id=o.element_id, braille_lines=[o.corrected_text])
        )
        assert all("[처리 불가" not in "".join(b.braille_lines) for b in out)


class TestTextBrailleIsolation:
    def test_TextBraille_실패요소_격리(self, monkeypatch):
        # translate_with_breaks가 'BAD' 포함 텍스트에서 raise하도록 강제(braillify 설치 무관 결정적).
        real = _tb.translate_with_breaks

        def fake(text: str):
            if "BAD" in text:
                raise ValueError("Invalid character")
            return real(text)

        monkeypatch.setattr(_tb, "translate_with_breaks", fake)

        opts = [_opt("안녕하세요"), _opt("BAD글자"), _opt("반갑습니다")]
        out = TextBraille().translate(opts)

        assert len(out) == 3
        assert "[처리 불가" in "".join(out[1].braille_lines)
        # 정상 요소는 placeholder가 아니어야 함
        assert "[처리 불가" not in "".join(out[0].braille_lines)
        assert "[처리 불가" not in "".join(out[2].braille_lines)
