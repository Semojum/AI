"""한컴 수식 글꼴(EH*) 텍스트층 글자를 글리프 번호(GID)로 되돌린다(#1060).

수학 I 은 ToUnicode 가 비어 fitz 가 GID 번호 글자를 낸다(`log` → `MPH`). ToUnicode 가 있어도 거짓일 수 있다
(EHyak GID 12 는 윤곽이 ≠ 인데 `+`). 그래서 EH 글꼴 글자는 (글꼴, GID) 로 정한다. 시험 PDF 에는 한컴 글꼴이
없어 helv 로 쓴 글자에 한컴 글꼴 texttrace(GID)를 입힌다.
"""
import types

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


def test_폭_0_첨자와_원점이_같은_띄움이_첨자를_덮지_않는다():
    """위첨자 글리프는 폭이 0 이라 뒤 가는 띄움과 원점이 같다(생명과학 유전자형 XᴬXᵃ, 수학 I x² 1,693곳).
    ᴬ(GID 96)와 띄움(GID 65)은 둘 다 `` ` `` 로 매핑돼 층 글자까지 같다 — 차례로 맞춘다. 첨자와 원점이 같은
    띄움과 거기 잇달린 띄움은 첨자의 폭이라 뺀다(gold `XᴬXᵃ`). 보통 글자 뒤 띄움은 띄움이다(`log 2`).
    (fitz 는 같은 자리 같은 글리프를 하나로 줄여 PDF 로 못 만든다)"""
    raw, xs = "9```9b`:", (10, 17, 17, 19, 21, 28, 28, 30)
    gids = (57, 96, 65, 65, 57, 98, 65, 58)                    # X ᴬ (폭) 띄움 X ᵃ (폭) Y
    trace = [{"font": "ABCDEF+EHsang-Plain", "chars": [
        (ord(c) if c == "`" else 0xFFFD, g, (x, 100.0), None) for c, g, x in zip(raw, gids, xs)]}]
    page = types.SimpleNamespace(get_texttrace=lambda: trace)
    line = {"spans": [{"font": "ABCDEF+EHsang-Plain", "chars": [{"c": c, "origin": (x, 100.0)} for c, x in zip(raw, xs)]}]}
    subs = hg.line_subs(line, hg.glyph_fixes(page))
    assert "".join(subs.get(i, c) for i, c in enumerate(raw)) == "XᴬXᵃY"

    raw, xs, gids = "MPH`\x13", (40, 46, 52, 58, 61), (77, 80, 72, 65, 19)
    trace[0]["chars"] = [(ord(c) if c == "`" else 0xFFFD, g, (x, 120.0), None) for c, g, x in zip(raw, gids, xs)]
    page = types.SimpleNamespace(get_texttrace=lambda: trace)
    line = {"spans": [{"font": "ABCDEF+EHsang-Plain", "chars": [{"c": c, "origin": (x, 120.0)} for c, x in zip(raw, xs)]}]}
    subs = hg.line_subs(line, hg.glyph_fixes(page))
    assert "".join(subs.get(i, c) for i, c in enumerate(raw)) == "log 2"


def test_쪽마다_한_번만_읽는다(_helv_is_ehsang):
    doc, page = _page(("상용로그표에서 ", False), ("MPH", True))
    calls = []
    real = page.get_texttrace
    page.get_texttrace = lambda: calls.append(1) or real()
    hg.glyph_fixes(page)
    hg.glyph_fixes(page)
    assert len(calls) == 1


def test_긴_동치_화살표_한_벌과_되돌리기가_적는_글자():
    """#1072 — EHSunm-Plain GID 28 · 49 · 29 는 ⟺ 한 벌(층 `HjK`). EMITTED 는 판정용 사본에서 뺄 비ASCII 글자."""
    assert [hg.restored("EHSunm-Plain", g) for g in (28, 49, 29)] == ["⟺", "", ""]
    assert {"²", "₁", "μ", "⁺", "×"} <= hg.EMITTED and not any(c.isascii() for c in hg.EMITTED)


def test_큰_괄호_종류와_적분_합성():
    """#1082 다음 묶음 — 수학 II 윤곽 + 지면 독립 검증(gold 무관). 큰 괄호 글꼴은 층이 괄호 종류를 바꿔 준다:
    91 · 93 층 `{` `}` = 큰 소괄호, 60 · 61 층 `[` `]` = 큰 중괄호. ∫ 은 층 `:`, 합성 ∘ 은 층 `ç`."""
    assert [hg.restored("EHboNA-Plain", g) for g in (91, 93, 60, 61, 63)] == ["(", ")", "{", "}", "×"]
    assert [hg.restored("EHSusic-Plain", g) for g in (27, 10, 197, 34, 64, 5)] == ["∫", "₀", "₁", "ₐ", "₋", "⁴"]
    assert hg.restored("EHyak-Plain", 151) == "∘"
    assert hg.restored("EHboNA-Plain", 28) is None                 # 분수 조각은 1:1 로 못 되살린다(#1055 몫)


def test_376_윤곽으로_본_글자():
    """#376 A — dev 에서 본 거짓 글자 꼴을 박힌 글꼴 윤곽으로 읽은 것(V2 temp/n198/glyph/sheet_*.png)."""
    assert hg.restored("EHSusic-Plain", 132) == "∑"          # 층 `Á`(수학 I 수열)
    assert hg.restored("EHKiho-Plain", 20) == "μ"            # 층 `%`
    assert hg.restored("EHsang-Italic", 197) == "!"          # 층도 `!`, 규칙(GID+0x1F) 밖
    assert hg.restored("EHsang-Plain", 160) == "⁰"           # 층 `â`
    assert [hg.restored("EHhabu-Plain", g) for g in (119, 137, 147, 144, 153)] == ["ₘ", "ₙ", "ᵢ", "⁻", "³"]
    assert hg.restored("EHSunm-Plain", 47) is None           # 큰 괄호 조각은 글자 1:1 이 아니라 안 넣는다
    assert hg.restored("EHSunm-Plain", 10) == ""             # 긴 화살표 몸통(뒤에 머리 90 → 가 붙는다)


def test_376_모르는_글리프에서_빼는_것():
    """#376 B — 구조 글꼴 · 띄움 · 층 글자가 GID+0x1F 와 같은 것 · 표에 있는 것은 '모르는 글리프'가 아니다."""
    trace = [{"font": "ABCDEF+EHboNA-Plain", "chars": [(0xFFFD, 28, (10, 100.0), None)]},      # 분수 가로선
             {"font": "ABCDEF+EHSunm-Plain", "chars": [(0x2009, 3, (20, 100.0), None),          # 띄움
                                                     (ord("g"), 47, (30, 100.0), None),         # 큰 괄호 조각 → 모름
                                                     (ord("Ú"), 90, (40, 100.0), None)]},       # → (표에 있음)
             {"font": "ABCDEF+EHsang-Plain", "chars": [(ord("!"), 2, (50, 100.0), None)]}]      # chr(2+0x1F)
    page = types.SimpleNamespace(get_texttrace=lambda: trace)
    assert hg.unknown_glyphs(page) == frozenset({("EHSunm-Plain", 30, 100.0, "g")})


def test_376_표에_없는_글리프가_든_블록은_MinerU_글을_둔다(monkeypatch):
    """#376 B — EHSunm 큰 괄호 조각(GID 47)을 ToUnicode 가 `g` 로 알려 준다. 멀쩡한 글자로 보여 층 거부 검사에
    안 걸리고 MinerU 글을 덮었다. 표에 없는 글리프가 든 블록은 층을 안 믿는다. 스위치를 끄면 종전대로 층이 이긴다."""
    monkeypatch.setattr(hg, "_font", lambda n: "EHSunm-Plain" if "Nimbus" in (n or "") else (n or ""))
    doc, page = _page(("연립방정식 ", False), ("g", True), ("x+y=3", False))
    chars = [c for b in page.get_text("rawdict")["blocks"] for ln in b["lines"] for sp in ln["spans"]
             if "Nimbus" in sp["font"] for c in sp["chars"]]
    page.get_texttrace = lambda: [{"font": "NimbusSans-Regular", "chars": [(ord("g"), 47, c["origin"], c["bbox"]) for c in chars]}]
    assert mr._has_unknown_glyph(page, BB)
    assert mr._native_override(page, BB, "연립방정식 {x+y=3") is None
    monkeypatch.setattr(mr, "_UNKNOWN_GLYPH_GUARD", False)
    assert mr._native_override(page, BB, "연립방정식 {x+y=3") is not None
