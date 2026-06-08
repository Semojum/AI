"""BRF Braille ASCII ↔ 유니코드 점자(U+2800–U+283F) 변환 — 표준 64셀 결정표.

규정·지침 원문의 점자 예시는 **Braille ASCII**(6점 64패턴을 ASCII 64자로 표기하는 표준)로
적혀 있다. 이를 유니코드 점자로 결정적으로 변환해 묵자↔점자 골드 쌍을 만든다.

표준 Braille ASCII 한 가지 변형만 쓴다(규정 예시 관례에 맞춤):
  · 글자는 **소문자**로 표기됨 → 대문자 표준셀과 동일 매핑(`a`=`A`=⠁).
  · 칸 사이 빈칸을 backtick(`` ` ``)으로 표기 → 공백 셀 ⠀. 리터럴 공백도 ⠀.

표는 추측이 아니라 표준이지만, `regulation_pairs`의 기존 골드(`brf_ascii`↔`braille_unicode`,
decode_ok=True)로 전수 교차검증한다(test_braille_ascii). 못 푸는 글자는 정직하게 `[?x]`로 남긴다.

사용:
    from app.utils.braille_ascii import ascii_to_unicode, unicode_to_ascii
    ascii_to_unicode("vr`ac+8")   # → '⠧⠗⠀⠁⠉⠬⠦'  ('왜 그러나요?')
"""

from __future__ import annotations

# 유니코드 점자 오프셋(0..63) 순서의 표준 Braille ASCII 문자.
# index n ↔ U+2800+n. (예: index 1='A'↔⠁, index 0x3C=60='#'↔수표 ⠼)
_BRAILLE_ASCII = (
    " A1B'K2L@CIF/MSP"      # 0x00–0x0F
    "\"E3H9O6R^DJG>NTQ"     # 0x10–0x1F
    ",*5<-U8V.%[$+X!&"      # 0x20–0x2F
    ";:4\\0Z7(_?W]#Y)="     # 0x30–0x3F
)
assert len(_BRAILLE_ASCII) == 64, f"Braille ASCII 표는 64자여야 함 (현재 {len(_BRAILLE_ASCII)})"

_SPACE_CELL = "⠀"  # U+2800 공백 셀

# 규정 관례는 글자뿐 아니라 대괄호·캐럿 블록도 소문자 시프트형으로 적는다.
#   표준 ASCII `[ \ ] ^` (0x5B–0x5E) → 시프트형 `{ | } ~` (0x7B–0x7E).
# 글자는 .upper()로 잡히지만 이 기호들은 안 잡혀 명시 remap이 필요하다.
_SHIFT_REMAP = {"{": "[", "|": "\\", "}": "]", "~": "^"}
_UNSHIFT_REMAP = {v: k for k, v in _SHIFT_REMAP.items()}  # 역변환용 ([→{, ^→~ …)

# ASCII 문자(대문자/기호) → 유니코드 점자 셀
_ASCII_TO_CELL: dict[str, str] = {ch: chr(0x2800 + i) for i, ch in enumerate(_BRAILLE_ASCII)}
# 유니코드 점자 셀 → ASCII 문자(역)
_CELL_TO_ASCII: dict[str, str] = {chr(0x2800 + i): ch for i, ch in enumerate(_BRAILLE_ASCII)}


def ascii_to_unicode(brf: str, *, strict: bool = False) -> str:
    """Braille ASCII 문자열 → 유니코드 점자. 못 푸는 글자는 `[?x]`(strict면 ValueError).

    소문자는 대문자로 정규화, backtick·리터럴 공백은 공백 셀 ⠀로 변환한다.
    줄바꿈은 그대로 보존한다.
    """
    out: list[str] = []
    for ch in brf:
        if ch == "\n":
            out.append("\n")
            continue
        if ch in ("`", " "):
            out.append(_SPACE_CELL)
            continue
        key = _SHIFT_REMAP.get(ch) or ch.upper()
        cell = _ASCII_TO_CELL.get(key)
        if cell is None:
            if strict:
                raise ValueError(f"Braille ASCII 미지원 글자: {ch!r}")
            out.append(f"[?{ch}]")
        else:
            out.append(cell)
    return "".join(out)


def unicode_to_ascii(braille: str, *, space: str = "`") -> str:
    """유니코드 점자 → Braille ASCII(소문자). 공백 셀은 `space`(기본 backtick)로.

    역변환은 표시·디버깅용. 못 푸는 셀은 `⟨XXXX⟩`(코드포인트)로 남긴다.
    """
    out: list[str] = []
    for ch in braille:
        if ch == "\n":
            out.append("\n")
            continue
        if ch == _SPACE_CELL or ch == " ":
            out.append(space)
            continue
        a = _CELL_TO_ASCII.get(ch)
        if a is None:
            out.append(f"⟨{ord(ch):04X}⟩")
        else:
            out.append(_UNSHIFT_REMAP.get(a) or a.lower())
    return "".join(out)
