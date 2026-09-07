"""칸수 일치율 — 주지표 CER 이 **못 재는 축**(빈칸)을 재는 보조 계기.

════════════════════════════════════════════════════════════════════════════
무엇을 재나
════════════════════════════════════════════════════════════════════════════
CER 은 빈칸을 세지 않는다. `code/AI/test/corpus_metrics.py:88-90` 의 `cells_only()`
와 `temp/fwd_baseline.py:40-44` 의 `gold_cells()`/`our_cells()` 가 U+2800(빈칸 셀)과
줄바꿈을 **지우고** 견준다. 그래서

    A∩B          → ⠠⠁⠩⠠⠃      (우리, 틀림)
    $A \\cap B$   → ⠠⠁⠀⠩⠀⠠⠃  (정답)

이 두 줄의 CER 차이가 **0.00%p** 다. 점역사 눈에는 바로 보이는데 계기에는 안 보인다.

그런데 규정은 칸수를 직접 정한다.
  · 「한국 점자 규정」 수학 편 제11항(재추출본 **3235행**) — 수식·수학적 표기 앞뒤 **두 칸**
  · 수학 편 제15항(**3485행**) — 일반연산 기호 앞뒤 **한 칸**
  · 수학 편 제60항(**4073행**, 5호 가 **4119행**·나 **4122행**) — 합집합·교집합 앞뒤 **한 칸**
  · 한글 편 제69항(**2680행**) — 단위 기호는 로마자표·종료표로 감싸고 띄어쓰기는 묵자를 따름
    ([붙임 2] **2719행** — 비로마자 단위 뒤에 한글이 오면 한 칸)

이 도구는 **정렬된 셀 사이의 빈칸 개수(gap)** 를 우리 출력과 gold 에서 각각 세어
같은지 본다. 조항별로 갈라 어느 조항을 못 지키는지 짚는다.

지표 정의
  · 잰 자리(junction) = gold 의 이웃한 두 셀이 **둘 다** 우리 출력의 이웃한 두 셀에
    정렬된 자리. 그 자리의 `gold 빈칸 수` 와 `우리 빈칸 수` 가 같으면 일치.
  · **칸수 일치율 = 일치한 자리 ÷ 잰 자리**.
  · 틀리는 꼴 ① 우리가 안 넣음(gold>0, 우리=0) ② 우리가 더 넣음(gold=0, 우리>0)
             ③ 칸 수가 다름(둘 다 >0, 값이 다름)

════════════════════════════════════════════════════════════════════════════
무엇을 못 재나 (읽는 사람이 반드시 알아야 할 한계)
════════════════════════════════════════════════════════════════════════════
1. **정렬 못 한 자리는 못 잰다.** 셀 내용이 다르면(점역 오류·추출 누락) 칸을 짝지을
   수가 없다. 그 비율을 `잴 수 없음`에 사유별로 찍는다. 이 비율이 크면 지표가 약하다.
2. **줄바꿈 자리는 못 잰다.** gold 는 32칸에서 접히고 우리 출력은 안 접힌다. 접힌
   자리의 원래 칸수는 gold 에 남아 있지 않다. 제11항 두 칸이 줄 끝에 걸리면 사라진다.
   → `잴 수 없음 · 조판(줄바꿈)` 으로 따로 센다. 조용히 빼지 않는다.
3. **줄머리 들여쓰기는 안 센다.** 각 줄의 앞뒤 빈칸은 조판이라 벗겨 낸다.
4. **제11항은 대리 지표다.** 수식 경계를 gold 점자에서 식별할 수단이 없어, `양쪽 중
   한쪽이라도 두 칸인 자리`로 대신 잡는다. 이 바구니에는 제65항 ∴·∵(4271·4276행,
   앞뒤 두 칸)과 표 열 구분 두 칸(「점자 자료 제작 지침」 §3.1.1)도 섞인다. 순수한
   제11항 수치가 아니다.
5. **제45·46항(연산·비교 기호가 한글 사이, 2028·2062행)은 안 잰다.** 등호 ⠒⠒ 같은
   점형이 한글 셀과 겹쳐 앵커로 쓰면 과검출된다. 별도 설계가 필요하다 — 안 쟀다.
6. CER 을 대체하지 않는다. **옆에 세우는 계기**다(대표 결재 2026-09-07). 과거 수치와의
   비교 가능성을 위해 CER 정의는 건드리지 않는다.

════════════════════════════════════════════════════════════════════════════
어디서 재나 — CER 과 같은 코퍼스·같은 팔
════════════════════════════════════════════════════════════════════════════
`temp/fwd_baseline.py` 와 **같은 묵자 원천·같은 gold·같은 쪽 집합**을 쓴다. 나란히
읽으려면 같은 자리에서 재야 한다.
  · 묵자 = `temp/poc/reextract/*.json` (Opus 5 재추출, 1,361쪽)
  · 점자 = `corpus/pages/braille/EBS-E26-<bid>/<vol>/<page>.brf`
  · 쪽 거르기도 fwd_baseline 과 동일 — 태그·페이지행 제거, 80자 미만 제외,
    점자 쪽에만 해설이 실린 비대칭 쪽 제외.

★ **분모는 재추출 1,361쪽이 아니라 정답본이 있는 1,180쪽이다.** 수학 II·독서·영어듣기·
  세계지리·한국사는 점자본이 없다(근거: `temp/poc/rt_kpi.py` 상단 주석 · `corpus/books.jsonl`).

백틱 규약: 코퍼스 BRF 는 `backtick="cell"`(백틱=⠈), 규정 원문은 `"space"`. 섞지 않는다.

사용:
    code/AI/venv/bin/python tools/kpi/spacing_kpi.py [코드경로] [--out 결과.json]
    code/AI/venv/bin/python tools/kpi/spacing_kpi.py --selftest

★ 사는 곳 — 정본은 `code/AI/tools/kpi/spacing_kpi.py`(저장소 안이라 PR·CI 를 탄다).
  `V2/tools/kpi/spacing_kpi.py` 는 그리로 가는 심볼릭 링크다. 옆에 있는 `kpi_v2.py` 는
  V2 루트 밖이라 git 미추적인데, 이 도구는 "PR 로 올려라"는 지시를 지키려면 저장소
  안에 있어야 해서 갈랐다. 어느 경로로 불러도 `os.path.realpath` 로 같은 자리를 본다.

════════════════════════════════════════════════════════════════════════════
변경 이력
════════════════════════════════════════════════════════════════════════════
2026-09-07  신설. 대표 결재 "CER 은 그대로 두고 칸수 지표를 옆에 세운다".
            조항 행 번호는 `braille-source/text/한국 점자 규정_재추출.txt` 에서 직접 확인.

            **develop @ d1848ce 기준선** (1,147쪽 · gold 2,450,343셀 · 잰 자리 1,762,449)
              전체 99.35% │ 제11항(대리) 74.16%(n=10,790) · 제60항 94.36%(n=532)
              제69항(단위) 43.03%(n=165) · 로마자구간 98.91%(n=9,534) · 기타 99.51%
              틀리는 꼴 ①안 넣음 1,467 · ②더 넣음 4,654 · ③칸 수 다름 5,344
              짝 못 지은 비율 28.04%(정렬 실패 25.0% + 조판 3.1%)
            ※ 제15항은 **코퍼스에 잴 자리가 0건**이다(홑 토큰 후보 2건은 눈으로 보니
              글머리표 오검출). "결함 없음"이 아니라 "이 코퍼스에 그 조건이 없음"이다.

            ※ 확인 중 발견 — `app/utils/braille_back.py:1612` 주석이 집합 연산을
              "제61항 5" 로 적었는데 재추출본 4073행 기준 **제60항 5호**다(제61항은
              4149행 명제 기호). 앱 소스는 이번 회차에서 안 고친다(계기 신설 회차).
"""
from __future__ import annotations

import collections
import difflib
import glob
import json
import os
import re
import sys

# 코드 경로는 첫 인자로 갈아 끼운다(워크트리 A/B). fwd_baseline.py 와 같은 관례.
# 이 파일은 <AI저장소>/tools/kpi/ 에 산다. V2 루트는 거기서 넷 위다.
# ⚠ 절대경로를 박지 않는다 — PJ14·ARMINUS 두 대에서 같이 돌아야 한다.
_HERE = os.path.dirname(os.path.realpath(__file__))            # <AI>/tools/kpi
AI = (sys.argv[1] if len(sys.argv) > 1 and not sys.argv[1].startswith("-")
      else os.path.abspath(os.path.join(_HERE, "..", "..")))   # <AI>
V2 = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, AI)
from app.utils.braille_ascii import unicode_to_ascii          # noqa: E402
from app.utils.braille_back import _is_operand, decode         # noqa: E402

# 유니코드 점자 셀 → Braille ASCII 문자(표준 64셀). 규정 원문이 ASCII 로 적혀 있어
# 단위 기호를 대조하려면 되돌려야 한다.
CELL_ASCII = {chr(0x2800 + i): unicode_to_ascii(chr(0x2800 + i)) for i in range(64)}

REEXTRACT = os.environ.get("SPACING_PRINT_SRC",
                          os.path.join(V2, "temp/poc/reextract/*.json"))
BRAILLE_ROOT = os.path.join(V2, "corpus/pages/braille")
SPACE = "⠀"

# 책 id → 재추출 meta 의 book 이름. `temp/poc/rt_kpi.py` 의 M 을 그대로 옮겼다.
# 여기 없는 책은 누락이 아니라 **점자 정답본이 없는 책**이다(수학 II·독서·영어듣기·한국사).
BOOKS = {
    "001": "PDF-2027 수능특강 생명과학 I", "003": "PDF-2027 수능특강 문학",
    "004": "PDF-2027 수능특강 언어와 매체", "005": "PDF-2027 수능특강 화법과 작문 원본",
    "006": "PDF-2027 수능특강 영어 ", "009": "PDF-2027 수능특강 수학 I",
    "011": "PDF-2027 수능특강 확률과 통계", "012": "PDF-2027 수능특강 동아시아사 원본",
    "013": "PDF-2027 수능 특강 사회문화", "014": "PDF-2027 수능특강 생활과 윤리 1",
    "015": "PDF-27 수능특강 세계사", "016": "PDF-2027 수능특강 세계지리",
    "017": "PDF-2027 수능특강 윤리와 사상",
}

# ── 조항 앵커 ────────────────────────────────────────────────────────────
# 점형은 규정 원문의 Braille ASCII 를 ascii_to_unicode(backtick="space") 로 옮긴 값이다.
# 「수학 점자」 제15항(3485행) 1~6호 — 앞뒤 한 칸.
#   7~9호(∙ ⠸⠲ · 네모표 ⠸⠬ · ∆ ⠸⠶)는 뺀다. 전권 실측에서 그 셋이 홑 토큰으로 서는
#   자리는 글머리표·본문이지 수식이 아니었다(braille_back.py:1636 근거 재사용).
ART15 = ("⠸⠢", "⠸⠔", "⠸⠡", "⠸⠣", "⠸⠴⠴", "⠸⠴")   # ⊕ ⊖ ⊗ ∗ ⦾ ∘  (긴 것 먼저)
# 「수학 점자」 제60항 5호(4119·4122행) — 합집합 ⠬ · 교집합 ⠩, 앞뒤 한 칸.
#   ⚠ 두 셀은 한글 약자 `요`(⠬)·`유`(⠩)와 **같은 셀**이다. 양옆이 집합 이름일 때만 본다
#     (braille_back.py:1612 의 _SET_NAME_RE 와 같은 가드). 안 걸면 본문 `요 지리적`이
#     합집합으로 잡힌다.
ART60 = ("⠬", "⠩")
SET_NAME = re.compile(r"⠠[⠁⠃⠉⠙⠑⠋⠛⠓⠊⠚⠅⠇⠍⠝⠕⠏⠟⠗⠎⠞⠥⠧⠺⠭⠽⠵]")
# 「한글 점자」 제69항(2680행) — 로마자표 ⠴ … 로마자 종료표 ⠲ 로 감싼 단위·로마자 구간.
#   규정은 고정 칸수를 정하지 않고 "띄어쓰기는 묵자를 따른다"고 한다. 그러므로 여기서
#   재는 것은 "규정이 정한 칸수를 지켰나"가 아니라 **"gold 와 같은 칸수를 냈나"** 다.
ROMAN_OPEN, ROMAN_CLOSE = "⠴", "⠲"
ROMAN_SPAN = 12          # 여는 표와 닫는 표 사이 최대 셀 수(단위 기호는 짧다)
# 제69항 예문(2684~2718행)에 나온 단위. **두 글자 이상만** 센다.
#   ⚠ 홑 글자 단위(m·g·s·h·A·V·W)는 **뺀다.** 점자에서 로마자 변수와 구별이 안 된다 —
#     2026-09-07 실측: `a` 를 암페어로 넣었더니 `⠴⠁⠲`(로마자 A) 수백 건이 단위로 잡혔다
#     (`A는`·`A이고`·`A가 2개`). 그래서 홑 글자 단위는 **안 잰다**(못 잰다).
UNITS = frozenset("cm mm km kg mg dl ml cal min in gb kb mb tb "
                  "mhz khz ghz hz kw pa mol ms".split())
# [붙임 2](2719~2751행) 비로마자 단위표 — ⠴ 뒤에 이 꼴이 붙고 종료표가 없다.
#   0p=% · 0pp=%p · 0pm=‰ · 0pt=%ile · 0d=° · 0d,c=℃ · 0d,f=℉ · 0-=′ · 0--=″ · 0*=Å
UNIT_MARK = frozenset(("p", "pp", "pm", "pt", "d", "d,c", "d,f", "-", "--", "*"))

LAB11 = "제11항(대리)"
LAB15 = "제15항"
LAB60 = "제60항"
LAB69 = "제69항(단위)"
LABROM = "로마자구간(제35·36항)"
LABETC = "기타(낱말 사이)"
ORDER = [LAB11, LAB15, LAB60, LAB69, LABROM, LABETC]


# ── 정규화 ───────────────────────────────────────────────────────────────
def cells_and_gaps(text: str) -> tuple[list[str], list[int], list[bool]]:
    """점자 문자열 → (셀 목록, 셀 앞 빈칸 수, 그 빈칸이 줄바꿈에서 온 것인가).

    줄머리·줄끝 빈칸은 조판이라 벗긴다. 줄바꿈은 빈칸 1로 잇되 `wrap` 에 표시해
    나중에 `잴 수 없음`으로 뺀다 — gold 는 32칸에서 접히고 우리 출력은 안 접힌다.
    """
    cells: list[str] = []
    gaps: list[int] = []
    wrap: list[bool] = []
    pend, pend_wrap, first = 0, False, True
    for raw in text.split("\n"):
        line = "".join(ch if "⠀" <= ch <= "⣿" else
                       (SPACE if ch == " " else "") for ch in raw).strip(SPACE)
        if not line:
            continue
        if not first:
            pend, pend_wrap = max(pend, 1), True
        first = False
        for ch in line:
            if ch == SPACE:
                pend += 1
                continue
            cells.append(ch)
            gaps.append(pend)
            wrap.append(pend_wrap)
            pend, pend_wrap = 0, False
    return cells, gaps, wrap


# ── 조항 분류 ────────────────────────────────────────────────────────────
_HANGUL = re.compile(r"[가-힣]")


def is_operand(tok: str) -> bool:
    """제15항 기호의 이웃이 피연산자인가 — braille_back 의 가드에 한글 문을 하나 더 얹는다.

    `_is_operand` 만으로는 모자란다(2026-09-07 실측). 그건 토큰을 **수식으로 읽어** 알파벳이
    남는지만 보는데, 한글 `염색체`(⠱⠢⠠⠗⠁⠰⠝)도 수식으로 읽으면 알파벳이 된다. 그래서
    글상자 뒤 글머리표 `∘`(⠸⠴)가 제15항 일반연산으로 17건 새어 들어왔다.
    한글로 정상 해독되는 **세 셀 이상** 토큰은 피연산자가 아니다. 두 셀 이하는 규정 예문
    `x⊕y`(3487행)처럼 홑 낱자 변수가 한글 셀과 겹치므로 봐준다.
    """
    if not _is_operand(tok):
        return False
    return len(tok) <= 2 or not _HANGUL.search(decode(tok))


def tokenize(cells: list[str], gaps: list[int]) -> list[tuple[int, int]]:
    """빈칸으로 갈린 토큰 목록 [(시작, 끝+1)]. 규정의 '앞뒤 한 칸'은 곧 홑 토큰이다."""
    out, s = [], 0
    for k in range(1, len(cells)):
        if gaps[k]:
            out.append((s, k))
            s = k
    out.append((s, len(cells)))
    return out


def _roman_runs(tok: str) -> list[tuple[int, int, str]]:
    """토큰 안의 로마자표 ⠴ … 종료표 ⠲ 구간 [(시작, 끝+1, 알맹이 ASCII)].

    ⚠ ⠲ 는 마침표와 **같은 셀**이고 ⠴ 도 한글에 흔하다. 여는 표와 닫는 표가
      짝을 이룰 때만 구간으로 본다 — 홑 ⠲(문장 끝)·홑 ⠴ 는 안 잡힌다.
    """
    out, i = [], 0
    while True:
        a = tok.find(ROMAN_OPEN, i)
        if a < 0:
            return out
        b = tok.find(ROMAN_CLOSE, a + 1, a + 1 + ROMAN_SPAN)
        if b < 0:
            i = a + 1
            continue
        out.append((a, b + 1, "".join(CELL_ASCII.get(c, "?") for c in tok[a + 1:b])))
        i = b + 1


def _unit_tail(tok: str, e: int) -> bool:
    """토큰이 **비로마자 단위표**(제69항 [붙임 2] 2727~2749행)로 끝나는가.

    ⠴ 뒤에 p·pp·pm·pt·d·d⠠c·d⠠f·-·--·* 가 붙고 종료표가 없는 꼴이다(%·‰·°·℃·′·″·Å).
    이 꼴만 "뒤에 한글이 나오면 한 칸 띄어 쓴다"는 고정 칸수 규정을 가진다.
    """
    a = tok.rfind(ROMAN_OPEN, 0, e)
    if a < 0 or ROMAN_CLOSE in tok[a:e]:
        return False
    return "".join(CELL_ASCII.get(c, "?") for c in tok[a + 1:e]) in UNIT_MARK


def classify_all(cells: list[str], gaps: list[int]) -> list[str]:
    """자리(k = 셀 k-1 과 k 사이)마다 조항 이름. **gold 만 보고 정한다.**

    우리 출력을 섞어 분류하면 분모가 팔마다 달라져 A/B 가 안 된다. gold 만 보면
    분모(조항별 자리 수)가 코드와 무관하게 고정된다.

    ★ 앵커는 **토큰 단위**로 건다. 규정이 "앞뒤를 한 칸씩 띄어 쓴다"고 정한 기호는
      gold 에서 **홑 토큰으로 선다.** 셀만 보고 걸면 통째로 헛detection 이 난다 —
      2026-09-07 실측: ⠬ 를 셀로 걸면 한글 `요소`(⠬⠠⠥)가 합집합으로, ⠸⠴ 를 셀로
      걸면 글상자 뒤 글머리표가 제15항 ∘ 로 잡혔다(각각 570·3,568건 전부 오검출).
    """
    cls = [LABETC] * len(cells)
    toks = tokenize(cells, gaps)
    txt = [("".join(cells[a:b])) for a, b in toks]
    for t, (a, b) in enumerate(toks):
        prv = txt[t - 1] if t else ""
        nxt = txt[t + 1] if t + 1 < len(toks) else ""
        lab = None
        if txt[t] in ART15 and prv and nxt and is_operand(prv) and is_operand(nxt):
            lab = LAB15                      # 제15항 — 양옆이 피연산자인 홑 기호만
        elif txt[t] in ART60 and SET_NAME.search(prv) and SET_NAME.search(nxt):
            lab = LAB60                      # 제60항 5호 — 양옆이 집합 이름일 때만
        if lab:
            if a:
                cls[a] = lab                 # 기호 앞 자리
            if b < len(cells):
                cls[b] = lab                 # 기호 뒤 자리
            continue
        for ra, rb, body in _roman_runs(txt[t]):
            lab69 = LAB69 if body.lower() in UNITS else LABROM
            if a + ra:                       # 구간 앞 자리
                cls[a + ra] = lab69
            if a + rb < len(cells):          # 구간 뒤 자리
                cls[a + rb] = lab69
        if b < len(cells) and _unit_tail(txt[t], b - a):
            cls[b] = LAB69                   # 비로마자 단위표 뒤 자리([붙임 2])
    for k in range(1, len(cells)):           # 제11항 대리 — 남은 두 칸 자리
        if cls[k] == LABETC and gaps[k] == 2:
            cls[k] = LAB11
    return cls


# ── 한 쪽 채점 ───────────────────────────────────────────────────────────
def score_page(ours: str, gold: str) -> dict:
    oc, og, ow = cells_and_gaps(ours)
    gc, gg, gw = cells_and_gaps(gold)
    res = {"gold_cells": len(gc), "sites": 0, "hit": 0, "over2": 0,
           "kind": collections.Counter(),
           "art": collections.defaultdict(lambda: {"all": 0, "n": 0, "hit": 0}),
           "skip": collections.Counter(), "aligned_cells": 0}
    if not gc:
        return res
    # ① gold 쪽 자리 전수 — 조항별 **분모**. 못 잰 자리도 여기 들어간다.
    cls = classify_all(gc, gg)
    for k in range(1, len(gc)):
        res["art"][cls[k]]["all"] += 1
    if not oc:
        res["skip"]["우리 출력이 빔"] += len(gc) - 1
        return res
    # ② 정렬 — CER 과 같은 자(difflib, autojunk=False)로 셀을 짝짓는다.
    sm = difflib.SequenceMatcher(None, oc, gc, autojunk=False)
    for i, j, n in sm.get_matching_blocks():
        res["aligned_cells"] += n
        for t in range(1, n):                              # 블록 안의 이웃 자리만
            k = j + t
            if gw[k] or ow[i + t]:
                res["skip"]["조판(줄바꿈)"] += 1
                continue
            gv, ov = gg[k], og[i + t]
            res["sites"] += 1
            a = res["art"][cls[k]]
            a["n"] += 1
            if gv == ov:
                res["hit"] += 1
                a["hit"] += 1
            elif ov == 0:
                res["kind"]["① 우리가 안 넣음"] += 1
            elif gv == 0:
                res["kind"]["② 우리가 더 넣음"] += 1
                res["over2"] += ov >= 2
            else:
                res["kind"]["③ 칸 수가 다름"] += 1
                res["over2"] += ov >= 2 > gv
    # gold 자리 총수 = len(gc)-1. 그중 위에서 못 다룬 것은 정렬 실패다.
    res["skip"]["정렬 실패(셀 내용 불일치)"] += max(
        len(gc) - 1 - res["sites"] - res["skip"]["조판(줄바꿈)"], 0)
    return res


# ── 쪽 모으기 (fwd_baseline.py 와 동일) ──────────────────────────────────
_PAGE_ROW = re.compile(r"^[a-z]?\d+\s.*\s\d+\s*$")
_ANS_HEAD = re.compile(r"정답\s*[:：]|정답과\s*해설|해설\s*[:：]")
# ★ 강조 태그 `<!강조>…<!/강조>` 는 **번역기가 먹는 입력**이다 — 규정 제56항 드러냄표
#   ⠠⠤ … ⠤⠄(`braille-source/text/규정_텍스트.txt:2467`). 통째로 지우면 그 점형이
#   **구조적으로 못 나온다.** 재추출 코퍼스의 태그는 강조뿐(여는 1,074·닫는 805 +
#   뒤집힌 꼴 `</!강조>` 269). 2026-09-08 실측: 태그 있는 314쪽 총편집 248,678 →
#   247,521(−1,157셀) · 우리 ⠠⠤ 1 → 1,012. 나머지 태그는 종전대로 벗긴다.
_TAG = re.compile(r"<!(?!/?강조>)/?[^>]{1,40}>")
_TAG_FLIP = ("</!강조>", "<!/강조>")


def iter_pages(ascii_to_unicode, decode):
    for rf in sorted(glob.glob(REEXTRACT)):
        d = json.load(open(rf, encoding="utf-8"))
        m = d.get("meta") or {}
        bid = next((k for k, v in BOOKS.items() if v == m.get("book")), None)
        if not bid:
            continue
        brf = f"{BRAILLE_ROOT}/EBS-E26-{bid}/{m['vol']}/{m['page']}.brf"
        if not os.path.exists(brf):
            continue
        want = "\n".join(e.get("content") or "" for e in d.get("elements") or [])
        want = _TAG.sub("", want.replace(*_TAG_FLIP))
        want = "\n".join(l for l in want.split("\n")
                         if l.strip() and not _PAGE_ROW.match(l.strip()))
        if len(want) < 80:
            continue
        raw = open(brf, encoding="utf-8", errors="ignore").read()
        gold = raw if "⠁" in raw else ascii_to_unicode(raw, backtick="cell")
        if not any("⠁" <= c <= "⣿" for c in gold):
            continue
        yield BOOKS[bid], m["page"], want, gold, decode, raw


def main(argv: list[str]) -> int:
    ai = AI
    from app.ai.braille.translator import translate_plain     # noqa: E402
    from app.utils.braille_ascii import ascii_to_unicode      # noqa: E402
    from app.utils.braille_back import decode                 # noqa: E402

    tot = {"pages": 0, "gold_cells": 0, "sites": 0, "hit": 0, "over2": 0}
    kind: collections.Counter = collections.Counter()
    skip: collections.Counter = collections.Counter()
    art: dict = collections.defaultdict(lambda: {"all": 0, "n": 0, "hit": 0})
    by_book: dict = collections.defaultdict(lambda: {"p": 0, "n": 0, "hit": 0})
    dropped = collections.Counter()
    rows = []

    for book, page, want, gold, _dec, raw in iter_pages(ascii_to_unicode, decode):
        try:
            ours = translate_plain(want)
        except Exception as exc:                              # noqa: BLE001
            dropped[f"점역 실패: {type(exc).__name__}"] += 1
            continue
        try:                                                   # 해설 비대칭 쪽 제외
            dtxt = decode(gold)
        except Exception:                                      # noqa: BLE001
            dtxt = ""
        gc_n = sum(1 for c in gold if "⠁" <= c <= "⣿")
        oc_n = sum(1 for c in ours if "⠁" <= c <= "⣿")
        if _ANS_HEAD.search(dtxt) and not _ANS_HEAD.search(want) and gc_n > oc_n * 1.3:
            dropped["점자 쪽에만 해설(비대칭)"] += 1
            continue
        r = score_page(ours, gold)
        tot["pages"] += 1
        tot["gold_cells"] += r["gold_cells"]
        tot["sites"] += r["sites"]
        tot["hit"] += r["hit"]
        tot["over2"] += r["over2"]
        kind.update(r["kind"])
        skip.update(r["skip"])
        for a, v in r["art"].items():
            art[a]["all"] += v["all"]
            art[a]["n"] += v["n"]
            art[a]["hit"] += v["hit"]
        b = by_book[book]
        b["p"] += 1
        b["n"] += r["sites"]
        b["hit"] += r["hit"]
        rows.append([book, page, r["sites"], r["hit"], r["gold_cells"]])

    if not tot["sites"]:
        print("잴 자리가 없다")
        return 1
    pc = lambda h, n: (h / n * 100) if n else float("nan")     # noqa: E731
    print(f"칸수 일치율   대상 {tot['pages']:,}쪽 / gold {tot['gold_cells']:,}셀   코드 {ai}")
    print(f"  전체        {pc(tot['hit'], tot['sites']):.2f}%   "
          f"(잰 자리 {tot['sites']:,})")
    print("  조항별            일치율   잰 자리 n / gold 자리 전체  (커버리지)")
    for a in ORDER + [k for k in art if k not in ORDER]:
        if a not in art:
            continue
        v = art[a]
        print(f"    {a:<16s} {pc(v['hit'], v['n']):6.2f}%   {v['n']:>8,} / {v['all']:>8,}"
              f"   ({pc(v['n'], v['all']):5.1f}%)")
    print("  틀리는 꼴")
    miss = tot["sites"] - tot["hit"]
    for k, v in [("① 우리가 안 넣음", kind["① 우리가 안 넣음"]),
                 ("② 우리가 더 넣음", kind["② 우리가 더 넣음"]),
                 ("③ 칸 수가 다름", kind["③ 칸 수가 다름"])]:
        print(f"    {k:<16s} {v:>8,}건  ({pc(v, miss):5.1f}% of 틀린 {miss:,})")
    print(f"    └ 그중 우리가 두 칸 이상 넣은 자리 {tot['over2']:,}건")
    print("  책별 (일치율 낮은 순)")
    for b, v in sorted(by_book.items(), key=lambda x: pc(x[1]["hit"], x[1]["n"])):
        print(f"    {b:<32s} {v['p']:>4}쪽  {pc(v['hit'], v['n']):6.2f}%  (n={v['n']:,})")
    print("  잴 수 없음")
    denom = tot["sites"] + sum(skip.values())
    for k, v in skip.most_common():
        print(f"    {k:<24s} {v:>8,}건  ({pc(v, denom):5.1f}% of gold 자리 {denom:,})")
    for k, v in dropped.most_common():
        print(f"    {k:<24s} {v:>8,}쪽  (쪽째 제외)")
    print(f"    → 짝 못 지은 비율 {pc(sum(skip.values()), denom):.2f}%")

    if "--out" in argv:
        json.dump({"total": tot, "kind": dict(kind), "skip": dict(skip),
                   "art": {k: dict(v) for k, v in art.items()},
                   "book": {k: dict(v) for k, v in by_book.items()},
                   "dropped": dict(dropped), "pages": rows},
                  open(argv[argv.index("--out") + 1], "w", encoding="utf-8"),
                  ensure_ascii=False)
    return 0


# ── 자체 점검 ────────────────────────────────────────────────────────────
def selftest() -> int:
    c, g, w = cells_and_gaps("⠠⠁⠀⠩⠀⠠⠃")
    assert c == ["⠠", "⠁", "⠩", "⠠", "⠃"], c
    assert g == [0, 0, 1, 1, 0], g
    assert not any(w)
    # 줄머리·줄끝 빈칸은 벗기고, 줄바꿈은 빈칸 1 + wrap 표시
    c, g, w = cells_and_gaps("⠀⠀⠠⠁⠀\n⠀⠠⠃")
    assert c == ["⠠", "⠁", "⠠", "⠃"] and g == [0, 0, 1, 0], (c, g)
    assert w == [False, False, True, False], w

    gold = "⠠⠁⠀⠩⠀⠠⠃"        # 제60항: 앞뒤 한 칸
    bad = "⠠⠁⠩⠠⠃"            # 우리: 안 넣음
    r = score_page(bad, gold)
    assert r["sites"] == 4 and r["hit"] == 2, r
    assert r["kind"]["① 우리가 안 넣음"] == 2, r["kind"]
    assert r["art"][LAB60] == {"all": 2, "n": 2, "hit": 0}, dict(r["art"])
    assert score_page(gold, gold)["hit"] == 4

    # 반례 ① 양옆이 집합 이름이 아니면 ⠩ 은 한글 `유` 다. 제60항으로 잡히면 안 된다.
    plain = "⠛⠥⠀⠩⠀⠛⠥"
    assert LAB60 not in score_page(plain, plain)["art"], dict(score_page(plain, plain)["art"])
    # 반례 ② 붙어 있는 ⠬ 는 한글 `요소`(⠬⠠⠥)다 — 홑 토큰이 아니면 제60항이 아니다.
    yoso = "⠝⠠⠎⠀⠬⠠⠥⠫"
    assert LAB60 not in score_page(yoso, yoso)["art"], dict(score_page(yoso, yoso)["art"])
    # 반례 ③ 글상자 테두리 뒤 글머리표 ⠸⠴ 는 제15항 ∘ 가 아니다(양옆이 피연산자 아님).
    bullet = "⠿⠿⠿⠀⠸⠴⠀⠚⠬⠑⠥"
    assert LAB15 not in score_page(bullet, bullet)["art"], dict(score_page(bullet, bullet)["art"])

    # 제15항 두 셀 앵커 ⠸⠢(⊕)
    g15 = "⠭⠀⠸⠢⠀⠽"                              # x ⊕ y — 양옆이 피연산자
    r = score_page("⠭⠸⠢⠽", g15)
    assert r["art"][LAB15] == {"all": 2, "n": 2, "hit": 0}, dict(r["art"])  # 안쪽 자리는 안 셈

    # 제11항 대리 — 두 칸 자리
    r = score_page("⠛⠀⠠⠁⠀⠛", "⠛⠀⠀⠠⠁⠀⠀⠛")
    assert r["art"][LAB11] == {"all": 2, "n": 2, "hit": 0}, dict(r["art"])
    assert r["kind"]["③ 칸 수가 다름"] == 2, r["kind"]
    # 분류는 gold 만 본다 — 우리가 없는 두 칸을 넣어도 제11항 바구니로 안 옮겨진다
    r = score_page("⠛⠀⠀⠠⠁⠀⠀⠛", "⠛⠀⠠⠁⠀⠛")
    assert LAB11 not in r["art"] and r["over2"] == 2, (dict(r["art"]), r["over2"])

    # 제69항 — 로마자표 ⠴ … 종료표 ⠲. 반례: ⠲ 만 있으면(마침표) 안 잡힌다.
    # 제69항 — 180cm = `#ahj0cm4` (규정 재추출본 2684~2685행)
    assert _roman_runs("⠼⠁⠓⠚⠴⠉⠍⠲") == [(4, 8, "cm")], _roman_runs("⠼⠁⠓⠚⠴⠉⠍⠲")
    assert _roman_runs("⠛⠥⠲") == []              # 마침표 ⠲ 홑으로는 안 잡힌다
    assert _roman_runs("⠛⠥⠴⠛⠥") == []           # 종료표 없는 ⠴ 도 안 잡힌다
    r = score_page("⠫⠀⠼⠁⠓⠚⠴⠉⠍⠲⠀⠫", "⠫⠀⠼⠁⠓⠚⠴⠉⠍⠲⠀⠫")
    assert r["art"][LAB69]["all"] == 2, dict(r["art"])          # 구간 앞·뒤 자리
    # 로마자 변수 A 는 단위가 아니다 — 다른 바구니로 가야 한다
    r = score_page("⠫⠀⠴⠠⠁⠲⠉⠵⠀⠫", "⠫⠀⠴⠠⠁⠲⠉⠵⠀⠫")
    assert LAB69 not in r["art"] and r["art"][LABROM]["all"] == 2, dict(r["art"])
    # [붙임 2] 비로마자 단위표 — 10%에 = `#aj0p`n` (규정 2757행)
    assert _unit_tail("⠼⠁⠚⠴⠏", 5)
    assert not _unit_tail("⠼⠁⠚⠴⠉⠍⠲", 7)        # 종료표가 있으면 로마자 단위다

    # 정렬 실패는 조용히 사라지지 않는다
    r = score_page("⠛⠥⠛⠥", "⠠⠁⠀⠩⠀⠠⠃⠠⠁")
    assert sum(r["skip"].values()) + r["sites"] == r["gold_cells"] - 1, (dict(r["skip"]), r)
    print("selftest ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(selftest() if "--selftest" in sys.argv else main(sys.argv))
