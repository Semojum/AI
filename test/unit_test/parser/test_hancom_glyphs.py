"""한컴 수식 글꼴(EH*) 텍스트층 글자를 글리프 번호(GID)로 되돌린다(#1060).

수학 I 은 ToUnicode 가 비어 fitz 가 GID 번호 글자를 낸다(`log` → `MPH`). ToUnicode 가 있어도 거짓일 수 있다
(EHyak GID 12 는 윤곽이 ≠ 인데 `+`). 그래서 EH 글꼴 글자는 (글꼴, GID) 로 정한다. 시험 PDF 에는 한컴 글꼴이
없어 helv 로 쓴 글자에 한컴 글꼴 texttrace(GID)를 입힌다.
"""
import fitz
import pytest

from app.ai.parser import hancom_glyphs as hg
from app.ai.parser import mineru_runner as mr


def test_EHsang_ASCII_영역은_GID_더하기_0x1F():
    assert "".join(hg.restored("EHsang-Plain", g) for g in (77, 80, 72)) == "log"      # MPH
    assert "".join(hg.restored("EHsang-Plain", g) for g in (34, 35, 36)) == "ABC"      # "#$
    assert hg.restored("EHsang-Italic", 89) == "x"


def test_규칙의_예외와_표():
    assert hg.restored("EHsang-Plain", 64) == "×"             # 규칙이면 `_`
    assert hg.restored("EHsang-Italic", 65) == " "            # 한컴 가는 띄움(규칙이면 백틱)
    assert hg.restored("EHyak-Plain", 131) == "≤"
    assert hg.restored("EHyak-Plain", 12) == "≠"              # 다른 PDF 의 ToUnicode 는 `+`
    assert hg.restored("EHsang-Plain", 109) == "₂"
    assert hg.restored("EHsang-Italic", 159) == "⁹"           # 생명 · 수학 PDF 가 `á` 로 매핑
    assert hg.restored("EHyak-Plain", 72) == "μ"              # ToUnicode `l` — 생명과학 `1.6 lm` 은 1.6 μm
    assert hg.restored("EHyak-Plain", 85) == "…"              # ToUnicode `y`


def test_첨자와_윗줄은_유니코드_한_글자로():
    """braille 09-30 17:57: 글리프 하나를 유니코드 하나로. 밑 글자를 묶는 LaTeX 는 안 쓴다."""
    assert hg.restored("EHsang-Plain", 96) == "ᴬ"             # 생명과학 유전자형 위첨자 A(MinerU `\x81`)
    assert hg.restored("EHsang-Plain", 147) == "\u0305"       # 윗줄(결합)
    assert hg.restored("EHhabu-Italic", 147) == "ᵢ"           # 아래첨자 글꼴(B-22 `Ô`)


def test_윤곽_없는_GID_와_구조_글꼴과_다른_글꼴은_안_푼다():
    assert hg.restored("EHsang-Plain", 3) == " "              # 빈 글리프는 띄움(규칙이면 `"`)
    assert hg.restored("EHsang-Plain", 2) is None             # 윤곽을 못 본 GID
    assert hg.restored("EHboNA-Plain", 30) is None            # 분수 조각
    assert hg.restored("NanumGothic", 77) is None


@pytest.fixture
def _helv_is_ehsang(monkeypatch):
    monkeypatch.setattr(hg, "_font", lambda n: "EHsang-Plain" if "Nimbus" in (n or "") else (n or ""))


def _page(*parts):
    """(글, 한컴 글꼴?) 조각을 한 줄에 쓰고, 한컴 글꼴 조각에는 fitz 가 매핑 없는 글자에 내는 꼴(GID = 글자 번호,
    유니코드 FFFD)로 texttrace 를 입힌다."""
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    tw = fitz.TextWriter(page.rect)
    pos = (60, 100)
    for text, eh in parts:
        tw.append(pos, text, font=fitz.Font("helv" if eh else "korea"), fontsize=12)
        pos = tw.last_point
    tw.write_text(page)
    trace = [{"font": sp["font"], "chars": [(0xFFFD, ord(c["c"]), c["origin"], c["bbox"]) for c in sp["chars"]]}
             for b in page.get_text("rawdict")["blocks"] for ln in b["lines"] for sp in ln["spans"] if "Nimbus" in sp["font"]]
    page.get_texttrace = lambda: trace
    return doc, page


BB = [0, 0, 1000, 1000]


def test_층_글에서_밀린_글자를_되돌린다(_helv_is_ehsang):
    doc, page = _page(("상용로그표에서 ", False), ("MPH", True), ("이므로", False))
    assert mr._native_text_spaced(page, BB) == "상용로그표에서 log이므로"


def test_스위치를_끄면_종전대로(_helv_is_ehsang, monkeypatch):
    monkeypatch.setenv("TEXTLAYER_GLYPH_RESTORE", "0")
    doc, page = _page(("상용로그표에서 ", False), ("MPH", True), ("이므로", False))
    assert mr._native_text_spaced(page, BB) == "상용로그표에서 MPH이므로"


def test_ToUnicode_가_있어도_GID_로_정한다(monkeypatch):
    """EHyak GID 12 를 ToUnicode 가 `+` 로 알려 줘도 윤곽대로 ≠ 로 적는다."""
    monkeypatch.setattr(hg, "_font", lambda n: "EHyak-Plain" if "Nimbus" in (n or "") else (n or ""))
    doc, page = _page(("조건 a", False), ("+", True), ("1", False))
    page.get_texttrace = lambda: [{"font": "NimbusSans-Regular", "chars": [(ord("+"), 12, c["origin"], c["bbox"])
                                   for b in page.get_text("rawdict")["blocks"] for ln in b["lines"] for sp in ln["spans"]
                                   if "Nimbus" in sp["font"] for c in sp["chars"]]}]
    assert mr._native_text_spaced(page, BB) == "조건 a≠1"


def test_쪽마다_한_번만_읽는다(_helv_is_ehsang):
    doc, page = _page(("상용로그표에서 ", False), ("MPH", True))
    calls = []
    real = page.get_texttrace
    page.get_texttrace = lambda: calls.append(1) or real()
    hg.glyph_fixes(page)
    hg.glyph_fixes(page)
    assert len(calls) == 1
