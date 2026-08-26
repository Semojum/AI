import base64
import binascii
import collections
import os
import re
import tempfile
from typing import Optional

import fitz

from app.schemas.layout import DocumentMeta
from app.utils.logger import get_logger

from app.ai.braille.tag_names import BOX_CHAR as TAG_BOX_CHAR

logger = get_logger(__name__)

MIN_TEXT_LENGTH = 10

# PUA(사설영역) 글자 비율이 이 값을 넘으면 텍스트레이어를 신뢰하지 않는다.
# 한컴/HWP 수식 폰트는 수식·도형 글리프를 PUA(U+E000~)로 인코딩 → PyMuPDF가 매핑 없는
# raw 코드포인트로 추출한다. 텍스트는 '있으나' 수식이 글자로 안 읽혀 ZERO로는 점역 불가 →
# STANDARD(MinerU)로 보내 OCR/수식 추출을 거치게 한다.
PUA_RATIO_THRESHOLD = 0.10

# ── 글꼴 매핑이 어긋난 PDF (2026-08-09 실측) ────────────────────────────────
# PUA 규칙이 못 잡는 **다른 유형**이다. 레거시 한국어 조판 글꼴(ST*·TK*·Mathmungjo·
# T### 등)은 윗/아래첨자·그리스문자·분수선·근호·큰괄호를 라틴-1과 한자 확장A 자리에
# 얹어 놓고, 배포기가 그 (거짓) 글리프 이름을 그대로 ToUnicode로 굳혔다. 그래서
# **PUA가 0%인데 글자가 틀린다** — 예외도 안 나고 결과만 보면 모른다.
#
# 실물 대조(렌더 확인, 코퍼스 1,131쪽):
#     STksaA-Italic  ¤ → ²    ‹ → ³    ¡ → ₁    ™ → ₂    æ → °C
#     STkyak         a → α    b → β    p → π    … → ≤    ¶ → ∞    ⁄ → (i)
#     STkboNA        ; → 분수선    ∂ → √    { → 큰중괄호   (숫자도 분수선이다)
#     TKup           ` → ¹⁴    ± → ²⁺    ™ → ₂
#     UNIDOCS 본문   䤎 → •    (한자 확장A 자리)
#     YGO11          ⇂ → □(빈칸)      Skia-Regular  Ã → ✓
# ★ **같은 코드가 글꼴마다 다른 뜻이다**(¤ = ² 또는 (ii)). 그래서 되돌리려면 글꼴마다
#   글리프를 눈으로 확인한 표가 있어야 하고, 그 표가 있어도 수식은 못 살린다 — 이 PDF들은
#   분자·분모를 따로 찍어 놔서 추출 순서가 이미 무너져 있다("2x\n1\nx¤\n2\nx+1").
#   그래서 **복구하지 않고 STANDARD(MinerU)로 보낸다** — PUA 때와 같은 처방이다.
#
# 가르는 신호: '한국 교과서 묵자에 안 나오는 코드포인트'. 폰트 이름 목록보다 낫다 —
# 이름은 책마다 바뀌지만 이 코드포인트들은 어느 책에서도 정상일 수 없다.
# 실측 오탐 0/1,251쪽: ± ™ £ ¥ ¢ § œ æ ç ß ﬂ Ã ´ ¨ 는 코퍼스 전체에서 **단 한 번도**
# 정상으로 쓰이지 않았다(전부 레거시 글꼴 출처). 반대로 ° · × ÷ 는 본문 글꼴에서
# 정상으로 나오므로 아래 집합에서 뺐다.
#
# ★ 두 갈래로 나눈다 — **처방이 다르기 때문**이다.
#   A. 조판이 통째로 무너진 쪽: 윗/아래첨자·그리스·분수선을 잃었다 → 텍스트레이어 폐기,
#      STANDARD로. 수학2 147쪽 전부와 생물 상당수가 여기.
#   B. **기호 하나만** 어긋난 쪽: 본문은 멀쩡한데 글머리 기호(●·▶)가 한자 확장A 자리로
#      떨어졌다 — `䤋compress 압축하다` · `䭅들려주는내용을…`. 여기서 STANDARD로 돌리면
#      멀쩡한 외국어 본문 76쪽을 쪽당 9초짜리 OCR에 태우면서 깨끗한 텍스트를 버린다.
#      **경고만 남긴다**(원장 등재 대상). 되돌리려면 글꼴별 글리프 대조표가 필요한데
#      글꼴마다 뜻이 달라 책마다 새로 떠야 한다 — 일반 해가 없다.
_MANGLED_LAYER_RE = re.compile(          # A. 텍스트레이어를 통째로 못 믿는다
    "["
    "\x00-\x08\x0b\x0c\x0e-\x1f"   # 매핑이 아예 없어 raw 코드가 나온 자리(T### 표 글꼴)
    "\u00a1-\u00af\u00b1-\u00b6\u00b8-\u00bf"  # 라틴-1 기호 (° U+00B0 · U+00B7 제외)
    "\u00c0-\u00d6\u00d8-\u00f6\u00f8-\u00ff"  # 라틴-1 악센트 (× U+00D7 ÷ U+00F7 제외)
    "\u0100-\u024f"                    # 라틴 확장 A/B — œ ƒ 등
    "\u02b0-\u02ff"                    # 수식 수정 문자 — ˘ ˙ ˚ ˆ
    "\u2039\u203a\u2044\u201a\u201e\u2020\u2021"  # ‹ › ⁄ ‚ „ † ‡ = 윗첨자·(i)·분수 자리
    "\ufb00-\ufb06"                    # ﬁ ﬂ 합자
    "\ue000-\uf8ff"                    # PUA (종전 규칙과 같은 구간, 여기선 개수로도 본다)
    "]"
)
_MANGLED_SYMBOL_RE = re.compile(         # B. 기호 하나만 어긋났다 — 경고만
    "["
    "\u3400-\u4dbf"                    # 한자 확장 A — 교과서 한자는 U+4E00~ 뿐이다(글머리 기호가 여기로)
    "\u21c0-\u21c3"                    # 하푼 화살표 — ⇂ = 빈칸 □ (정상인 ⇄·⇌는 뺐다)
    "]"
)
# 한 글자만 나와도 그 자리는 확실히 틀렸다(위 집합은 '정상일 수 없는' 것만 모았다).
# 비율이 아니라 개수로 보는 이유: 수학2 p004는 700자 중 ¤가 5자(0.7%)뿐인데 그 5자가
# 지수 전부다. 비율 임계(10%)로는 영원히 안 걸린다.
MANGLED_GLYPH_THRESHOLD = 1

# 라틴 문자권 원서를 함께 다루게 되면 'café'의 é가 A에 걸린다(현 코퍼스 외국어 234쪽에는
# 0건). 그때는 위 라틴-1 악센트 줄만 빼면 된다 — 나머지 신호는 그대로 쓸 수 있다.

# 유효 PDF는 항상 "%PDF-"로 시작한다(앞쪽 일부 공백/BOM 허용).
_PDF_MAGIC = b"%PDF-"

# ── ZERO 티어 어절 경계 복원 ────────────────────────────────────────────────
# 교과서 PDF 다수가 공백 글리프 없이 글자 위치(커닝)로만 어절을 띄운다 → PyMuPDF
# get_text()가 한국어를 통째로 붙여 추출("다음은가정환경…") → 점자 띄어쓰기 전멸.
# 글자 bbox 간격은 이중분포(어절 경계 ≈ +0.2×폰트크기 vs 글자 내 ≈ -0.1×폰트크기)라
# 줄별 기준 간격(중앙값) 대비 확실히 벌어진 지점에만 공백을 복원한다(rule-based).
_WORD_GAP_RATIO = 0.12   # 어절 경계 판정: 기준 간격 + max(이 비율×폰트크기, 1.0pt)
_WORD_GAP_MIN_PT = 1.0
_MIN_GAP_SAMPLES = 4     # 줄에 간격 표본이 이보다 적으면 판단 보류(원문 유지)
# 여는 따옴표·괄호 **뒤**, 닫는 따옴표·괄호 **앞**에는 공백을 넣지 않는다(QA S5).
# 이 글리프들은 글자 폭보다 자리(advance)가 넓어 간격이 늘 임계를 넘는다 —
# 실측 QA 11곳 중 5곳이 `‘ 이 민족 ’`·`‘ 전쟁 ’`처럼 안쪽에 공백이 끼어 나왔다.
# 맞춤법상으로도 여는 부호 뒤·닫는 부호 앞은 붙여 쓴다.
_NO_SPACE_AFTER = "‘“'\"([{〈《「『【<"
_NO_SPACE_BEFORE = "’”'\")]}〉》」』】>.,!?;:"

# ── 한 인쇄 줄이 여러 line으로 쪼개지는 문제 (QA S4, 2026-08-07) ─────────────
# PyMuPDF(MuPDF stext)는 가로 간격이 크면 **같은 줄이라도 line 객체를 나눈다**.
# 정답표 "01 ⑤  02 ②  03 ①  04 ⑤"는 4개 line으로 나오고, 이걸 "\n"으로 이으면
# 항목마다 줄바꿈된 점자가 나간다(대표 QA 4번). 정답 점자책은 **한 줄에 이어 적고
# 항목 사이를 두 칸 띈다** — 「점자 도서 제작 지침」 3장 3절 4)(3)①("선택지와
# 선택지 사이에는 두 칸의 빈칸을 두어 구별한다") · 같은 장 6)(1)("표의 셀과 셀
# 사이는 두 칸을 띄어 구분한다").
# 실측(dev-2027+val-2027 인쇄면 1,746쪽, 쪼개진 행 7,670개 중 정답 점자책에서
# 같은 조각열을 찾은 1,426개): 두 칸 이어 적기 1,033(72.4%) · 한 칸 241(16.9%) ·
# 줄바꿈 152(10.7%). 한 칸 쪽은 "01"+제목 같은 번호머리(114)와 빈칸 채우기
# "( "+" )"가 대부분이라 아래 두 예외로 가른다 — 시뮬레이션 정확도 1,239/1,274.
_ROW_OVERLAP = 0.5        # 같은 인쇄 줄로 볼 세로 겹침 비율
_ITEM_GAP = "  "          # 항목 사이 두 칸 (지침 3장 3절 4)(3)①)
_NUM_HEAD_RE = re.compile(r"\d{1,3}\.?")


def _row_sep(prev: str, nxt: str, num_head: bool) -> str:
    """같은 줄 조각 사이에 넣을 간격 — 기본 두 칸, 아래 두 경우만 한 칸."""
    if num_head:                                    # "01" + 제목 = 강 머리 번호
        return " "
    if prev[-1] in _NO_SPACE_AFTER or nxt[0] in _NO_SPACE_BEFORE:
        return " "                                  # 빈칸 채우기 "( " + " )이다"
    return _ITEM_GAP


def rows_to_text(items) -> str:
    """[(rect, text)] → 텍스트. 세로로 겹치는 조각은 한 줄로 잇는다(x 순서).

    rect는 `.x0/.y0/.y1`만 쓰므로 fitz.Rect든 튜플 래퍼든 상관없다.
    """
    rows: list[list] = []
    for r, t in items:
        for row in rows:
            rr = row[0][0]
            ov = min(rr.y1, r.y1) - max(rr.y0, r.y0)
            if ov > _ROW_OVERLAP * min(rr.y1 - rr.y0, r.y1 - r.y0):
                row.append((r, t))
                break
        else:
            rows.append([(r, t)])
    out: list[str] = []
    for row in rows:
        if len(row) == 1:
            out.append(row[0][1])
            continue
        row.sort(key=lambda it: it[0].x0)
        # 조각 안쪽 탭은 그대로 둔다(점역기가 한 칸으로 옮긴다) — 실측 1,551개 이은 행 중
        # 탭이 낀 것은 17개뿐이고 대부분 글머리 뒤("ㄴ.\t내용")인데, 지침 3장 3절 4)(2)는
        # 그 자리를 **한 칸**으로 규정한다. 여기서 두 칸으로 늘리면 그쪽이 틀린다.
        frags = [t.strip() for _, t in row]
        frags = [f for f in frags if f]
        if not frags:
            continue
        num_head = len(frags) == 2 and bool(_NUM_HEAD_RE.fullmatch(frags[0]))
        line = frags[0]
        for nxt in frags[1:]:
            line += _row_sep(line, nxt, num_head) + nxt
        out.append(line)
    return "\n".join(out).strip()


def _is_hangul(ch: str) -> bool:
    return "가" <= ch <= "힣" or "ㄱ" <= ch <= "ㅣ"


# ── 밑줄(드러냄표) 감지 ──────────────────────────────────────────────────────
# 한국 점자 규정 제56항: 밑줄·드러냄표로 강조된 글자체는 ⠠⠤…⠤⠄로 적는다.
# 정답 도서는 이걸 1204회 쓰는데(수능 문항 "밑줄 친 ㉠~㉤") 우리는 0회였다 — 밑줄이
# 폰트 속성이 아니라 **벡터 선**으로 그려져 있어 텍스트 추출만으로는 안 보였기 때문.
# 글자 바로 아래(0~6pt)에 깔린 얇은 가로선을 찾아 그 위 글자들을 강조로 본다.
_UL_MAX_H = 2.0          # 선 두께 상한(pt) — 이보다 두꺼우면 밑줄이 아니라 도형/음영
_UL_MIN_W = 4.0          # 너무 짧은 선(점·기호)은 제외
_UL_GAP_MAX = 6.0        # 글자 아랫변에서 선까지 허용 거리(pt)
_UL_GAP_MIN = -1.5       # 글자와 살짝 겹치는 밑줄도 허용
_UL_PAGE_W_RATIO = 0.8   # 페이지 폭의 이 비율을 넘는 선은 머리말 구분선 등 → 제외
_UL_COVER = 0.5          # 글자 폭이 선과 이만큼 겹쳐야 밑줄로 인정
_UL_OPEN, _UL_CLOSE = "<!강조>", "<!/강조>"


def _grid_rules(cands: list) -> set:
    """표 구분선인 선들. **밑줄이 아니다.**

    ★ F04(대표 지적) — 표 제목행에만 `<!강조>`가 붙는 것을 보고 "굵은 글씨라서 붙인 것
      아닌가" 하셨는데, 실물은 그것도 아니었다. **표의 가로 구분선을 밑줄로 오검출**하고
      있었다. 시연 p2 실측: 제목행 '구분'·'전통 사회'·'근대 이후의 사회'가 전부
      `_is_underlined=True`. 그 아래 3.56pt 에 폭 54/154/154 짜리 선이 있는데 그게
      표의 열 구분선이다. 본문 셀('이 매우 어려운 폐쇄적…')도 같은 이유로 물린다.

    가르는 신호는 **같은 x-분할이 여러 y 에서 되풀이되는 것**이다(= 격자).
      표 구분선   y=179.4 · 196.4 · 309.4 가 전부 [(74.6,128.4),(128.4,282.4),(282.4,436.5)]
      진짜 밑줄   언어 p034 y=598.2 은 12조각, y=583.2 는 7조각 — 분할이 매번 다르다
    선 폭이나 연속성으로는 안 갈린다(진짜 밑줄도 여러 조각이 틈 없이 이어진다).
    """
    from collections import defaultdict
    byy = defaultdict(list)
    for r in cands:
        byy[round(r.y0, 1)].append(r)
    sig_y = defaultdict(set)
    for y, segs in byy.items():
        if len(segs) < 2:                     # 한 조각짜리는 격자 판정을 안 한다
            continue
        segs = sorted(segs, key=lambda r: r.x0)
        sig = tuple((round(r.x0, 1), round(r.x1, 1)) for r in segs)
        sig_y[sig].add(y)
    out = set()
    for sig, ys in sig_y.items():
        if len(ys) >= 2:                      # 같은 분할이 두 줄 이상 = 표 격자
            for y in ys:
                out.update(id(r) for r in byy[y])
    return out


def underline_rects(page) -> list:
    """페이지의 밑줄 후보 선(표시 좌표계 Rect). 표 구분선은 뺀다(위 `_grid_rules`)."""
    rot = page.rotation_matrix
    page_w = page.rect.width
    out = []
    for g in page.get_drawings():
        r = fitz.Rect(g["rect"]) * rot
        if r.height <= _UL_MAX_H and _UL_MIN_W <= r.width <= page_w * _UL_PAGE_W_RATIO:
            out.append(r)
    grid = _grid_rules(out)
    return [r for r in out if id(r) not in grid]


def _is_underlined(cb, underlines) -> bool:
    """글자 bbox(표시 좌표)가 밑줄 위에 있는가."""
    w = cb.x1 - cb.x0
    if w <= 0:
        return False
    for u in underlines:
        gap = u.y0 - cb.y1
        if not (_UL_GAP_MIN <= gap <= _UL_GAP_MAX):
            continue
        overlap = min(cb.x1, u.x1) - max(cb.x0, u.x0)
        if overlap / w >= _UL_COVER:
            return True
    return False


def _line_text_with_word_gaps(line: dict, matrix=None, underlines=None) -> str:
    """rawdict 한 줄 → 글자 간격으로 어절 경계를 복원한 텍스트.

    공백 글리프가 실제로 있는 자리는 그대로 두고, 한글이 낀 글자쌍에서만
    '기준 간격(중앙값) + 임계'보다 벌어진 지점에 공백을 삽입한다.
    자간이 고르게 넓은 제목(트래킹)은 기준 간격 자체가 커져 오분리되지 않는다.

    matrix: 회전된 페이지의 rotation_matrix. rawdict 좌표는 회전 전 기준이라 270° 페이지에서는
    글자들이 세로로 늘어서 x 간격이 무의미해진다(어절 복원이 전멸). 표시 좌표로 옮겨서 잰다.
    """
    chars: list[tuple[str, float, float, float, bool]] = []  # (ch, x0, x1, size, underlined)
    for span in line.get("spans", []):
        size = float(span.get("size") or 0.0)
        for c in span.get("chars", []):
            bbox = c.get("bbox") or (0, 0, 0, 0)
            if matrix is not None:
                bbox = fitz.Rect(bbox) * matrix
            else:
                bbox = fitz.Rect(bbox)
            ul = bool(underlines) and _is_underlined(bbox, underlines)
            chars.append((c.get("c", ""), float(bbox[0]), float(bbox[2]), size, ul))
    if not chars:
        return ""

    # 간격 표본: 공백이 아닌 인접 글자쌍의 (다음 x0 - 이전 x1)
    gaps: list[float] = []
    for i in range(1, len(chars)):
        if chars[i - 1][0].isspace() or chars[i][0].isspace():
            continue
        gaps.append(chars[i][1] - chars[i - 1][2])
    have_base = len(gaps) >= _MIN_GAP_SAMPLES
    base = sorted(gaps)[len(gaps) // 2] if have_base else 0.0

    out: list[str] = []
    in_ul = False
    for i, (ch, x0, _x1, size, ul) in enumerate(chars):
        # 밑줄 구간 여닫이 (규정 제56항) — 공백에서 열지 않는다(마커가 어절 밖으로 새는 것 방지)
        if ul and not in_ul and not ch.isspace():
            out.append(_UL_OPEN)
            in_ul = True
        elif in_ul and not ul:
            out.append(_UL_CLOSE)
            in_ul = False
        if i and have_base:
            prev_ch, _px0, px1, _psize, _pul = chars[i - 1]
            if not ch.isspace() and not prev_ch.isspace() and (_is_hangul(ch) or _is_hangul(prev_ch)) \
                    and prev_ch not in _NO_SPACE_AFTER and ch not in _NO_SPACE_BEFORE:
                threshold = base + max(_WORD_GAP_RATIO * (size or 10.0), _WORD_GAP_MIN_PT)
                if (x0 - px1) > threshold:
                    out.insert(len(out) - 1 if (ul and not _pul) else len(out), " ")
        out.append(ch)
    if in_ul:
        out.append(_UL_CLOSE)
    return "".join(out)


def _page_text_blocks_spaced(page) -> list[dict]:
    """페이지 텍스트 블록 추출(어절 경계 복원 포함) — get_text('blocks') 대체.

    반환 요소: {"content": str, "bbox": [x0,y0,x1,y1] (PyMuPDF 포인트)}.
    """
    raw = page.get_text("rawdict")
    rot = page.rotation_matrix
    uls = underline_rects(page)
    blocks: list[dict] = []
    for b in raw.get("blocks", []):
        if b.get("type") != 0:      # 0 = 텍스트 블록
            continue
        items = [(fitz.Rect(ln.get("bbox") or (0, 0, 0, 0)) * rot,
                  _line_text_with_word_gaps(ln, rot, uls)) for ln in b.get("lines", [])]
        text = rows_to_text([(r, t) for r, t in items if t])
        if not text:
            continue
        blocks.append({"content": text, "bbox": list(b.get("bbox") or (0, 0, 0, 0))})
    return blocks


# ── 줄 단위 블록 → 문단 (QA S2, 2026-08-07) ──────────────────────────────────
# PyMuPDF의 블록 분할이 이 교재 PDF들에서는 **한 줄 = 한 블록**으로 나온다
# (실측 job_260807103532 한 쪽 43~46요소, 전부 한 줄). 그러면 문장이 중간에서 끊긴
# 조각이 요소가 되고, 조판은 그 조각마다 문단 3칸 들여쓰기를 넣는다.
#
# 이어 붙이는 신호는 **오른쪽 끝**이다. 본문 줄은 단 오른쪽까지 차고, 문단의 마지막
# 줄만 짧게 끝난다. 새 문단의 첫 줄은 들여쓰기로 시작한다.
_PAR_COL_OVERLAP = 0.6     # 같은 단으로 볼 x 겹침 비율
_PAR_FULL_RIGHT = 0.04     # 단 오른쪽에서 이 비율 안쪽까지 오면 '끝까지 찬 줄'
_PAR_GAP_MAX = 1.0         # 줄 간격이 줄높이의 이 배 이하일 때만 이음
_PAR_INDENT_MIN = 0.6      # 단 왼쪽에서 줄높이의 이 배 넘게 들어가면 새 문단 첫 줄
_PAR_RIGHT_Q = 0.95        # 단 오른쪽 끝을 잡을 분위수(max는 꼬리말 한 줄에 흔들린다)

# 이어 붙이면 안 되는 자리 두 가지(2026-08-20 실물 확인).
#   ① 뒤 조각이 **항목 표지**로 시작 — 선택지 ②와 ③, 표의 두 행을 한 덩어리로 붙였다
#      (사회문화 p0041 '② …태도' + '③ 자신의 주장과…', 언어와매체 p0107 표 두 행).
#   ② 앞 조각이 **문장부호로 끝남** — 수학은 식 번호(yy㉠)를 오른쪽 정렬해서 그 줄이
#      늘 '단 끝까지 찼다'가 되고, 끝난 문장 뒤에 다음 식을 붙였다(수학 I p0050).
# ⚠ 표지 목록을 좁게 잡는다(2026-08-20 2차 실물). 처음에 ⓐ-ⓩ·㉠-㉭까지 넣었더니
#   본문 속 기호를 문두로 오인해 한 문단을 끊었다('…여자이고,' + 'ⓑ는 남자이다').
#   실제로 새 항목을 여는 것은 선택지 번호와 보기 표지뿐이다.
_PAR_ITEM_HEAD = re.compile(
    r"^\s*(?:[①-⑳]|[⑴-⒇]|[ㄱ-ㅎ]\.|\d{1,2}\s*[.)]|[(（]\s*\d{1,2}\s*[)）])")


_HANGUL_RE = re.compile(r"[가-힣]")
_TAG_RE = re.compile(r"<!/?[^>]*>")


def _par_blocked(prev: str, nxt: str) -> bool:
    """문단으로 이으면 안 되는 자리인가.

    뒤 조각이 수식 줄이면 잇지 않는다 — 묵자가 일부러 나눈 자리라 쪼개진 게 아니다.
    문단 병합은 PyMuPDF가 한 줄씩 끊어 놓은 것을 되돌리는 일이지, 원본이 나눈 줄을
    합치는 일이 아니다(수학 I p0032·p0037에서 'BCÓ=DCÓ'가 앞 문장에 붙었다).
    """
    # 태그를 벗기고 본다 — 표 행이 <!강조>①<!/강조>로 시작하면 그냥 매칭이 못 잡는다
    # (언어와매체 p0107에서 표 머리행에 첫 행이 붙었다).
    if _PAR_ITEM_HEAD.match(_TAG_RE.sub("", nxt).lstrip()):
        return True
    # 뒤 조각에 한글이 **하나도 없으면** 수식·기호 줄이다.
    #   비율(30%)로 걸렀더니 수식이 섞인 본문까지 끊겼다('…유전자형은' + 'AAXõXºDd이다.').
    body = _TAG_RE.sub("", nxt).strip()
    return bool(body) and not _HANGUL_RE.search(body)

# 이을 때 공백을 넣을지 — 한국어 줄바꿈은 어절 경계에서도, 어절 가운데서도 일어난다.
# 실측(job_260807103532 p1): '있을까'+'하고'는 띄어야 하고('있을까 하고'),
# '거의 눈'+'물을'은 붙여야 한다('눈물을'). 눈으로도 규칙으로도 못 가른다 —
# 상위 모델이 문맥을 보고 매긴 18쌍으로 채점했을 때
#     항상 공백 9/18 · 항상 붙임 9/18 · 문장부호 규칙 9/18 · 낱말 사전 2/6
# 전부 동전 던지기였다. **형태소 분석(kiwipiepy)은 18/18**이었다(아래 _join_words).
# 부호가 확실히 가르는 자리는 분석 없이 _join_sep로 처리한다.
_PAR_OPEN = "([{‘“〈《「『【<"
_PAR_CLOSE_END = ".,!?;:”’)]}〉》」』】>"
# 그중 **닫는 부호**만 따로 든다. 이 뒤에는 조사가 그대로 붙는다(「곤여만국전도」를 ·
# 예(禮)를 · 조약(1860)이). 부호 규칙만으로 무조건 띄웠더니 `「곤여만국전도」 를`가
# 나갔다(val-2027 200쪽 19건 실측). 그래서 이 자리도 한글끼리와 똑같이 형태소로 가른다.
_PAR_CLOSE_MARK = "”’)]}〉》」』】>"


def _join_sep(a: str, b: str) -> str:
    """앞 줄 끝 `a`와 뒤 줄 앞 `b` 사이에 넣을 것 — 공백 또는 빈 문자열(부호 규칙만)."""
    if not a or not b:
        return " "
    if a[-1] in _PAR_CLOSE_END or a[-1].isdigit():
        return " "
    if b[0] in _PAR_OPEN or b[0].isdigit() or not ("가" <= b[0] <= "힣"):
        return " "
    return "" if "가" <= a[-1] <= "힣" else " "


_kiwi = None
_kiwi_tried = False


def _get_kiwi():
    """형태소 분석기(kiwipiepy) 지연 로드. 없으면 None — 부호 규칙으로 내려간다."""
    global _kiwi, _kiwi_tried
    if not _kiwi_tried:
        _kiwi_tried = True
        try:
            from kiwipiepy import Kiwi
            _kiwi = Kiwi()
        except Exception as exc:  # noqa: BLE001 — 없으면 규칙으로 동작한다
            logger.info("kiwipiepy 없음 — 줄 잇기는 문장부호 규칙으로 (%s)", exc)
    return _kiwi


def _join_words(prev_line: str, next_line: str) -> str:
    """줄 끝 어절 + 줄 첫 어절을 붙일지 띄울지 — **형태소 분석으로** 가른다.

    한국어 줄바꿈은 어절 경계에서도, 어절 가운데서도 일어난다. 실측 표본 18쌍
    (상위 모델이 문맥을 보고 매긴 정답)에서
        항상 공백 9/18 · 항상 붙임 9/18 · 문장부호 규칙 9/18 · **형태소 18/18**
    이었다. 붙인 것과 띄운 것을 각각 분석해 **로그확률이 높은 쪽**을 고른다.
        '있을까'+'하고' → 띄움('있을까 하고')   '눈'+'물을' → 붙임('눈물을')
    """
    wa = prev_line.rstrip().split()[-1] if prev_line.strip() else ""
    wb = next_line.lstrip().split()[0] if next_line.strip() else ""
    if not wa or not wb:
        return " "
    sep = _join_sep(wa[-1:], wb[:1])
    # 앞 줄이 한글로 끝났거나 **닫는 부호**로 끝났고 뒤 줄이 한글로 시작하면 형태소로 가른다.
    # 닫는 부호를 넣은 것은 2026-08-08 — 종전에는 부호 규칙이 무조건 공백을 넣어
    # `「곤여만국전도」 를`·`예(禮) 를`가 나갔다(val-2027 실측 19건, 형태소 판정 10/10).
    if not (("가" <= wa[-1] <= "힣" or wa[-1] in _PAR_CLOSE_MARK)
            and "가" <= wb[0] <= "힣"):
        return sep                      # 부호가 확실히 가르는 자리는 분석 불필요
    kiwi = _get_kiwi()
    if kiwi is None:
        return sep
    try:
        # ★ `analyze` 점수 비교는 못 쓴다 — kiwi가 띄어쓰기를 정규화해서 붙인 것과 띄운 것에
        #   **같은 점수**를 준다(실측 12쌍 중 9쌍 동점). 동점이면 종전 코드가 늘 띄움으로
        #   떨어져 `촉구 하였다`·`발표 하였다`가 나갔다(OCR 이음 2,691건 중 66건).
        #   띄어쓰기 교정기 `space()`가 같은 12쌍을 12/12 맞춘다.
        if wa[-1] in _PAR_CLOSE_MARK:
            # 닫는 부호 뒤는 space()가 절대 안 가른다(`(가)국가가`도 붙여 놓는다).
            # 그 자리는 **뒤 어절이 조사로 시작하는가**로 가른다 — 조사면 붙고
            # (「곤여만국전도」를), 아니면 띄운다((가) 국가가).
            # 어절 하나만 떼어 보면 못 읽는다(`를` → 르/NNG + ᆯ/JKO). 붙여서 분석하고
            # **부호 뒤 첫 형태소**를 본다.
            morphs = kiwi.analyze(wa + wb, top_n=1)[0][0]
            after = [m for m in morphs if m.start >= len(wa)]
            return "" if after and after[0].tag.startswith("J") else " "
        # 어절 하나만 넘기면 문맥이 없어 못 가른다(`줄`+`그`). 앞뒤 두 어절씩 붙여 준다.
        a_ctx = " ".join(prev_line.rstrip().split()[-2:])
        b_ctx = " ".join(next_line.lstrip().split()[:2])
        spaced = kiwi.space(a_ctx + b_ctx)
        if spaced:
            n = len(a_ctx.replace(" ", ""))       # 이음매의 글자 기준 위치
            seen = 0
            for ch in spaced:
                if ch == " ":
                    if seen == n:
                        return " "
                    continue
                seen += 1
                if seen > n:
                    break
            return ""
    except Exception as exc:  # noqa: BLE001 — 분석 실패는 규칙으로 격리
        logger.debug("줄 잇기 띄어쓰기 판정 실패(규칙으로): %s", exc)
    return sep


def _merge_paragraph_blocks(blocks: list[dict]) -> list[dict]:
    """줄 단위로 쪼개진 블록을 문단으로 잇는다. 원 순서를 지킨다."""
    items = [b for b in blocks if (b.get("content") or "").strip()]
    if len(items) < 2:
        return list(blocks)
    heights = sorted(b["bbox"][3] - b["bbox"][1] for b in items)
    lh = heights[len(heights) // 2] or 1.0

    def ovl(p, q) -> float:
        lo, hi = max(p[0], q[0]), min(p[2], q[2])
        return 0.0 if hi <= lo else (hi - lo) / max(1e-6, min(p[2] - p[0], q[2] - q[0]))

    out: list[dict] = []
    # ★ 이어 붙인 문단의 bbox는 합집합이라 오른쪽 끝이 가장 넓은 줄 값이 된다. 그러면
    #   '마지막 줄이 짧게 끝났다'는 신호가 지워진다. **직전 줄의** 오른쪽 끝을 따로 든다.
    last_x1: list[float] = []
    for b in items:
        bx0, by0, bx1, by1 = b["bbox"]
        if not out:
            out.append({"content": b["content"], "bbox": list(b["bbox"])})
            last_x1.append(bx1)
            continue
        a = out[-1]
        ax0, ay0, ax1, ay1 = a["bbox"]
        col = [x["bbox"] for x in items if ovl(x["bbox"], b["bbox"]) >= _PAR_COL_OVERLAP] or [b["bbox"]]
        col_left = min(c[0] for c in col)
        # ★ 단의 오른쪽 끝은 **max가 아니라 분위수**다(2026-08-20). 꼬리말 한 줄이 단을
        #   부풀려 그 단의 본문이 통째로 과분절됐다 — 사회문화 p0008 좌측 문단은 줄이
        #   x 132에서 끝나는데 꼬리말 '8  2027학년도 EBS 수능특강 사회·문화'가 160까지
        #   가서 col_right가 160이 됐고, 네 줄 전부 '단 끝까지 안 찼다'로 탈락했다.
        #   꼬리말은 왼쪽 정렬도 폭도 본문과 비슷해 겹침 기준으로는 안 걸러진다.
        #   ⚠ 90분위 이하로 내리면 짧게 끝난 문단 마지막 줄까지 '끝까지 찼다'가 되어
        #     다른 문단을 붙인다(실측 p0008에서 80분위는 요소가 하나 더 준다).
        xs = sorted(c[2] for c in col)
        col_right = xs[-1] if len(xs) < 4 else xs[min(int(len(xs) * _PAR_RIGHT_Q), len(xs) - 1)]
        width = max(1.0, col_right - col_left)
        joinable = (
            not _par_blocked(a["content"], b["content"])
            and ovl(a["bbox"], b["bbox"]) >= _PAR_COL_OVERLAP
            and -0.3 * lh <= by0 - ay1 <= _PAR_GAP_MAX * lh
            and last_x1[-1] >= col_right - _PAR_FULL_RIGHT * width  # 직전 줄이 단 끝까지 참
            and bx0 - col_left <= _PAR_INDENT_MIN * lh              # 뒤 줄이 들여쓰기로 시작 안 함
        )
        if joinable:
            av, bv = a["content"].rstrip(), b["content"].lstrip()
            a["content"] = f"{av}{_join_words(av, bv)}{bv}"
            a["bbox"] = [min(ax0, bx0), min(ay0, by0), max(ax1, bx1), max(ay1, by1)]
            last_x1[-1] = bx1
        else:
            out.append({"content": b["content"], "bbox": list(b["bbox"])})
            last_x1.append(bx1)
    return out


def extract_text_blocks(pdf_data: bytes, page_no: int) -> tuple[list[dict], int, int]:
    """텍스트레이어(ZERO) 추출 — PyMuPDF 블록 단위로 (content, bbox)를 뽑는다.

    반환: (blocks, page_width, page_height). 좌표계 = MinerU와 동일하게 2x 렌더 픽셀
    (PyMuPDF 포인트 × 2). page_width/height도 2x. BE/FE가 bbox/크기 비율로 매핑.
    """
    data = _coerce_pdf_bytes(pdf_data)
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(data)
            tmp_path = f.name
        doc = fitz.open(tmp_path)
        try:
            page_idx = max(0, min(page_no - 1, doc.page_count - 1))
            page = doc[page_idx]
            w, h = page.rect.width, page.rect.height
            # ★ 회전 지면 보정(2026-08-20). PyMuPDF의 텍스트 블록 좌표는 **회전 전**
            #   좌표계(mediabox)로 나오는데 page.rect는 회전 후 크기다. 그대로 쓰면
            #   270° 쪽에서 x가 쪽 폭을 넘고 종횡비가 뒤집힌다 — 영문 한 줄이 13x442로
            #   세로로 길게 잡혔다(외국어 코퍼스 실측, 응답 '쪽 밖' 169건 전량이 이 얼굴).
            #   rotation_matrix를 곱하면 표시 좌표가 된다(실측 21/21 전부 정상 범위).
            rot = page.rotation_matrix if page.rotation else None
            blocks: list[dict] = []
            for b in _merge_paragraph_blocks(_page_text_blocks_spaced(page)):
                x0, y0, x1, y1 = b["bbox"]
                if rot is not None:
                    r = fitz.Rect(x0, y0, x1, y1) * rot
                    r.normalize()
                    x0, y0, x1, y1 = r.x0, r.y0, r.x1, r.y1
                blocks.append({
                    "content": b["content"],
                    "bbox": [round(x0 * 2), round(y0 * 2), round(x1 * 2), round(y1 * 2)],
                })
        finally:
            doc.close()
    finally:
        if tmp_path:
            os.unlink(tmp_path)
    return blocks, int(round(w * 2)), int(round(h * 2))


# ── 글상자 테두리(BBPG-1.2.5 · 원장 C-01b) ─────────────────────────────────
# 지문·보기·설명 박스는 묵자에서 **벡터 사각형**으로 그려져 있어 텍스트 추출만으로는
# 안 보인다(밑줄과 같은 사정). 정답 도서는 이걸 dev-2027 900쪽에서 1,783번 쓰는데
# 우리는 0번이었다 — gold 셀의 5.2%가 테두리 줄이다.
#
# 가르는 조건 두 개(실측 사회문화 p8·p23):
#   · **글자를 감싸야** 한다 — 제목 배너·머리말 띠는 안에 글이 없다(감싸는 게 아니라 덮는다).
#   · 선(stroke)이 있어야 한다 — 채움만 있는 도형은 강조 음영이지 테두리가 아니다.
#     ※ 규정(1장5 1))은 음영 글상자도 글상자라 하지만, 실측하면 **점수가 내려간다**
#       (2026-08-09 A/B: dev −0.0p·val −0.3p, 새로 만든 상자의 76%가 정답에 없는 상자).
#       규정↔실측이 갈리는 자리라 원장에 올릴 항목이다.
_BOX_MIN_W = 0.20        # 페이지 폭 대비 최소 너비 — 이보다 좁으면 아이콘·라벨
_BOX_MIN_H = 18.0        # 최소 높이(pt) — 밑줄·구분선 제외
_BOX_MAX_AREA = 0.85     # 페이지 면적의 이 비율을 넘으면 페이지 테두리·배경
_BOX_X_TOL = 2.0         # 좌우가 이만큼 안에서 같으면 같은 상자의 위·아래 조각(pt)
# 곁단(사이드바) 상자 — 좁지만 길다. 폭 하한 하나로만 재면 통째로 떨어진다(F06 ⓐ 실측:
# 사회문화 p194 "우리나라의 다문화 교육 정책" 곁단이 84.5pt/595pt = 0.142로 0.20에 걸려
# 미검출). 아이콘·라벨은 가로세로가 **둘 다** 작으므로 높이로 가른다.
_BOX_SIDE_MIN_W = 0.12   # 아래 높이 조건을 만족할 때의 폭 하한
_BOX_SIDE_MIN_H = 60.0   # 이보다 높으면 '좁고 긴 상자'로 본다(pt)
# 판면 밖으로 흘러나가는 도형은 **도련 장식**이다 — 글상자는 판면 안에 그려진다.
# (F06 ⓑ 실측: p194 머리띠 배너가 x −166.9~386.4로 판면을 넘나드는 곡선 리본 22겹인데,
#  클리핑만 하고 받아들이면 제목 "자료 탐구"를 감싼 빈 글상자가 두 겹으로 붙는다.)
_BOX_IN_PAGE = 0.9       # 원래 넓이의 이 비율은 판면 안이어야 한다
# 부모 넓이의 이 비율을 넘게 채우는 안쪽 사각형은 **중첩이 아니라 같은 상자를 두 겹으로
# 그린 것**이다(기기 베젤+화면, 그림자, 채움+선 두 경로). 종전 0.98은 너무 빡빡해 그 겹이
# 위계를 한 단 올렸다. 실측 dev-2027 900쪽 자식 사각형 206개의 부모 대비 넓이비는
# 뚜렷한 쌍봉이다 — 0.9~1.0에 29개(두 겹) · 0.0~0.4에 156개(진짜 중첩) · 0.7~0.9에 5개뿐.
_BOX_SAME_AREA = 0.85


def page_is_blank(pdf_data: bytes, page_no: int) -> bool:
    """그 지면이 **정말 비었는가** — 글자도 그림도 획도 없는가 (T702).

    추출이 요소를 0개 냈을 때 그것이 **실패**인지 **빈 지면**인지 가른다. 빈 지면을 실패로
    올리면 앱이 "서버에서 변환이 차단된 페이지입니다"를 띄운다(노션 Review 3c243813…b40c).
    빈 지면을 끼워 넣는 것은 점역 조판에서 정상 동작이다.
    """
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(_coerce_pdf_bytes(pdf_data))
            tmp_path = f.name
        doc = fitz.open(tmp_path)
        try:
            page = doc[max(0, min(page_no - 1, doc.page_count - 1))]
            if page.get_text("text").strip():
                return False
            if page.get_images(full=True):
                return False
            return not page.get_drawings()
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001 — 못 읽으면 '비었다'고 단정하지 않는다
        logger.warning("빈 지면 판정 실패(비지 않은 것으로 본다): %s", exc)
        return False
    finally:
        if tmp_path:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass


def _disp(bbox, rot) -> "fitz.Rect":
    """회전 전(mediabox) 좌표 → 표시 좌표 Rect. 회전 없으면 그대로다."""
    r = fitz.Rect(bbox) * rot
    r.normalize()
    return r


# 획이 테두리에서 이만큼 안쪽으로 들어가면 사각형이 아니다(둥근 모서리 여유 포함)
_BOX_HUG_TOL = 0.12      # 짧은 변 대비
_BOX_HUG_MIN = 2.0       # 최소 허용폭(pt)


def _hugs_border(g, r, rot) -> bool:
    """그 도형이 **사각형 테두리**인가 — 모든 획이 bbox 변에 붙어 있는가.

    종전에는 도형의 bbox만 보고 글상자로 삼았다. 그러면 **속을 가로지르는 그림**이
    전부 상자가 된다 — 실측 EBS-E26-009 p0007의 삼각형 ABC 도형(98×65pt)이 꼭짓점
    라벨을 품은 '글상자'로 잡혔다. 테두리는 변만 그리고 속은 비운다는 것이 가르는 신호다.
    둥근 모서리 상자는 모서리 곡선이 변 근처라 그대로 통과한다.

    ★ 재는 것은 **직선 토막의 가운데**다. 꼭짓점만 보면 삼각형을 못 거른다 — 꼭짓점은
      어떤 도형이든 제 bbox 변에 닿기 때문이다. 빗변의 가운데는 속을 지난다.
      곡선(둥근 모서리)·`re`는 재지 않는다. 모서리 곡선을 속으로 오인하면 진짜 상자가 떨어진다.
    """
    tol = max(_BOX_HUG_MIN, min(r.width, r.height) * _BOX_HUG_TOL)
    for it in g["items"]:
        if it[0] != "l":
            continue
        p1, p2 = fitz.Point(it[1]) * rot, fitz.Point(it[2]) * rot
        x, y = (p1.x + p2.x) / 2, (p1.y + p2.y) / 2
        if (min(abs(x - r.x0), abs(x - r.x1)) > tol
                and min(abs(y - r.y0), abs(y - r.y1)) > tol):
            return False
    return True


def box_rects(page) -> list:
    """페이지의 글상자 후보 사각형(표시 좌표 Rect). 겹치는 후보는 큰 것 하나로 묶는다."""
    pr = page.rect
    W = pr.width
    # ★ 회전 지면 보정(#228 후속, 2026-08-24). get_drawings·rawdict는 **회전 전**(mediabox)
    #   좌표로 나오는데 page.rect는 회전 후 크기다. 그대로 쓰면 270° 지면에서 사각형이
    #   엉뚱한 자리로 정규화된다(실측: 180°에서 쪽 높이의 0.18 어긋남, 90°는 딴 자리).
    #   경계 요소 bbox는 이미 표시 좌표라(extract_text_blocks) 여기도 맞춰야 짝이 된다.
    rot = page.rotation_matrix
    try:
        tblocks = [_disp(b["bbox"], rot) for b in page.get_text("rawdict")["blocks"]
                   if b.get("type") == 0]
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001 — 손상 페이지는 테두리 없이 진행
        return []
    out: list = []
    for g in drawings:
        raw = _disp(g["rect"], rot)
        if not raw.intersects(pr):
            continue
        r = raw & pr
        # 판면 밖으로 크게 흘러나갔으면 도련 장식이다(위 _BOX_IN_PAGE 주석).
        if raw.get_area() > 0 and r.get_area() < raw.get_area() * _BOX_IN_PAGE:
            continue
        if r.height < _BOX_MIN_H:
            continue
        min_w = _BOX_SIDE_MIN_W if r.height >= _BOX_SIDE_MIN_H else _BOX_MIN_W
        if r.width < W * min_w:
            continue
        if r.get_area() > pr.get_area() * _BOX_MAX_AREA:
            continue
        if "s" not in g["type"]:              # 채움 전용 = 음영·배너(위 주석 참조)
            continue
        # 선색이 채움색과 같으면 **보이는 테두리가 없다** — 채움 전용과 다를 바 없는
        # 음영·마스크다(p194 배너의 흰 리본: fill=(1,1,1) color=(1,1,1)).
        if "f" in g["type"] and g.get("color") is not None and g.get("color") == g.get("fill"):
            continue
        if not _hugs_border(g, r, rot):       # 속을 가로지르는 획 = 그림이지 테두리가 아니다
            continue
        if not any(t in r for t in tblocks):  # 감싼 글이 없다
            continue
        out.append(r)
    # 겹치는 후보는 하나로 — 다만 **안에 든 것은 남긴다**. gold는 상자를 중첩하고
    # (자료 박스 안 표), 그 안쪽에 2단계 테두리를 쓴다(dev-2027 343개 중 81%가 1단계 안).
    # 종전 규칙은 안쪽 사각형을 겹침으로 보고 통째로 버렸다.
    merged: list = []
    for r in sorted(out, key=lambda r: -r.get_area()):
        # ★ 한 글상자를 **머리띠 + 본문** 두 사각형으로 그린 것을 먼저 합친다 —
        #   좌우가 같고 세로로 겹치면 같은 상자다. 안 합치면 위 조각이 제목 요소를
        #   먼저 claim해 gold의 상자 하나가 둘로 쪼개진다(실측 생명과학 p72·p152).
        #   2026-08-09 A/B: 이 병합 하나가 dev +0.28p·val +0.68p(CER)로 이번 라운드 최대 레버.
        hit = next((k for k, m in enumerate(merged)
                    if abs(r.x0 - m.x0) <= _BOX_X_TOL and abs(r.x1 - m.x1) <= _BOX_X_TOL
                    and r.y0 < m.y1 and m.y0 < r.y1), None)
        if hit is not None:
            merged[hit] = r | merged[hit]
            continue
        # 완전히 안에 들었다 = 중첩, 남긴다. 단 **거의 같은 크기**는 중첩이 아니라
        # 같은 테두리를 채움·선 두 경로로 그린 것이다 — 남기면 같은 상자를 두 번 감싼다.
        if any(r in m and r.get_area() < m.get_area() * _BOX_SAME_AREA for m in merged):
            merged.append(r)
            continue
        if any((r & m).get_area() > r.get_area() * 0.7 for m in merged):
            continue                                     # 어중간하게 겹친다 = 같은 상자
        merged.append(r)
    return merged


# ── 정오 표시 ○·× (원장 M-04·C-14) ─────────────────────────────────────────
# 해설은 선지마다 맞음/틀림을 ○·×로 찍는데, **텍스트레이어에도 MinerU 추출에도 안 나온다** —
# 글리프가 **채움 경로**로 그려져 있어서다(밑줄·글상자와 같은 사정).
# 정답 도서는 이걸 로마자 소괄호로 적는다: (O)=⠦⠄⠴⠠⠕⠠⠴ · (X)=⠦⠄⠴⠠⠭⠠⠴.
# dev-2027 900쪽에 1,058회(≈6,300셀)인데 우리는 0회였다.
#
# 가르는 신호(실측 5쪽에서 O 54/54 · X 34/34 완전일치):
#   · 채움 전용(type 'f')·선색 없음 — 획으로 그린 도형은 표·테두리다
#   · 곡선만(c) 20~60항목 = ○ · 곡선+선(cl) 40~120항목 = ×
#   · 페이지 **안**에 있어야 한다 — 판면 밖 장식이 같은 모양으로 잡힌다
#   · ○이 하나도 없는 쪽의 ×는 **곱셈 기호**다(정오 표기는 쌍으로 온다)
# 표시가 붙는 자리 — 선지 번호로 시작하는 요소만(⌧는 번호 위에 겹쳐 찍힌다)
_CHOICE_HEAD_RE = re.compile(r"^\s*(?:[①-⑳]|[㉠-㉻]|[ㄱ-ㅎ]\s*[.)]|\d{1,2}\s*[.)])")
_MARK_MIN, _MARK_MAX = 4.0, 14.0      # 글리프 한 자 크기(pt)
_MARK_SQUARE = 3.0                    # 가로세로 차이 상한 — 정사각이어야 글자다


def mark_glyphs(page) -> list[tuple[str, "fitz.Rect"]]:
    """페이지의 정오 표시 글리프 [(O|X, 사각형)]. 없으면 빈 목록.

    ★ ○이 하나도 없는 쪽의 ×는 **곱셈 기호**다 — 정오 표기는 쌍으로 온다.
      이 가드가 없으면 수학1에서 곱셈 ×를 정오 표시로 오검출한다(실측 2쪽).
    """
    pr = page.rect
    rot = page.rotation_matrix          # 회전 지면 보정 — box_rects의 _disp 주석 참조
    out: list[tuple[str, fitz.Rect]] = []
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001
        return []
    for g in drawings:
        r = _disp(g["rect"], rot)
        if r not in pr or g["type"] != "f" or g.get("color"):
            continue
        if not (_MARK_MIN <= r.width <= _MARK_MAX and _MARK_MIN <= r.height <= _MARK_MAX
                and abs(r.width - r.height) <= _MARK_SQUARE):
            continue
        kinds = {it[0] for it in g.get("items", [])}
        n = len(g.get("items", []))
        if kinds == {"c"} and 20 <= n <= 60:
            out.append(("O", r))
        elif kinds == {"c", "l"} and 40 <= n <= 120:
            out.append(("X", r))
    if not any(m == "O" for m, _ in out):
        return []                      # ○ 없는 쪽의 ×는 곱셈이다
    return out


def mark_glyphs_norm(pdf_data: bytes, page_no: int) -> list[tuple[str, list[float]]]:
    """정오 표시를 0~1000 정규화 좌표로. 실패하면 빈 목록(본문은 나가야 한다)."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(_coerce_pdf_bytes(pdf_data))
            tmp_path = f.name
        doc = fitz.open(tmp_path)
        try:
            page = doc[max(0, min(page_no - 1, doc.page_count - 1))]
            w, h = page.rect.width or 1, page.rect.height or 1
            return [(k, [r.x0 / w * 1000, r.y0 / h * 1000, r.x1 / w * 1000, r.y1 / h * 1000])
                    for k, r in mark_glyphs(page)]
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("정오 표시 검출 실패(없이 진행): %s", exc)
        return []
    finally:
        if tmp_path:
            os.unlink(tmp_path)


def tag_answer_marks(elements: list[dict], marks: list) -> int:
    """정오 표시를 **바로 뒤 요소** 앞에 글자로 붙인다(in-place). 붙인 개수 반환.

    ★ 표시는 **선지 번호 위에 겹쳐** 찍힌다(⌧ = ① 위의 ×). 그래서 표시를 품은 요소를 찾아
    그 **앞**에 붙인다 — gold 배치가 `…해당한다.(X)①아메바가…`라 번호보다 앞이다.
    선지로 시작하는 요소에만 붙인다(엉뚱한 본문에 붙지 않게).
    """
    if not marks or not elements:
        return 0
    n = 0
    for kind, (mx0, my0, mx1, my1) in marks:
        cx, cy = (mx0 + mx1) / 2, (my0 + my1) / 2
        best, best_d = None, None
        for el in elements:
            bb = el.get("bbox")
            if not bb or len(bb) != 4 or el.get("type") not in ("text", "list_item"):
                continue
            if not (bb[0] - 6 <= cx <= bb[2] and bb[1] - 6 <= cy <= bb[3] + 6):
                continue                                  # 표시를 품은(또는 줄머리에 붙은) 요소
            if not _CHOICE_HEAD_RE.match(el.get("content") or ""):
                continue                                  # 선지로 시작하는 것만
            d = abs(bb[1] - my0)
            if best is None or d < best_d:
                best, best_d = el, d
        if best is not None:
            best["content"] = f"({kind}){best['content']}"
            n += 1
    return n


# ── 네모 문자(규정 제64항 · 원장 C-16-2) ─────────────────────────────────────
# 규정 제64항: "…네모 문자는 `⠸⠦ ⠴⠇`으로 묶어 나타낸다." 규정 예시 넷이 전부 한 글자다.
#
# ★ 왜 검출이 필요한가 — **그 네모는 글자가 아니라 그림이다.** 지문 빈칸 "전쟁 중에
#   ▯(가)▯ 이/가 남긴"의 네모는 벡터 드로잉이라 텍스트 추출에 안 잡히고, 추출물에는
#   `(가)`만 남아 문두 지시 `(가)`와 구분이 사라진다. 쪽 맞춘 전수 대조에서 우리 414 대
#   gold 867(−453)이었고 미달의 대부분이 이 자리다(원장 C-16-2).
#
# 문턱은 실측으로 정했다(gold 쪽 단위 개수 대조, 2026-08-23):
#   · 사각형 W<60·H<20pt — 이보다 크면 표 칸·도형 노드다. 실측 `EBS-E26-014` 오검출이
#     64×38(표 칸)·83×29였고, 문턱을 120×40에서 60×20으로 좁히니 015 정확일치 94→98%,
#     012 92→94%, 014 87→88%로 셋 다 올랐다.
#   · 토큰은 `(가)` 꼴과 한글 낱글자만. 숫자·로마자·원문자까지 넓히면 015가 94→83%로
#     무너진다(표 안 낱자·수식 변수를 줍는다).
#   · 획 사각형(`type`에 `s`)만 본다. 채움 배지는 두 갈래가 섞여 있다 — `EBS-E26-009`
#     절 번호 배지(11×11 채움)는 gold가 적지만, `EBS-E26-014` 답지 제목 `정`·`답` 배지는
#     **장식이라 gold가 안 적는다**(원장 C-16-3). 가르는 기준이 아직 없어 이번 판은 뺐다.
_CHAR_BOX_MAX_W = 60.0
_CHAR_BOX_MAX_H = 20.0
_CHAR_BOX_TOKEN_RE = re.compile(r"\([가-힣A-Za-z0-9]\)|[가-힣]")


def char_box_glyphs(page) -> list[tuple[str, list]]:
    """네모 문자 후보 `(토큰, 표시좌표 Rect)`. 실패하면 빈 목록."""
    rot = page.rotation_matrix          # 회전 지면 보정 — box_rects의 _disp 주석 참조
    try:
        rects = [d for d in (_disp(g["rect"], rot) for g in page.get_drawings()
                             if "s" in g["type"])
                 if d.width < _CHAR_BOX_MAX_W and d.height < _CHAR_BOX_MAX_H]
        words = page.get_text("words")
    except Exception:  # noqa: BLE001 — 손상 페이지는 네모 문자 없이 진행
        return []
    out: list[tuple[str, list]] = []
    for w in words:
        token = w[4]
        if not _CHAR_BOX_TOKEN_RE.fullmatch(token):
            continue
        r = _disp(w[:4], rot)
        if any(box.contains(r) for box in rects):
            out.append((token, r))
    return out


def char_box_glyphs_norm(pdf_data: bytes, page_no: int) -> list[tuple[str, list[float]]]:
    """네모 문자 후보를 0~1000 정규화 좌표로. 실패하면 빈 목록(본문은 나가야 한다)."""
    tmp_path = None
    try:
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(_coerce_pdf_bytes(pdf_data))
            tmp_path = f.name
        doc = fitz.open(tmp_path)
        try:
            page = doc[max(0, min(page_no - 1, doc.page_count - 1))]
            w, h = page.rect.width or 1, page.rect.height or 1
            return [(t, [r.x0 / w * 1000, r.y0 / h * 1000, r.x1 / w * 1000, r.y1 / h * 1000])
                    for t, r in char_box_glyphs(page)]
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("네모 문자 검출 실패(없이 진행): %s", exc)
        return []
    finally:
        if tmp_path:
            os.unlink(tmp_path)


def tag_char_boxes(elements: list[dict], boxes: list) -> int:
    """네모 문자를 품은 토큰을 `<!네모글>…<!/네모글>`로 감싼다(in-place). 감싼 개수 반환.

    같은 토큰이 한 요소에 여러 번 나오면 **앞에서부터 하나씩** 감싼다 — 한 요소 안
    `(가)`가 지시문과 빈칸 두 자리에 나오는 쪽이 흔한데, 감싸는 자리는 상자가 있는 수만큼이다.
    (자리까지 맞추려면 글자별 좌표가 필요한데 추출물에는 요소 bbox밖에 없다. 개수는 맞는다.)
    """
    if not boxes or not elements:
        return 0
    open_tag, close_tag = f"<!{TAG_BOX_CHAR}>", f"<!/{TAG_BOX_CHAR}>"
    n = 0
    cursor: dict[int, int] = {}
    for token, (bx0, by0, bx1, by1) in boxes:
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2
        target = None
        for el in elements:
            bb = el.get("bbox")
            if not bb or len(bb) != 4 or el.get("type") not in ("text", "list_item", "title"):
                continue
            if not (bb[0] <= cx <= bb[2] and bb[1] <= cy <= bb[3]):
                continue
            if token not in (el.get("content") or ""):
                continue
            target = el
            break
        if target is None:
            continue
        key = id(target)
        start = cursor.get(key, 0)
        pos = (target["content"] or "").find(token, start)
        if pos < 0:
            pos = (target["content"] or "").find(token)
            if pos < 0:
                continue
        content = target["content"]
        target["content"] = (content[:pos] + open_tag + token + close_tag
                             + content[pos + len(token):])
        cursor[key] = pos + len(open_tag) + len(token) + len(close_tag)
        n += 1
    return n


def box_rects_norm(pdf_data: bytes, page_no: int) -> list[list[float]]:
    """글상자 후보를 **0~1000 정규화** 좌표로 돌려준다.

    ⚠ 경계 파일의 `bbox`는 경로마다 좌표계가 다르다(`result_builder` 2026-07-19 주석):
      · MinerU 경로 = **0~1000 정규화**
      · ZERO 경로   = **2x 렌더 픽셀**
    그래서 여기서는 한쪽으로 통일해 내보내고, 픽셀 경로는 부르는 쪽이 되돌린다.
    (섞으면 사각형이 엉뚱한 요소를 감싼다 — 실측 사회문화 p80에서 지문 상자가 선택지를 감쌌다.)
    """
    tmp_path = None
    try:
        # ★ _coerce_pdf_bytes도 try 안이다 — 빈 bytes면 InvalidPDFError를 던지는데,
        #   테두리는 있으면 좋은 것이라 그 예외로 페이지를 죽이면 안 된다.
        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
            f.write(_coerce_pdf_bytes(pdf_data))
            tmp_path = f.name
        doc = fitz.open(tmp_path)
        try:
            page = doc[max(0, min(page_no - 1, doc.page_count - 1))]
            w, h = page.rect.width or 1, page.rect.height or 1
            return [[r.x0 / w * 1000, r.y0 / h * 1000, r.x1 / w * 1000, r.y1 / h * 1000]
                    for r in box_rects(page)]
        finally:
            doc.close()
    except Exception as exc:  # noqa: BLE001 — 테두리는 있으면 좋은 것, 없어도 본문은 나가야 한다
        logger.warning("글상자 사각형 검출 실패(테두리 없이 진행): %s", exc)
        return []
    finally:
        if tmp_path:
            os.unlink(tmp_path)


def _center_in(bb, rect) -> bool:
    """요소 중심이 사각형 안인가. 테두리에 닿은 글이 몇 px 삐져나오므로 완전포함은 안 쓴다."""
    return (rect[0] <= (bb[0] + bb[2]) / 2 <= rect[2]
            and rect[1] <= (bb[1] + bb[3]) / 2 <= rect[3])


def regroup_boxed(elements: list[dict], rects: list) -> int:
    """사각형이 감싼 요소가 읽기순서에서 끊겨 있으면 **끼어든 요소를 상자 뒤로 뺀다**(in-place).
    옮긴 상자 수 반환.

    4분류: ③ AI 오류 — 추출기(MinerU) 읽기순서가 다단 지면에서 상자를 가로지른다.
    실측 `EBS-E26-001/0137`: 탐구자료 상자(`[107,78,733,923]`) 안 요소가 `1~16`과 `25~27`로
    끊기고 그 사이 `17~24`는 오른쪽 단의 다른 상자(개념 체크, x766~924)다. 그래서
    `tag_boxed_elements`의 연속성 가드가 상자를 통째로 건너뛰었고, 바깥 상자가 없으니 안의
    표 셋이 전부 깊이 0으로 1단계 테두리를 달았다. **정답은 그 표들을 2단계로 적는다**
    (도서지침 예3-59: 1단계 지문 글상자 안의 표가 2단계). 실측 10쪽에서 gold 2단계 10줄 :
    우리 0줄.

    **사각형이 진실이다.** 묵자에 그려진 테두리는 추출기 순서보다 확실한 묶음 근거다.
    다만 함부로 옮기면 본문이 뒤섞이므로 두 가지를 다 만족할 때만 옮긴다:
      · 끼어든 요소가 **하나도 빠짐없이** 그 사각형 밖일 것(하나라도 안이면 판단 불가)
      · 옮겨서 상자가 실제로 연속이 될 것
    옮긴 뒤 `order`를 다시 매긴다 — 소비자(`pipeline._parse_txt_result`)가 그 값을 읽는다.
    """
    if not rects or not elements:
        return 0
    moved = 0
    for rect in sorted(rects, key=lambda r: -((r[2] - r[0]) * (r[3] - r[1]))):
        idx = [i for i, el in enumerate(elements)
               if el.get("bbox") and len(el["bbox"]) == 4 and _center_in(el["bbox"], rect)]
        if len(idx) < 2:
            continue
        span = range(idx[0], idx[-1] + 1)
        outs = [i for i in span if i not in set(idx)]
        if not outs:
            continue                                   # 이미 연속
        if any(_center_in(elements[i].get("bbox") or [0, 0, 0, 0], rect) for i in outs):
            continue                                   # 있을 수 없지만 방어
        keep = [elements[i] for i in span if i in set(idx)]
        tail = [elements[i] for i in outs]
        elements[idx[0]:idx[-1] + 1] = keep + tail
        moved += 1
    if moved:
        for k, el in enumerate(elements, start=1):
            if "order" in el:
                el["order"] = k
    return moved


def tag_boxed_elements(elements: list[dict], rects: list) -> int:
    """사각형이 감싼 텍스트 요소 앞뒤에 테두리 태그를 넣는다(in-place). 감싼 상자 수 반환.

    ★ **표·그림을 품은 사각형도 글상자다**(「제작 지침」 3장 지문 (4): 지문 속 글상자는
      속글상자). 종전에는 통째로 버려서 dev 816쪽에서 388개(검출의 25.6%)를 잃었다.
      태그는 글 요소에만 붙이되(표 HTML 안에 태그를 넣으면 표 체인이 깨진다), 시각 요소도
      읽기순서 연속성 판정에는 함께 센다.

    ★ **중첩을 살린다**(BBPG-1.2.5 위계). gold는 자료 박스 안에 표를 넣고 안쪽에 2단계
      테두리(⠖⠒…⠲)를 쓴다 — dev-2027 900쪽에 343개, 그중 81%가 1단계 안이다. 우리는
      0개였다. 사각형이 다른 사각형 안에 들면 그 깊이만큼 위계를 올려 태그한다.

    ★ `rects`와 `elements`의 bbox는 **같은 좌표계**여야 한다(부르는 쪽 책임).
    ★ 감싼 요소가 **읽기순서에서 연속**이어야 태그를 단다. 태그는 첫 요소 앞과 마지막 요소
      뒤에 붙으므로, 중간에 상자 밖 요소가 끼면 그것까지 테두리 안으로 들어간다.
      MinerU는 읽기순서를 다시 매기므로(단 클러스터링·문항번호 이동) 실제로 끊긴다.
    """
    if not rects or not elements:
        return 0
    def _inside(a, b) -> bool:
        """a가 b 안에 완전히 드는가(같은 사각형은 아니다)."""
        return (b[0] <= a[0] and b[1] <= a[1] and a[2] <= b[2] and a[3] <= b[3]
                and (a[2] - a[0]) * (a[3] - a[1]) < (b[2] - b[0]) * (b[3] - b[1]) * _BOX_SAME_AREA)

    ordered = sorted(rects, key=lambda r: -((r[2] - r[0]) * (r[3] - r[1])))
    depth = {id(r): sum(1 for q in ordered if _inside(r, q)) for r in ordered}
    claimed: dict[int, int] = {}          # 요소 → 그 요소를 이미 감싼 가장 안쪽 위계
    opens: dict[int, list] = {}           # 요소 → [(위계, 여는 태그)]
    closes: dict[int, list] = {}          # 요소 → [(위계, 닫는 태그)]
    promoted: set[int] = set()            # 테두리 제목으로 올라가 본문에서 뺄 요소
    n = 0
    for rect in ordered:
        rx0, ry0, rx1, ry1 = rect
        level = min(3, depth[id(rect)] + 1)          # 1단계부터, 3단계까지
        # 윗변에 걸친 짧은 한 줄은 **테두리 제목**으로 올린다(1장5 2)(4)②). 본문 줄이 아니라
        # 테두리 안에 박히므로 상자 몸통에서는 뺀다. ★ 첫 요소로 한정하면 안 된다 —
        # MinerU 읽기순서가 제목을 몸통 중간에 놓는 일이 잦아, 한정하면 이득의 2/3가 날아간다
        # (실측 2026-08-09: 한정 dev −6,297셀 / 전체 탐색 dev −9,000셀).
        blocked = promoted | opens.keys() | closes.keys()   # 태그를 인 요소는 못 뺀다
        title_i = _box_title_index(elements, rect, blocked)
        inside: list[int] = []            # 읽기순서 연속성 판정용(시각요소 포함)
        texts: list[int] = []             # 태그를 붙일 수 있는 요소만
        for i, el in enumerate(elements):
            bb = el.get("bbox")
            if not bb or len(bb) != 4 or i == title_i or i in promoted:
                continue
            # 중심점으로 본다 — MinerU bbox는 테두리에 닿은 글에서 몇 px 삐져나와
            # 완전포함으로 재면 실측 9요소가 든 상자에서 0개가 잡힌다(생물 p118·사문 p107).
            cx, cy = (bb[0] + bb[2]) / 2, (bb[1] + bb[3]) / 2
            if not (rx0 <= cx <= rx1 and ry0 <= cy <= ry1):
                continue
            if el.get("type") not in ("text", "list_item", "title", "caption"):
                inside.append(i)     # 표·그림: 자리만 차지한다(태그는 글 요소에만)
                continue
            if claimed.get(i, 0) >= level:      # 같은 위계에서 이미 감쌌다
                continue
            inside.append(i)
            texts.append(i)
        if not texts and title_i is not None:
            # 제목만 남으면 상자가 통째로 사라진다 — 승격을 물리고 상자를 살린다.
            inside, texts, title_i = sorted(inside + [title_i]), [title_i], None
        if not texts:
            continue
        if inside != list(range(inside[0], inside[-1] + 1)):
            logger.debug("글상자 건너뜀 — 읽기순서가 끊겼다(%s)", inside)
            continue
        title = ""
        if title_i is not None:
            title = _tag_title(elements[title_i])
            promoted.add(title_i)
        first, last = texts[0], texts[-1]
        sfx = "" if level == 1 else str(level)        # <!상자2> = 2단계(translator 규약)
        opens.setdefault(first, []).append((level, f"<!상자{sfx}>{title}<!/상자{sfx}>"))
        closes.setdefault(last, []).append((level, f"<!상자끝{sfx}><!/상자끝{sfx}>"))
        for i in texts:                         # 안쪽 상자가 다시 감쌀 수 있게 위계를 기록
            claimed[i] = max(claimed.get(i, 0), level)
        n += 1

    # 여는 것은 **바깥부터**, 닫는 것은 **안쪽부터** — 중첩이 뒤집히면 위계가 어긋난다.
    for i, tags in opens.items():
        head = "\n".join(t for _lv, t in sorted(tags))
        elements[i]["content"] = f"{head}\n{elements[i]['content']}"
    for i, tags in closes.items():
        tail = "\n".join(t for _lv, t in sorted(tags, reverse=True))
        elements[i]["content"] = f"{elements[i]['content']}\n{tail}"
    for i in sorted(promoted, reverse=True):   # 제목은 테두리 안으로 갔으니 본문에서 뺀다
        elements.pop(i)
    return n


# 테두리에 박히는 제목(「제작 지침」 1장5 2)(4)②: 제목을 테두리 7칸에 양옆 띄어 넣는다).
# 정답 도서는 dev-2027 900쪽에서 705번 쓰는데(보기 274·〈보기 N〉 198·개념 체크 48…)
# 우리는 0번이었다 — 렌더러(`layout._render_box_top`)는 있는데 태그가 늘 빈 제목이었다.
_BOX_TITLE_BAND = 22.0    # 윗변 위아래 허용폭(0~1000 정규화). 좁혀도 재현율만 깎였다
_BOX_TITLE_MAX = 12       # 제목 최대 글자수


def _tag_title(el: dict) -> str:
    return re.sub(r"<!/?[^>]+>", "", el.get("content") or "").strip()


def _box_title_index(elements: list[dict], rect, blocked) -> int | None:
    """사각형 윗변에 걸친 **짧은 한 줄** 요소의 인덱스(테두리 제목). 없으면 None."""
    rx0, ry0, rx1, _ry1 = rect
    best = None
    for i, el in enumerate(elements):
        bb = el.get("bbox")
        if (not bb or len(bb) != 4 or i in blocked
                or el.get("type") not in ("text", "list_item", "title", "caption")):
            continue
        if not (rx0 <= (bb[0] + bb[2]) / 2 <= rx1):
            continue
        d = abs((bb[1] + bb[3]) / 2 - ry0)
        if d > _BOX_TITLE_BAND:
            continue
        txt = _tag_title(el)
        if not txt or "\n" in txt or len(txt) > _BOX_TITLE_MAX:
            continue
        if best is None or d < best[0]:
            best = (d, i)
    return best[1] if best else None


# 벡터 그림 판정(교과서 지도·도표·그래프는 임베디드 이미지가 아니라 벡터로 그려진다).
# 드로잉 프리미티브를 격자로 뭉친 덩어리가 아래 둘을 모두 넘으면 그림으로 본다.
# 실측 근거(세계사 p022 지도 2개 / 사회문화 p035·외국어 p012 그림 없음, 렌더 확인):
#   지도    = 4350개·면적 5.0% , 2669개·면적 3.4%
#   장식    = 글상자 둥근모서리·머리말 배너 → 덩어리 없음 또는 225개·면적 1.7%
_VEC_MIN_PRIMS = 200      # 덩어리 내 선/곡선 프리미티브 수
_VEC_MIN_AREA = 0.03      # 덩어리가 덮는 페이지 면적 비율
_VEC_GRID = 24            # 덩어리 병합용 격자 해상도


def _has_vector_figure(page) -> bool:
    """벡터로 그려진 그림(지도·도표·그래프)이 있으면 True.

    ★ 이게 없으면 교과서 지도가 통째로 사라진다. 지도는 임베디드 이미지가 아니라 벡터라
    get_image_info() 검사를 통과하지 못하고 ZERO(PyMuPDF)로 빠지는데, 그러면 (1) 그림이
    시각자료로 잡히지 않아 캡션도 대체텍스트도 없고 (2) 지도 안 라벨(황해·흉노 등)이 본문
    텍스트로 쏟아져 읽기순서를 흩뜨린다(세계사 order_tau 0.54의 주원인).

    장식(머리말 배너·둥근 글상자)과 구분하려고 '덩어리 크기 + 면적'을 함께 본다 — 장식은
    프리미티브가 적거나(<200) 면적이 작다(<3%).
    """
    W, H = page.rect.width, page.rect.height
    page_area = (W * H) or 1.0
    try:
        drawings = page.get_drawings()
    except Exception:  # noqa: BLE001
        return False
    if len(drawings) < 8:            # 밑줄·표선 몇 개는 그림이 아니다
        return False

    # 격자 셀별로 프리미티브 수와 bbox를 모은다.
    cells: dict[tuple[int, int], list] = {}
    for dr in drawings:
        n = len(dr.get("items", []))
        if not n:
            continue
        r = dr["rect"]
        key = (int((r[0] + r[2]) / 2 / W * _VEC_GRID), int((r[1] + r[3]) / 2 / H * _VEC_GRID))
        cell = cells.setdefault(key, [0, [1e9, 1e9, -1.0, -1.0]])
        cell[0] += n
        bb = cell[1]
        bb[0] = min(bb[0], r[0]); bb[1] = min(bb[1], r[1])
        bb[2] = max(bb[2], r[2]); bb[3] = max(bb[3], r[3])

    # 인접 셀을 이어붙여(8방향) 덩어리 단위로 판정.
    seen: set[tuple[int, int]] = set()
    for start in cells:
        if start in seen:
            continue
        stack, comp = [start], []
        while stack:
            c = stack.pop()
            if c in seen or c not in cells:
                continue
            seen.add(c)
            comp.append(c)
            x, y = c
            stack.extend([(x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1),
                          (x + 1, y + 1), (x - 1, y - 1), (x + 1, y - 1), (x - 1, y + 1)])
        prims = sum(cells[c][0] for c in comp)
        if prims < _VEC_MIN_PRIMS:
            continue
        bb = [1e9, 1e9, -1.0, -1.0]
        for c in comp:
            b = cells[c][1]
            bb[0] = min(bb[0], b[0]); bb[1] = min(bb[1], b[1])
            bb[2] = max(bb[2], b[2]); bb[3] = max(bb[3], b[3])
        if (bb[2] - bb[0]) * (bb[3] - bb[1]) > _VEC_MIN_AREA * page_area:
            return True
    return False


def _page_has_visual(page) -> bool:
    """텍스트레이어 페이지에 표·유의미한 이미지가 있으면 True → MinerU(OCR) 라우팅.

    순수 텍스트는 ZERO로 빠르게 처리하되, 표·그림 등 '텍스트 기반 시각자료'는 구조·캡션이
    필요해 MinerU가 처리해야 한다(태민 방침). 작은 장식 로고는 제외(페이지 3% 미만).

    ★ 이 판정을 느슨하게 만들지 말 것 — 2026-08-02 코퍼스 1131쪽 실측 결론.

    동기는 정당했다. MinerU는 쪽당 ~9초인데 ZERO는 ~0.1초라, 안 태워도 되는 쪽을
    골라내면 처리량이 크게 는다. 실제로 **MinerU를 탔지만 표·수식·시각이 하나도
    없던 쪽이 317쪽(28.0%)**이었다. 그런데 그 낭비를 줄이려는 완화안이 전부 실패했다.

      규칙                          ZERO 라우팅   오판(구조를 놓침)
      현행                          144쪽 12.7%   **0쪽**
      표를 2행2열 이상만 인정        280쪽 24.8%   60쪽
      + 이미지 임계 3%→5%           352쪽 31.1%   117쪽
      + 벡터 도형 신호 제외          397쪽 35.1%   156쪽
      반복 출현 이미지를 장식으로 제외 180쪽 15.9%   36쪽

    놓친 쪽은 표·그림을 통째로 잃는다. 9초를 아끼자고 낼 대가가 아니다.
    - `find_tables()`의 1행/1열 검출은 노이즈가 아니었다. 선이 부분만 있는 진짜 표가
      거기 섞여 있고, MinerU는 그걸 표로 잡아낸다.
    - '반복되는 이미지 = 장식' 휴리스틱은 하필 수학2에서 깨진다. 문제집은 비슷한 그래프가
      비슷한 자리에 반복돼서, 내용 그림이 장식으로 오인된다(36쪽 중 대부분).

    즉 현행 규칙은 이미 오판 0의 파레토 점이다. 남은 낭비 317쪽은 **추출 전 신호로는
    구분되지 않는다.** 처리량을 늘리려면 이 판정이 아니라 GPU 쪽을 봐야 한다.
    측정 스크립트는 `V2/temp/probe_routing*.py`, 분석은
    `V2/docs/analysis/routing-textlayer-first-0802.md`.
    """
    page_area = (page.rect.width * page.rect.height) or 1.0
    try:
        for info in page.get_image_info():
            bb = info.get("bbox")
            if bb and (bb[2] - bb[0]) * (bb[3] - bb[1]) > 0.03 * page_area:
                return True
    except Exception:  # noqa: BLE001
        pass
    try:
        if page.find_tables().tables:   # 선이 있는 표 감지
            return True
    except Exception:  # noqa: BLE001
        pass
    return _has_vector_figure(page)     # 벡터 지도·도표·그래프


def mangled_glyph_chars(text: str) -> tuple["collections.Counter[str]", "collections.Counter[str]"]:
    """글꼴 매핑이 어긋나 잘못 추출된 글자들 → (A: 레이어 폐기, B: 기호만 어긋남).

    각각 {글자: 횟수}. 부르는 쪽은 보통 **A의 개수만** 보면 된다 — 한 글자라도 있으면
    그 텍스트레이어는 통째로 못 믿는다. B는 경고용이다(본문은 멀쩡하니 버리지 않는다).

    ⚠ 이 함수는 '고칠 수 있다'는 뜻이 아니다. 되돌리기는 글꼴마다 다른 표가 필요하고
      (¤ = ² 또는 (ii)), 표가 있어도 2차원으로 찍힌 수식은 못 살린다. 위 주석 참조.
    """
    t = text or ""
    return (collections.Counter(_MANGLED_LAYER_RE.findall(t)),
            collections.Counter(_MANGLED_SYMBOL_RE.findall(t)))


def _pua_ratio(text: str) -> float:
    """비공백 글자 중 PUA(U+E000~U+F8FF, 보충 PUA) 비율."""
    chars = [c for c in text if not c.isspace()]
    if not chars:
        return 0.0
    pua = sum(
        1 for c in chars
        if 0xE000 <= ord(c) <= 0xF8FF or 0xF0000 <= ord(c) <= 0x10FFFD
    )
    return pua / len(chars)


class InvalidPDFError(ValueError):
    """도착한 pdf_data가 유효 PDF가 아닐 때. 메시지는 BE 디버깅용 진단을 담는다."""


def diagnose_pdf_bytes(data: bytes) -> Optional[str]:
    """도착 바이트가 유효 PDF인지 진단. 문제가 없으면 None, 있으면 사유 문자열.

    BE↔AI 전송 시 흔한 변질(base64 인코딩, 경로 문자열, 텍스트 모드, 빈/잘린 데이터)을
    사람이 읽을 수 있는 진단으로 변환해 C1 BLOCKED 메시지에 실어 보낸다.
    """
    if not data:
        return "도착 데이터 길이 0 — BE가 빈 bytes를 전송(파일 핸들/경로 누락 의심)."
    head = data[:64].lstrip(b"\x00\r\n\t \xef\xbb\xbf")  # 선행 공백/BOM 제거
    if head[:5] == _PDF_MAGIC:
        return None
    # base64로 인코딩된 PDF인가? (%PDF- → 'JVBER...')
    if head[:5] == b"JVBER":
        return "base64로 인코딩된 PDF로 보임 — proto pdf_data는 raw bytes여야 함(base64 금지)."
    # 파일 경로 문자열을 그대로 bytes로 넣었는가?
    try:
        as_text = data[:256].decode("utf-8", errors="strict")
        if as_text.startswith(("/", "./", "../", "~")) or as_text[1:3] == ":\\":
            return f"PDF 바이트가 아니라 파일 경로 문자열로 보임: {as_text[:80]!r}"
    except UnicodeDecodeError:
        as_text = None
    return (
        f"PDF 매직(%PDF-) 없음 — 길이 {len(data)}B, 첫 8바이트 {data[:8]!r}. "
        "전송 중 변질이거나 BE 적재 오류(텍스트 모드/인코딩/압축 의심)."
    )


def _coerce_pdf_bytes(data: bytes) -> bytes:
    """가능하면 흔한 변질을 복구한다. 복구 불가하면 InvalidPDFError.

    - base64-of-PDF: 디코드해 사용(경고 로그). BE 버그지만 파이프라인은 진행시킨다.
    - 그 외 비-PDF: 진단 메시지와 함께 InvalidPDFError.
    """
    problem = diagnose_pdf_bytes(data)
    if problem is None:
        return data
    head = data[:16].lstrip(b"\x00\r\n\t \xef\xbb\xbf")
    if head[:5] == b"JVBER":
        try:
            decoded = base64.b64decode(data, validate=False)
        except (binascii.Error, ValueError):
            decoded = b""
        if decoded[:5] == _PDF_MAGIC:
            logger.warning("pdf_data가 base64로 도착 — 디코드해 복구함(BE는 raw bytes 전송 필요)")
            return decoded
    raise InvalidPDFError(problem)


def analyze_pdf(
    pdf_path: str | bytes,
    page_no: int,
    job_id: Optional[str] = None,
) -> tuple[DocumentMeta, str]:
    """
    pdf_path : str(파일 경로) 또는 bytes(PDF 데이터)
    page_no  : 1-indexed. 0 이하가 들어오면 +1 보정.
    job_id   : 미사용 — pipeline.py 호환용
    반환     : (DocumentMeta, page_text)
               TEXT_NATIVE → routing_tier="ZERO",     page_text=페이지 전체 텍스트
               OCR         → routing_tier="STANDARD", page_text=""
    """
    if page_no < 1:
        page_no += 1

    tmp_path = None
    try:
        if isinstance(pdf_path, bytes):
            # 도착 바이트 진단 로그(전송 변질 추적용) + 흔한 변질 복구/거부
            logger.info(
                "pdf_data 도착: page=%s len=%dB head=%r",
                page_no, len(pdf_path), pdf_path[:8],
            )
            pdf_bytes = _coerce_pdf_bytes(pdf_path)
            with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as f:
                f.write(pdf_bytes)
                tmp_path = f.name
            open_path = tmp_path
        else:
            open_path = str(pdf_path)

        doc = fitz.open(open_path)
        try:
            # proto 계약상 pdf_data는 '단일 페이지' PDF다(BE가 페이지마다 1장씩 전송).
            # page_no는 원본 문서의 페이지 번호(헤더/푸터·저장경로용)일 뿐이므로,
            # 도착 PDF 인덱스로 그대로 쓰면(예: page_no=2 → doc[1]) 단일 페이지에서
            # IndexError가 난다. 페이지 수에 맞게 클램프(단일=0, 멀티=page_no-1).
            page_idx = max(0, min(page_no - 1, doc.page_count - 1))
            page = doc[page_idx]
            text = page.get_text().strip()
            has_visual = _page_has_visual(page) if len(text) >= MIN_TEXT_LENGTH else False
            # ZERO 후보면 어절 경계 복원 텍스트로 교체(공백 글리프 없는 교과서 PDF 대응)
            if len(text) >= MIN_TEXT_LENGTH and not has_visual:
                spaced = "\n".join(b["content"] for b in _page_text_blocks_spaced(page)).strip()
                text = spaced or text
        finally:
            doc.close()
    finally:
        if tmp_path:
            os.unlink(tmp_path)

    if len(text) >= MIN_TEXT_LENGTH:
        pua = _pua_ratio(text)
        if pua >= PUA_RATIO_THRESHOLD:
            # 텍스트는 있으나 PUA 글리프 과다 → 텍스트레이어 비신뢰 → MinerU 경로.
            logger.info(
                "PUA 비율 %.1f%% (≥%.0f%%) → 텍스트레이어 비신뢰, STANDARD 라우팅 page=%s",
                pua * 100, PUA_RATIO_THRESHOLD * 100, page_no,
            )
            return DocumentMeta(pdf_confidence=0.5, routing_tier="STANDARD", scan_only=False), ""
        # ★ 경고를 꼭 남긴다 — 조용히 틀린 값이 나가는 게 제일 나쁘다. 이 쪽에서 뽑은
        #   기호 빈도는 "0회 = 없다"가 아니라 "0회 = 못 쟀다"이다.
        layer_bad, symbol_bad = mangled_glyph_chars(text)
        if symbol_bad:
            logger.warning(
                "글꼴 매핑 어긋남(기호 %d자 %s) — 본문은 유지하되 이 쪽의 기호 빈도는 "
                "믿지 말 것 page=%s",
                sum(symbol_bad.values()),
                "".join(c for c, _ in symbol_bad.most_common(8)), page_no,
            )
        if sum(layer_bad.values()) >= MANGLED_GLYPH_THRESHOLD:
            # PUA는 0%인데 글꼴 매핑이 어긋난 PDF(수학2 판 등) → 같은 처방(STANDARD).
            logger.warning(
                "글꼴 매핑 어긋남 %d자 %s → 텍스트레이어 비신뢰, STANDARD 라우팅 page=%s",
                sum(layer_bad.values()),
                "".join(c for c, _ in layer_bad.most_common(8)), page_no,
            )
            return DocumentMeta(pdf_confidence=0.5, routing_tier="STANDARD", scan_only=False), ""
        if has_visual:
            # 텍스트레이어지만 표·그림 등 시각자료 포함 → 구조·캡션 위해 MinerU OCR.
            logger.info("표·그림 포함 → STANDARD(MinerU) 라우팅 page=%s", page_no)
            return DocumentMeta(pdf_confidence=0.7, routing_tier="STANDARD", scan_only=False), ""
        # 순수 텍스트 → ZERO(빠른 직접추출).
        return DocumentMeta(pdf_confidence=1.0, routing_tier="ZERO", scan_only=False), text
    else:
        return DocumentMeta(pdf_confidence=0.5, routing_tier="STANDARD", scan_only=False), ""
