"""영어 줄의 기울임 글자 → `<!기울임>`(이슈 #1205). 점역기는 아직 걷어 낸다(점자 불변).

라인 dict 는 PyMuPDF rawdict 형식을 본떠 손으로 짓는다(순환 검증 금지). fitz 가 기울임 비트를 실제로 주는지는
합성 PDF(기본 글꼴 Times-Italic) 한 장으로 본다. 코퍼스 묵자는 안 쓴다 — gold 이탤릭이 든 영어책 4권은 묵자 짝이 없다.
"""
import fitz
import pytest

from app.ai.braille.tag_names import ITALIC_TAG_RE
from app.ai.preprocessor.pdf_analyzer import _line_text_with_word_gaps, _page_text_blocks_spaced

IT, RO = 2 | 4, 4          # fitz 조각 flags: 기울임 2 · 세리프 4 (윗첨자는 1)


def _line(*spans) -> dict:
    """(글, flags, 글꼴, 크기) 조각들 → rawdict 줄. 글자 폭 5pt, 빈칸 글리프를 그대로 둔다."""
    out, x = [], 0.0
    for text, flags, font, size in spans:
        chars = []
        for c in text:
            chars.append({"c": c, "bbox": (x, 0.0, x + 5.0, 10.0)})
            x += 5.0
        out.append({"size": size, "flags": flags, "font": font, "chars": chars})
    return {"spans": out}


def _tag(line: dict) -> str:
    return _line_text_with_word_gaps(line, italic=True)


def test_영어_줄_기울임_낱말을_감싼다():
    line = _line(("He ", RO, "Times-Roman", 10), ("availed", IT, "Times-Italic", 10), (" himself.", RO, "Times-Roman", 10))
    assert _tag(line) == "He <!기울임>availed<!/기울임> himself."


def test_사이_빈칸이_바로선_조각이어도_한_구간():
    line = _line(("Jihun wants ", RO, "Times-Roman", 10), ("to", IT, "Times-Italic", 10), (" ", RO, "Times-Roman", 10),
                 ("buy", IT, "Times-Italic", 10), (" a bag.", RO, "Times-Roman", 10))
    assert _tag(line) == "Jihun wants <!기울임>to buy<!/기울임> a bag."


@pytest.mark.parametrize("line", [
    _line(("ab", IT, "ABCDEF+EHsang-Italic", 10), (" + cd = 1", RO, "Times-Roman", 10)),     # 한컴 수식 글꼴
    _line(("P", RO, "TKup", 10), ("max", IT, "TKupItalic", 6)),                               # 첨자(작은 글자)
    _line(("x", RO, "Times-Roman", 10), ("max", IT | 1, "Times-Italic", 10)),                # 윗첨자 비트
    _line(("김치는 ", RO, "Batang", 10), ("kimchi", IT, "Times-Italic", 10)),                # 한글 든 줄
    _line(("the letter ", RO, "Times-Roman", 10), ("a", IT, "Times-Italic", 10)),           # 한 글자
    _line(("year ", RO, "Times-Roman", 10), ("(", IT, "TKupItalic", 10), ("1990", RO, "Times-Roman", 10),
          (")", IT, "TKupItalic", 10)),                                                       # 로마자 없음
])
def test_수식_글꼴_첨자_한글_줄_한_글자는_안_감싼다(line):
    assert "<!" not in _tag(line)


def test_호출부가_안_켜면_종전_글():
    line = _line(("He ", RO, "Times-Roman", 10), ("availed", IT, "Times-Italic", 10))
    assert _line_text_with_word_gaps(line) == "He availed"


def test_스위치를_끄면_종전(monkeypatch):
    monkeypatch.setenv("ITALIC_TAG", "0")
    line = _line(("He ", RO, "Times-Roman", 10), ("availed", IT, "Times-Italic", 10))
    assert _tag(line) == "He availed"


def _pdf_page(*spans) -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=300, height=100)
    x = 20.0
    for text, font in spans:
        page.insert_text((x, 50), text, fontname=font, fontsize=11)
        x += fitz.get_text_length(text, fontname=font, fontsize=11)
    return page


def test_합성_PDF_에서_fitz_기울임_비트가_태그로_나온다():
    page = _pdf_page(("He ", "tiro"), ("availed", "tiit"), (" himself of every chance.", "tiro"))
    tagged = "\n".join(b["content"] for b in _page_text_blocks_spaced(page, italic=True))
    plain = "\n".join(b["content"] for b in _page_text_blocks_spaced(page))
    assert "<!기울임>availed<!/기울임>" in tagged
    assert ITALIC_TAG_RE.sub("", tagged) == plain          # 태그만 더한다


def test_MinerU_경로는_태그_없는_글로_판정하고_태그_든_글을_낸다():
    from app.ai.parser.mineru_runner import _native_override
    # 낱말 하나짜리 요소. 태그 13자를 닮음 판정에 넣으면 `Nara` 대 MinerU `Nara` 가 0.38 로 문턱(0.45) 밑이다.
    page = _pdf_page(("Nara", "tiit"))
    assert _native_override(page, [0, 0, 1000, 1000], "Nara") == "<!기울임>Nara<!/기울임>"


def test_점역기는_기울임_태그를_걷어_점자가_같다():
    from app.ai.braille.translator import translate_body, translate_tagged_text
    # 넷째가 입구에서 걷어야 하는 까닭이다. 늦게 걷으면 밑줄 안의 태그 때문에 영어 줄 밑줄(UEB ⠸⠶…⠸⠄, #1204)이
    # 한글 드러냄표 ⠠⠤…⠤⠄ 로 나간다.
    for src in ("He <!기울임>availed<!/기울임> himself of every chance.",
                "<!기울임>kimchi<!/기울임> fried rice, <!기울임>ramyeon<!/기울임>",
                "Jihun wants <!기울임>to buy<!/기울임> <!강조>a new bag<!/강조>.",
                "<!강조>He <!기울임>availed<!/기울임> himself<!/강조> of every chance."):
        assert translate_body(src) == translate_body(ITALIC_TAG_RE.sub("", src))
        assert translate_tagged_text(src) == translate_tagged_text(ITALIC_TAG_RE.sub("", src))


def test_기울임_든_요소도_빈칸_규칙_태깅이_산다():
    from app.ai.llm.text_opt import _tag_by_rule
    assert "<!밑줄>" in _tag_by_rule("He <!기울임>availed<!/기울임> ____ himself.")
