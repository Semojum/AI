"""네모 문자 (규정 제64항 · 원장 C-16-2) — 태깅과 점형.

규정 제64항: "…네모 문자는 `⠸⠦ ⠴⠇`으로 묶어 나타낸다."
묵자의 그 네모는 **벡터 드로잉이라 텍스트 추출에 안 잡힌다**. 추출물에는 `(가)`만 남아
지문 빈칸 ▯(가)▯ 와 문두 지시 `(가)`가 구분 없이 같은 출력이 됐다. 쪽 맞춘 전수 대조에서
우리 414 대 gold 867(−453)이었고 미달의 대부분이 이 자리다.

검출은 `char_box_glyphs`(작은 획 사각형이 감싼 짧은 토큰)이고, 여기서는 **태깅과 점형**을 본다.
"""
from __future__ import annotations

from app.ai.braille import tag_names as _TAGS
from app.ai.braille.translator import translate_tagged_text
from app.ai.preprocessor.pdf_analyzer import tag_char_boxes

OPEN, CLOSE = f"<!{_TAGS.BOX_CHAR}>", f"<!/{_TAGS.BOX_CHAR}>"


def _el(content: str, bbox: tuple[float, ...]) -> dict:
    return {"type": "text", "content": content, "bbox": list(bbox)}


class TestTagging:
    def test_상자_안_토큰만_감싼다(self) -> None:
        els = [_el("전쟁 중에 (가) 이/가 남긴", (60, 300, 500, 330))]
        assert tag_char_boxes(els, [("(가)", [120, 305, 150, 325])]) == 1
        assert els[0]["content"] == f"전쟁 중에 {OPEN}(가){CLOSE} 이/가 남긴"

    def test_같은_토큰이_여러_번이면_상자_수만큼_앞에서부터(self) -> None:
        """한 요소에 지시문 `(가)`와 빈칸 `(가)`가 같이 오는 쪽이 흔하다. 자리까지는
        못 맞춰도 **개수는 맞춘다** — 추출물에 글자별 좌표가 없다."""
        els = [_el("(가)와 (가)를 비교", (60, 300, 500, 330))]
        assert tag_char_boxes(els, [("(가)", [70, 305, 100, 325])]) == 1
        assert els[0]["content"].count(OPEN) == 1
        assert els[0]["content"].startswith(f"{OPEN}(가){CLOSE}와")

    def test_상자_밖_요소에는_안_붙는다(self) -> None:
        els = [_el("(가) 황제의 재위 시기에", (60, 700, 500, 730))]
        assert tag_char_boxes(els, [("(가)", [120, 305, 150, 325])]) == 0
        assert OPEN not in els[0]["content"]

    def test_요소에_없는_토큰은_건너뛴다(self) -> None:
        els = [_el("본문만 있다", (60, 300, 500, 330))]
        assert tag_char_boxes(els, [("답", [120, 305, 150, 325])]) == 0


class TestBraille:
    def test_제64항_점형으로_묶는다(self) -> None:
        out = translate_tagged_text(f"{OPEN}답{CLOSE}")
        assert out.startswith("⠸⠦") and out.rstrip("\n").endswith("⠴⠇")
        assert "⠊⠃" in out          # 안쪽 '답'이 그대로 점역된다

    def test_빈_네모와_다른_태그다(self) -> None:
        """`네모`(빈칸)는 단독으로 여는·빈칸·닫는을 통째로 내고(제73항), `네모글`은 감싼다."""
        blank = translate_tagged_text(f"<!{_TAGS.BLANK_SQUARE}>")
        assert "⠸⠦⠀⠴⠇" in blank
        assert _TAGS.BOX_CHAR != _TAGS.BLANK_SQUARE
