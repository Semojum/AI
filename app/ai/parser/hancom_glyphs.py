"""한컴 수식 글꼴(EH*) 텍스트층 글자를 글리프 번호(GID)로 되돌린다(#1060).

한컴 수식 글꼴은 Type0(Identity-H) TrueType 부분집합이다. ToUnicode 가 비었거나 거짓이라 텍스트층이
글자를 잘못 알려 준다.
- 수학 I: ToUnicode 가 거의 비어 있어 fitz 가 **GID 번호 글자**를 낸다. EHsang 은 로마자를 −0x1F 밀어
  적어서 `log` 가 `MPH`(GID 77 · 80 · 72), `ABC` 가 `"#$` 가 된다. EHyak 의 `≤` 는 `\\x83`(GID 131)이다.
- 생명과학 I: ToUnicode 가 비ASCII 글리프를 라틴-1 글자로 매핑한다(₁ → `Á`, ₂ → `ª`). 이 글자 때문에
  층이 통째로 거부된다(`mineru_runner._layer_untrustworthy`).
- ★ **ToUnicode 도 믿지 않는다.** EHyak-Plain GID 12 는 윤곽이 ≠ 인데 다른 PDF 의 ToUnicode 는 `+` 다.
  그래서 EH 글꼴 글자는 ToUnicode 가 아니라 (글꼴, GID) 로 정한다.

표는 박힌 TTF 에서 윤곽을 그려 GID 마다 눈으로 읽은 것이다(d8c 2027 dev · val 1,746쪽, 근거 그림 V2
`temp/n68/ascii_EHsang-Plain.png` · `sheet_<글꼴>.png`, 계수 `temp/n68/결과_한컴글꼴복원.md`).
- EHsang 가족(Plain · Italic · Bold · BoldItalic) ASCII 영역(GID 1~95)은 chr(GID + 0x1F) 가 한결같다. 윤곽이 있는
  202자(70 · 59 · 57 · 16)를 모두 눈으로 봤고, 예외는 네 글꼴 모두 GID 64(`_` 가 아니라 ×) 하나다. 규칙은 **윤곽으로
  확인한 GID 에만** 건다(`_RULE_GIDS`). 윤곽 없는 GID 1 · 3 · 65 는 띄움 글리프다 — GID 3 을 규칙대로 풀면 `"` 가 된다.
- GID 65 는 한컴 수식의 가는 띄움(`` ` ``, EHsang 가족 넷 모두)이다. 쓰레기가 아니다 — 지우면 `log 2` 가
  `log2` 로 붙는다. 수학 I 은 EHsang-Italic GID 65 를 ToUnicode 로 `` ` `` 에 매핑해 둔다.
  보통 띄움으로 둔다(U+2009 · 백틱은 점역기가 칸을 더 넣는다, MinerU 의 `log 2` 가 gold 와 같다).
- 글리프 하나를 유니코드 글자 하나로 1:1 로 적는다(braille 09-30 17:57). 아래첨자 ₀~₉ · 이온 전하 ⁺ ⁻ ·
  위첨자 숫자 · ℃ · ° · 윗줄(결합 U+0305)은 점역기가 받는다. 글자 위첨자(ᴬ ᵃ ᴮ ᵇ …)는 유니코드 수식 글자로
  적고 점역기 쪽은 braille 이 B-22 로 맞춘다. 밑 글자를 묶는 LaTeX(`$X^{A}$`)는 쓰지 않는다 — 수식 조판을
  타서 식 앞뒤 빈칸이 생기고 로마자표가 빠진다(B-24 와 같은 병).
- EHhabu 는 아래첨자 글꼴이다(braille B-22 `Ô`=ᵢ 가 EHhabu-Italic GID 147).
- 분수 가로선 · 근호(EHboNA · EHboNB · EHRoot)는 구조 글리프라 손대지 않는다(스팬 #1055 몫).
"""
from __future__ import annotations

import os
import re

_SUBSET_RE = re.compile(r"^[A-Z]{6}\+")
# 윤곽으로 확인한 ASCII 영역 GID(d8c 2027 dev · val 박힌 부분집합, V2 `temp/n68/rule_gids.json`)
_RULE_GIDS: dict[str, frozenset] = {
    "EHsang-Plain": frozenset((6, 8, 9, 10, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 29, 30, 31, 32, 34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 55, 57, 58, 59, 64, 66, 67, 68, 69, 70, 71, 72, 73, 74, 76, 77, 78, 79, 80, 81, 83, 84, 85, 90, 91, 95)),
    "EHsang-Italic": frozenset((8, 9, 10, 12, 14, 15, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 29, 30, 31, 32, 34, 35, 36, 37, 42, 44, 45, 46, 47, 48, 51, 52, 53, 64, 66, 67, 68, 69, 71, 72, 73, 74, 75, 76, 77, 78, 79, 81, 82, 83, 84, 85, 89, 90, 91, 92, 93, 94)),
    "EHsang-Bold": frozenset((6, 10, 12, 14, 15, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 30, 31, 32, 34, 35, 36, 37, 38, 39, 40, 41, 42, 44, 45, 46, 47, 48, 49, 50, 51, 52, 53, 55, 57, 58, 59, 64, 66, 67, 68, 69, 70, 72, 73, 74, 77, 78, 79, 80, 83, 84, 85)),
    "EHsang-BoldItalic": frozenset((9, 10, 12, 14, 17, 18, 19, 27, 30, 31, 47, 66, 79, 85, 89, 90)),
}
_FAMILY_FIXED = {1: " ", 3: " ", 64: "×", 65: " "}       # 빈 글리프는 띄움, 64 는 규칙의 예외

_SUB = dict(zip("0123456789", "₀₁₂₃₄₅₆₇₈₉"))
_SUP = dict(zip("0123456789", "⁰¹²³⁴⁵⁶⁷⁸⁹"))
_THIN = " "                                   # 한컴 가는 띄움 — 위 docstring

GLYPHS: dict[str, dict[int, str]] = {
    "EHsang-Plain": {96: "ᴬ", 98: "ᵃ", 107: "ʳ", 121: "ᵈ", 125: "ᵇ", 162: "ᴿ", 166: "ᴰ", 168: "ᴴ", 173: "ᴮ", 178: "ʰ",
                     147: "\u0305", 101: _SUB["4"], 102: _SUB["3"], 109: _SUB["2"], 115: _SUB["5"], 116: "⁺",
                     129: "℃", 132: _SUB["1"], 145: "⁻", 153: _SUP["2"], 154: _SUP["3"], 155: _SUP["4"], 177: "°", 197: "!"},
    "EHsang-Italic": {120: "ᵐ", 136: "ˣ", 138: "ⁿ", 147: "\u0305", 100: _SUP["8"], 101: _SUB["4"], 102: _SUB["3"], 103: _SUB["6"], 104: _SUB["8"], 105: _SUB["7"],
                      109: _SUB["2"], 115: _SUB["5"], 116: "⁺", 126: _SUB["9"], 127: _SUB["0"], 132: _SUB["1"], 145: "⁻",
                      150: "÷", 152: _SUP["1"], 153: _SUP["2"], 154: _SUP["3"], 155: _SUP["4"], 156: _SUP["5"],
                      157: _SUP["6"], 158: _SUP["7"], 159: _SUP["9"], 160: _SUP["0"]},
    "EHsang-Bold": {101: _SUB["4"], 102: _SUB["3"], 109: _SUB["2"], 116: "⁺", 129: "℃", 132: _SUB["1"], 145: "⁻",
                    153: _SUP["2"]},
    "EHsang-BoldItalic": {102: _SUB["3"], 109: _SUB["2"], 131: _SUB["1"]},
    # EHyak 은 기호 글꼴이다. ToUnicode 가 로마자로 매핑해도 윤곽은 기호다(`l` = μ 81회 · `y` = … 641회 · `C` = * 115회 ·
    # `b` = β · `+` = ≠ · `!` = i) · `@` = ii) · `#` = iii)). 그래서 매핑된 글자도 이 표로 덮는다.
    "EHyak-Plain": {3: _THIN, 4: "iii)", 12: "≠", 14: "−", 32: "≒", 33: "ii)", 60: _THIN, 61: "α", 62: "β", 63: "γ",
                    68: "θ", 72: "μ", 76: "π", 85: "…", 93: "(viii)", 111: "·", 121: "≥", 131: "≤", 134: "±", 140: "(i)",
                    141: "(ii)", 142: "(iii)", 143: "(iv)", 144: "(v)", 145: "(vi)", 146: "(vii)", 162: "℃", 166: "*",
                    197: "i)"},
    "EHyak-Bold": {3: _THIN, 12: "≠", 61: "α", 62: "β", 68: "θ", 72: "μ", 76: "π", 166: "*"},
    "EHhabu-Italic": {98: "ₐ", 101: _SUB["4"], 102: _SUB["3"], 109: _SUB["2"], 115: _SUB["5"], 123: "ₚ", 125: _SUB["9"],
                      131: _SUB["1"], 147: "ᵢ"},
    "EHhabu-Plain": {109: _SUB["2"], 131: _SUB["1"], 151: _SUP["1"], 152: _SUP["2"], 154: _SUP["4"], 159: _SUP["0"]},
    # GID 28 · 49 · 29 는 긴 동치 화살표 ⟺ 한 벌이다(층 `HjK`, 수학 I body p0008 `a^x=N ⟺ x=log_a N`). 첫 글리프에 싣는다(#1072).
    "EHSunm-Plain": {83: "▬", 90: "→", 104: "➡", 28: "⟺", 49: "", 29: ""},
}

# 되돌리기가 적어 넣는 비ASCII 글자. 층을 믿을지 볼 때는 이 글자를 빼고 본다(#1072) — `²` · `³` · `¹` · `±` · `ʰ` · `ʳ` · `ˣ` 가
# `pdf_analyzer._MANGLED_LAYER_RE` 에 들어 있어, 제대로 되돌리면 그 결과 때문에 층이 다시 거부됐다.
EMITTED = frozenset(ch for t in (*GLYPHS.values(), _FAMILY_FIXED) for s in t.values() for ch in s if not ch.isascii())

def restore_on() -> bool:
    """EH 글꼴 글자를 GID 로 되돌린다. `TEXTLAYER_GLYPH_RESTORE=0` 이 종전이다. 호출 때 읽는다."""
    return os.environ.get("TEXTLAYER_GLYPH_RESTORE", "1") != "0"


def _font(name: str) -> str:
    return _SUBSET_RE.sub("", name or "")


def restored(font: str, gid: int) -> str | None:
    """(글꼴, GID) 의 참 글자. 모르거나 안 푸는 글리프면 None."""
    table = GLYPHS.get(font)
    if table and gid in table:
        return table[gid]
    if font in _RULE_GIDS:
        if gid in _FAMILY_FIXED:
            return _FAMILY_FIXED[gid]
        if gid in _RULE_GIDS[font]:
            return chr(gid + 0x1F)
    return None


def glyph_fixes(fitz_page) -> dict[tuple[str, float, float, str], list[str]]:
    """쪽의 EH 글꼴 글자 → 참 글자. 열쇠 = (글꼴, 원점 x, 원점 y, 층 글자), 값 = 그 열쇠에 놓인 차례대로의 참 글자.

    `get_texttrace()` 가 글자마다 GID 를 준다. rawdict 글자와 원점으로 맞춘다. 층 글자는 매핑이 없으면 chr(GID),
    있으면 매핑 글자다(fitz rawdict 와 같다). 쪽마다 한 번만 읽고 쪽 객체에 둔다(요소마다 부른다).
    ★ 위첨자 · 윗줄 글리프는 폭이 0 이라 뒤따르는 빈 글리프(가는 띄움)와 원점이 같다(d8c 2027 2,370곳, 수학 I `x²`
    1,693 · 생명과학 `Xᵃ`). 원점만으로 맞추면 띄움이 첨자를 덮어 첨자가 사라진다. 그래서 층 글자를 열쇠에 넣고
    같은 열쇠(둘 다 `` ` `` 로 매핑된 ᴬ · 띄움 81곳)는 차례로 쓴다.
    폭 0 글리프와 원점이 같은 빈 글리프와 그 뒤에 잇달린 빈 글리프는 띄움이 아니라 첨자의 폭이라 뺀다("").
    한컴은 첨자를 폭 없이 그리고 가는 띄움 한두 개로 그 폭만큼 나아간다(표본 675곳 중 139곳이 둘 이상).
    gold 는 붙여 쓴다(생명과학 `XᴬXᵃBbDD`). 보통 글자 뒤 가는 띄움은 띄움이다(`log 2`).
    """
    cached = getattr(fitz_page, "_hancom_glyph_fixes", None)
    if cached is not None:
        return cached
    fixes: dict[tuple[str, float, float, str], list[str]] = {}
    try:
        prev, width = None, False
        for span in fitz_page.get_texttrace():
            font = _font(span.get("font"))
            for ch in span.get("chars", ()):
                xy = (round(ch[2][0], 2), round(ch[2][1], 2))
                real = restored(font, ch[1]) if font.startswith("EH") else None
                width = real == " " and prev is not None and xy[1] == prev[1] and (width or abs(xy[0] - prev[0]) < 0.3)
                if width:
                    real = ""                              # 폭 0 글리프의 폭
                if real is not None:
                    raw = chr(ch[1]) if ch[0] == 0xFFFD else chr(ch[0])
                    fixes.setdefault((font, *xy, raw), []).append(real)
                prev = xy
    except Exception:                          # noqa: BLE001 — 되돌리기 실패는 종전 층 글로 둔다
        fixes = {}
    try:
        fitz_page._hancom_glyph_fixes = fixes
    except Exception:                          # noqa: BLE001
        pass
    return fixes


def line_subs(line: dict, fixes: dict) -> dict[int, str] | None:
    """rawdict 줄의 글자 번호(스팬을 이어 센다) → 되돌린 글자. 바뀌는 것이 없으면 None."""
    if not fixes:
        return None
    subs, i, seen = {}, 0, {}
    for span in line.get("spans", ()):
        font = _font(span.get("font"))
        for c in span.get("chars", ()):
            if font.startswith("EH"):
                o = c.get("origin") or (0, 0)
                key = (font, round(o[0], 2), round(o[1], 2), c.get("c"))
                reals = fixes.get(key)
                if reals:
                    n = seen[key] = seen.get(key, -1) + 1
                    real = reals[min(n, len(reals) - 1)]
                    if real != c.get("c"):
                        subs[i] = real
            i += 1
    return subs or None
