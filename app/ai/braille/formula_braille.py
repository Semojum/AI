"""PART 5-3 — 수식 점역 (kor_math_rules KOR_MATH 엔진)."""

from __future__ import annotations

import re

from app.ai.braille.isolation import BLOCKED_TEXT_PREFIXES, blocked_braille, safe_translate
from app.ai.braille.kor_math_rules import BREAK_MARK as _MARK, convert_latex, latex_rule_ids
from app.ai.braille.regulations import make_rule
from app.schemas.content import BrailleOutput, LLMOutput


def _space_breaks(s: str) -> list[int]:
    """공백(두 칸 공백 등) 경계 = 줄바꿈 허용 지점."""
    return [i for i, ch in enumerate(s) if ch in (" ", "⠀") and 0 < i < len(s)]


# 수식 안 끊을 자리 — 「한국 점자 규정」 수학 점자 제66항(재추출 4287~4288행): "한 수식이 두 줄 이상 이어질 경우에는
#   사칙연산, 등호, 분수표 뒤에서 줄바꿈을 하고 그렇지 않은 경우에는 식의 연결표 ⠠ 을 적는다." 과학 점자 제31항(5007행)
#   예는 ≒ 뒤에서도 끊어 부등호 · 근사 같은 관계 기호를 등호 갈래로 본다(원장 R-93). gold 수학 Ⅰ(dev 009) 긴 수식 174개의
#   줄바꿈 216곳: 등호 130 · 덧셈 32 · 곱셈 21 · 뺄셈 18 · 분수표 11 · 부등호 < 3 · 비 ⠐⠂ 1, 연결표 0. 연결표를 쓰는 자리는
#   조판이 셀을 더해야 해 끊을 자리(`breaks`)로는 못 준다.
# 자리는 LaTeX 의 그 기호 뒤에 표시 글자를 넣어 점역해 찾는다. 표시를 지운 점자가 표시 없이 점역한 것과 같을 때만 쓴다
#   (조판이 셀을 옮기는 자리에서 표시가 엉뚱한 데 서지 않게). 첨자 · `\text` 안 기호와 부호(앞이 피연산자가 아닌 + −)는 뺀다.
_BREAK_AFTER = re.compile(r"\\(?:times|div|cdot|leq|geq|le|ge|neq|ne|approx|fallingdotseq|doteq)(?![A-Za-z])|[=<>≤≥≠≒×÷]")
_SIGN = frozenset("+-−")
_BIN_CMD = re.compile(r"\\(?:times|div|cdot)(?![A-Za-z])|[×÷]")
_FRAC = re.compile(r"\\[dt]?frac(?![A-Za-z])")
_ENV_HEAD = re.compile(r"\\begin\{\w+\*?\}(?:\{[^{}]*\})?$")   # 배열 머리 `\begin{array}{l}` 의 `}` 는 피연산자가 아니다
_TEXT_CMD = re.compile(r"\\(?:text|textrm|mbox|mathrm|operatorname)\s*$")


def _operand_before(latex: str, i: int) -> bool:
    """`latex[i]` 기호 앞이 피연산자인가. 아니면(맨 앞 · 여는 괄호 · 연산 · 관계 기호 · 쉼표 · 배열 줄 `\\\\` 뒤) + · − 는 부호이고,
    등호 · 관계 기호는 앞 줄을 이어 받는 머리라 뒤에서 끊을 까닭이 없다(제66항은 두 항 사이 기호 뒤다)."""
    j = i - 1
    while j >= 0 and latex[j].isspace():
        j -= 1
    if j < 0 or _ENV_HEAD.search(latex, 0, j + 1):
        return False
    if latex[j].isalnum():
        k = j
        while k >= 0 and latex[k].isalpha():
            k -= 1
        if k >= 0 and latex[k] == "\\":            # 명령 이름 끝 — 관계 · 연산 명령 뒤는 부호다(`\leq -3`)
            return not _BREAK_AFTER.match(latex, k) and latex[k:j + 1] not in ("\\pm", "\\mp", "\\to", "\\in")
        return True
    return latex[j] in ")]}|!'′"


def _op_marks(latex: str) -> list[tuple[int, str, tuple[int, ...]]]:
    """표시를 넣어 볼 LaTeX 자리 후보 `(깊이, 갈래, 자리들)`. 자리는 그 앞 글자 뒤이고 기호마다 (기호와 뒤 빈칸 다음,
    기호 바로 다음), 분수는 (분자 여는 중괄호 다음,)이다. 깊이는 감싼 괄호 · 묶음 수, 갈래는 rel(등호 · 부등호) ·
    bin(사칙연산) · frac(분수표)."""
    out, stack, pending, paren, fdepth = [], [], 0, 0, 0   # stack: 그룹 종류(script · text · num · den · group)
    i, n = 0, len(latex)
    while i < n:
        c = latex[i]
        skip = any(k in ("script", "text") for k in stack)
        depth = len(stack) + paren
        if pending and c not in "{ \t\n":         # 중괄호 없는 분수(`\frac12`)는 분자 자리를 안 잡는다
            pending = 0
        if c == "{":
            j = i - 1
            while j >= 0 and latex[j].isspace():
                j -= 1
            if j >= 0 and latex[j] in "^_":
                kind = "script"
            elif _TEXT_CMD.search(latex, 0, i):
                kind = "text"
            elif pending:
                kind = "num" if pending == 2 else "den"
                pending -= 1
                if kind == "num" and not skip:
                    out.append((fdepth, "frac", (i + 1,)))
            else:
                kind = "group"
            stack.append(kind)
            i += 1
            continue
        if c == "}":
            if stack:
                stack.pop()
            i += 1
            continue
        if c in "([":
            paren += 1
        elif c in ")]":
            paren = max(0, paren - 1)
        if c == "\\":
            m = _FRAC.match(latex, i)
            if m:
                pending, fdepth = (0 if skip else 2), depth
                i = m.end()
                continue
            if latex[i + 1:i + 2] in ("{", "}"):        # 집합 중괄호 \{ \}
                paren = paren + 1 if latex[i + 1] == "{" else max(0, paren - 1)
                i += 2
                continue
        m = _BREAK_AFTER.match(latex, i)
        end = (m.end() if m else i + 1 if c in _SIGN else 0) if _operand_before(latex, i) else 0
        if end:
            k = end
            while k < n and latex[k].isspace():
                k += 1
            if not skip and k < n:
                rel = bool(m) and not _BIN_CMD.match(latex, i)
                out.append((depth, "rel" if rel else "bin", (k, end) if k != end else (end,)))
            i = max(end, i + 1)
            continue
        if c == "\\":                           # 다른 명령은 이름째 넘긴다(`\leftarrow` 의 `-` 없음 · `\text` 판정)
            j = i + 1
            while j < n and latex[j].isalpha():
                j += 1
            i = max(j, i + 1)
            continue
        i += 1
    return out


# 끊을 자리 바로 앞에 올 수 있는 셀 — 연산 · 관계 기호와 분수표의 끝 셀(+ ⠢ · − ⠔ · = ⠒⠒ · × ⠡ · ÷ ⠌⠌ · · ⠐ ·
#   < ⠔⠔ · > ⠢⠢ · ≤ ⠖⠖ · ≥ ⠲⠲ · ≠ ⠨⠒⠒ · 분수표 ⠌). 표시가 기호 뒤가 아닌 데로 밀려 선 것을 버린다.
_OP_TAIL = frozenset("⠢⠔⠒⠡⠌⠐⠖⠲")


def _op_candidates(latex: str, braille: str) -> list[tuple[int, int, str]]:
    """수식 점자 `braille`(= `convert_latex(latex)`) 안 제66항 끊을 자리 후보 `(셀 자리, 깊이, 갈래)`.

    후보마다 표시 하나만 넣어 점역한다. 표시가 연산 기호 붙임(수학 제45항) 같은 빈칸 판정을 바꿔 점자가 달라지면 그 후보만
    버린다(한꺼번에 넣으면 하나가 어긋날 때 전부 잃는다). 표시 자리를 둘째 후보(기호 바로 뒤)로도 본다.
    """
    out = {}
    for depth, kind, alts in _op_marks(latex):
        for at in alts:
            got = convert_latex(latex[:at] + _MARK + latex[at:])
            k = got.find(_MARK)
            if k < 0 or got.replace(_MARK, "") != braille:
                continue
            if braille[k - 2:k] == "⠌⠷":         # 분자 앞 표시가 분자 묶음(⠷) 뒤에 서면 분수표 바로 뒤로 당긴다
                k -= 1
            if 0 < k < len(braille) and braille[k - 1] in _OP_TAIL:
                out.setdefault(k, (k, depth, kind))
            break
    return sorted(out.values())


# 후보 고르기 — 제66항은 어느 후보에서 끊을지 정하지 않는다. 접는 쪽(엔진 `wrap` · 앱)은 칸 안 가장 먼 자리를 고르므로
#   줄 수 대신 아래 두 관행을 자리 목록으로 건넨다. gold 수학 Ⅰ(009) 긴 수식 173개(줄 머리에서 시작해 그대로 찾은 것)
#   기준 접은 자리가 gold 와 같은 수식: 후보 전부 92 · 깊이 0 만 + 간격 메우기 109 · 이 둘에 관계 기호 먼저 137.
#   ① 괄호 · 분수 · 근호 안보다 밖(깊이 0). 깊이 0 자리 사이가 `_GAP` 칸보다 넓은 구간에만 얕은 깊이부터 안쪽 자리를 더한다
#      (32칸 줄에서 강제로 자르는 일이 없게, 간격 20 · 30 에서 결과가 1~2개만 다르다).
#   ② 사칙연산 · 분수표 자리 바로 앞(`_REL_PREF` 칸 안)에 등호 · 부등호 자리가 있으면 그 자리를 뺀다. gold 는 '='
#      뒤에서 끊고, 몇 칸 더 들어가는 '×' 뒤를 안 고른다(`AB = 2a + 2 =‖2 × 2 + 2`).
_GAP = 20
_REL_PREF = 4


def _op_breaks(latex: str, braille: str, base: list[int] = ()) -> list[int]:
    """`base`(빈칸 자리)에 제66항 후보를 위 관행으로 골라 더한 끊을 자리."""
    cands = _op_candidates(latex, braille)
    rels = [k for k, d, kd in cands if d == 0 and kd == "rel"]
    chosen = set(base) | {k for k, d, kd in cands
                          if d == 0 and (kd == "rel" or not any(k - _REL_PREF <= r < k for r in rels))}
    for depth in range(1, max((d for _, d, _ in cands), default=0) + 1):
        pts = sorted(chosen | {0, len(braille)})
        wide = [(a, b) for a, b in zip(pts, pts[1:]) if b - a > _GAP]
        if not wide:
            break
        chosen |= {k for k, d, _ in cands if d == depth and any(a < k < b for a, b in wide)}
    return sorted(chosen)


class FormulaBraille:
    """LLMOutput 목록 → BrailleOutput 목록 (수식)."""

    def translate(self, optimized: list[LLMOutput]) -> list[BrailleOutput]:
        # 요소별 격리: 한 수식 점역 실패가 다른 수식을 막지 않는다.
        return safe_translate(optimized, self._translate_one)

    def _translate_one(self, opt: LLMOutput) -> BrailleOutput:
        text = opt.corrected_text
        if text.startswith(BLOCKED_TEXT_PREFIXES) or text.startswith("[수식"):
            lines = [blocked_braille()]        # 자리표시는 묵자 쪽에만(#1275)
            struct_rules: list[str] = []
            breaks = [_space_breaks(ln) for ln in lines]
        else:
            lines = [convert_latex(text)]   # 논리 줄, 32칸 줄바꿈은 layout
            struct_rules = latex_rule_ids(text)
            breaks = [_op_breaks(text, lines[0], _space_breaks(lines[0]))]
        # 구조별 rule(분수·근·첨자·로그·극한 등)만 기록 — 요소 전체(line_no=-1).
        # ★ Step17(2026-08-08) — 포괄 규정 MCST-수학-1.1("숫자는 수표를 앞세워 적는다")을 뺐다.
        #   모든 수식 요소에 붙던 자명한 규정이라 정작 봐야 할 구조 판정(제곱 ⠣/⠘⠼2 원장 C-03,
        #   아래첨자 M-02)이 그 밑에 묻혔다.
        trail = [
            make_rule(rule_id, tag="math_struct")
            for rule_id in struct_rules
        ]
        return BrailleOutput(
            element_id=opt.element_id,
            braille_lines=lines,
            break_points=breaks,
            rule_trail=trail,
            corrected_text=text,   # 조판이 원문을 본다 — 수식 발문(`\text {의 값은?}`) 뒤 지문 상자(#1341)
        )
