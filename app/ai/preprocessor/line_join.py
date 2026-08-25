"""줄바꿈으로 쪼개진 텍스트 조각 잇기 (이슈 #263).

좁은 글상자 안에서 줄을 바꾼 자리가 **원본 PDF 텍스트 레이어의 블록 경계**로 굳어 있고,
우리가 그 경계를 그대로 요소로 옮긴다. 그래서 한 문장이 여러 요소로 쪼개지고 낱말
한가운데가 잘린다.

    요소1  …후각은 대뇌의 감각 피질과 직접 연결되어 있습니
    요소2  다. 시각, 청각 등의 다른 감각의 경우 정보가

★ **왜 preprocessor 에 있나** — 처음에는 `mineru_runner.run()` 안에 뒀는데, 파이프라인의
  추출 경로가 둘이라 절반에 안 걸렸다.

      pipeline._extract_with_hyunju
        ├ routing_tier == "ZERO" → extract_text_blocks (pdf_analyzer)   ← MinerU 안 탄다
        └ 그 밖                   → _extract_via_models → mineru_runner

  100쪽 표본 A/B 실측: 23쪽이 TEXT_NATIVE 라 코드가 아예 안 돌았고, 이음이 난다고 본
  37쪽 중 20쪽이 그쪽이었다. **대표가 지적한 시연 문서 p01 도 ZERO 티어다.** 그래서
  A/B 가 총 편집셀 차 0 으로 나왔다(A=e3b2fe8 · B=eeea373).
  두 경로가 만나는 자리(`_extract_with_hyunju` 가 경계 dict 를 만들기 직전)로 옮겼다.

⚠ **경계 bbox 는 좌표계가 경로마다 다르다** — `meta.bbox_space` 가 `"pixel"`(2x 렌더 픽셀)
  이거나 `"norm1000"`(0~1000 정규화)이다. 여기서는 그 값을 받아 **쪽 좌표(pt)** 로 환산해
  한 벌로 잰다. 판정 임계는 전부 줄 높이 배수라 배율에 무관하다.
"""
from __future__ import annotations

import re

import fitz

# 이으면 안 되는 것 — 시행·목록 항목·선택지·표 셀은 **줄이 바뀌는 것이 뜻**이다.
# 그래서 type=text 로 좁히고, 아래 셋을 다 만족할 때만 잇는다.
#   ① 앞 조각이 문장 끝 부호 없이 끝난다
#   ② 뒤 조각이 바로 아래 줄이고 왼쪽 끝·글자 크기가 같다
#   ③ 앞 조각이 **단 오른쪽 끝까지 찼다**(= 넘쳐서 다음 줄로 밀린 줄)
# ③ 이 시행·목록과 참-줄바꿈을 가른다. 시행·목록은 할 말이 끝나 줄이 짧다.
_JOIN_TYPES = {"text"}
_JOIN_LINE_GAP = 1.2        # 다음 줄까지 세로 간격(줄 높이 배수)
_JOIN_X_TOL = 1.5           # 왼쪽 끝 어긋남(줄 높이 배수)
_JOIN_RIGHT_SLACK = 1.2     # 오른쪽 끝에서 모자란 칸 — 한글은 글자 단위로 줄을 바꾸므로
                            # 마지막 글자 하나만큼은 늘 남는다
_JOIN_HEIGHT_TOL = 0.6      # 글자 크기 어긋남(줄 높이 배수)
_JOIN_NEAR_LINES = 25       # 단 오른쪽 끝을 재려고 볼 위아래 줄 수
_JOIN_MIN_WIDTH = 6.0       # 앞 조각 최소 너비 — 'EBS'·'방사관' 같은 라벨 배제
_JOIN_FLUSH_MIN = 0.5       # 이웃 줄 중 오른쪽 끝에 닿는 비율의 하한

# 문장이 끝났다고 볼 자리 — **문장부호만** 본다.
# ⚠ '다/음/함'으로 끝나면 문장 끝이라고 보면 안 된다. '…후각은 다' + '른 감각과'처럼
#   낱말 한가운데가 잘린 자리가 그 얼굴이고, 그게 정확히 이 기능이 잡아야 할 것이다.
#   문장부호 없이 끝나는 진짜 문단 끝은 줄이 짧아서 오른쪽 끝 판정에 걸린다.
_SENT_END_RE = re.compile(r'[.!?。」』”\'"\)\]…:;·~]\s*$')

# 뒤 조각이 **새 항목을 여는가** — 글머리표·번호·우리 인라인 태그.
_ITEM_HEAD_RE = re.compile(
    r'^\s*(?:<!'
    r'|[①-⑳㉠-㉯⑴-⒇🄐-🄩ⓐ-ⓩ❶-❿]'
    r'|[•·▪▶▷◦□■○●◇◆★☆※]'
    r'|\\?[-–—]\s'                       # 마크다운으로 이스케이프된 붙임표(\-)도 글머리다
    r'|\(\s*[0-9A-Za-z가-힣ㄱ-ㅎ]{1,3}\s*\)\s'   # (5) (A) (b) (가)
    r'|[0-9]{1,2}\s*[.)]\s'
    r'|[ㄱ-ㅎ]\s*[.)]\s'
    # ⚠ '가. 나. 다.' 한글 글머리는 **일부러 안 넣는다** — '다.'가 '-습니다'의 꼬리와
    #   똑같이 생겼고, 그게 이 기능이 잡아야 할 가장 흔한 자리다("…있습니"+"다. 시각").
    #   실제 글머리는 앞 줄이 짧아서 오른쪽 끝 판정(_JOIN_RIGHT_SLACK)에 걸린다.
    r'|[IVXivx]{1,4}\s*[.)]\s'
    r')')

# 이어지는 조각이 시작할 수 있는 글자 — 한글 음절/자모, 로마자, 숫자.
_CONT_HEAD_RE = re.compile(r'^[가-힣ㄱ-ㅎA-Za-z0-9]')


def _col_edge(lines: list[fitz.Rect], bb: fitz.Rect) -> tuple[float, float]:
    """같은 단 이웃 줄들의 (오른쪽 끝, 그 끝에 닿는 줄의 비율).

    비율이 잇기 판정의 핵심이다. **넘쳐서 접힌 문단은 거의 모든 줄이 오른쪽 끝에 닿고**,
    시행·목록·낱말 나열은 할 말이 끝나는 데서 줄이 끊겨 끝이 들쭉날쭉하다.

    ★ 단 끝은 **최댓값**으로 잡는다. '가장 많은 줄이 공유하는 끝'을 쓰면 문단 몇 개를
      더 잇지만 가사·시조가 딸려 온다 — 정형시는 율격이 고정이라 행 길이가 고르고,
      그래서 '고른 오른쪽 끝'이 문단과 구별이 안 된다(언어 234쪽 실측: 오탐 0 → 20건).
      **잘못 잇는 쪽이 더 나쁘다.**
    """
    line = bb.y1 - bb.y0
    xs = [b.x1 for b in lines
          if b != bb
          and b.x1 > bb.x0 and b.x0 < bb.x1                    # 가로로 겹침
          and abs(b.y0 - bb.y0) < _JOIN_NEAR_LINES * line]     # 세로로 가까움
    if not xs:
        return 0.0, 1.0
    right = max(max(xs), bb.x1)
    flush = sum(1 for x in xs if right - x <= _JOIN_RIGHT_SLACK * line)
    return right, flush / len(xs)


def _line_seam(page: fitz.Page, rect: fitz.Rect, text: str) -> str:
    """이을 때 두 조각 사이에 넣을 것.

    한 줄이 낱말 한가운데서 잘렸으면 붙여야 하고("있습니"+"다."), 어절 끝에서 잘렸으면
    한 칸 띄어야 한다("통합한 뒤"+"감각"). 그 차이는 **원본 줄 끝의 공백**에만 남아 있다.

    ⚠ 교과서 PDF 다수는 공백 글리프가 아예 없고 커닝으로만 어절을 띄운다. 그런 줄에서
      끝 공백이 없는 것은 아무 뜻도 없다 — 느슨하게 뒀다가 '유대 관계를'+'강화하였다.'를
      붙여 버렸다(세계사 p12 실측). 그래서 **셋을 다 확인했을 때만** 붙이거나 띄우고,
      하나라도 어긋나면 개행을 남겨 종전 경로(layout_braille._fold_full_lines)가 정하게 한다.
        ① 레이어에서 읽은 마지막 줄이 이 요소의 마지막 줄과 **같은 글자**인가
        ② 그 줄의 공백 수가 우리가 복원해 둔 어절 수만큼 되는가(쉼표 뒤 공백만 있고
           어절 사이는 커닝인 지면이 있다 — "폐포, 혈액, 조직세포에서" 실측)
        ③ 그 줄이 공백으로 끝나는가 → 띄움, 아니면 → 붙임
    """
    try:
        raw = page.get_textbox(rect)
    except Exception:                       # noqa: BLE001 — 이음매는 있으면 좋은 것이다
        return "\n"
    if not raw.strip():
        return "\n"
    last = raw.rstrip("\n").split("\n")[-1]
    want = (text or "").rstrip().split("\n")[-1]
    if not want or "".join(last.split()) != "".join(want.split()):   # ①
        return "\n"
    if last.count(" ") < want.count(" "):                            # ②
        return "\n"
    return " " if last.endswith((" ", " ")) else ""             # ③


def _can_join(lines: list[fitz.Rect], a: dict, ab: fitz.Rect, b: dict,
              bb: fitz.Rect) -> bool:
    """a 의 마지막 줄(ab)과 b 가 한 줄 이어지는 자리인가."""
    if a.get("type") not in _JOIN_TYPES or b.get("type") not in _JOIN_TYPES:
        return False
    if a.get("heading_level") or b.get("heading_level"):
        return False
    at, bt = (a.get("content") or "").strip(), (b.get("content") or "").strip()
    if not at or not bt:
        return False
    # ★ 조각내진 것은 **인쇄 한 줄**짜리다. 여러 줄 블록은 앞단이 이미 문단으로 묶은
    #   것이라 손대지 않는다 — 코퍼스 실측에서 손해가 거기서 나왔다(제목 '분석·해석'이
    #   본문에 딸려 들어가고, 빈칸 표의 줄들이 한 덩어리가 됐다).
    if "\n" in bt:
        return False
    if _SENT_END_RE.search(at) or _ITEM_HEAD_RE.match(bt):
        return False
    # 줄이 넘쳐 이어지는 자리는 **글자로 이어진다** — 한글 음절이나 로마자·숫자로 시작한다.
    # 기호로 시작하면 새 항목이거나(䤎·□·⇂) 추출 잔재다. 막아 놓는 편이 싸다.
    if not _CONT_HEAD_RE.match(bt):
        return False
    if "<!" in at[-12:] or "<!" in bt[:12]:      # 우리 인라인 태그 경계는 구조다
        return False
    ah, bh = ab.y1 - ab.y0, bb.y1 - bb.y0
    if ah <= 0 or bh <= 0:
        return False
    line = min(ah, bh)
    if abs(ah - bh) > _JOIN_HEIGHT_TOL * line:
        return False
    if not (-0.5 * line <= bb.y0 - ab.y1 <= _JOIN_LINE_GAP * line):
        return False
    if abs(bb.x0 - ab.x0) > _JOIN_X_TOL * line:
        return False
    if (ab.x1 - ab.x0) < _JOIN_MIN_WIDTH * line:  # 서너 글자짜리는 단이 아니다(머리말·라벨)
        return False
    right, flush = _col_edge(lines, ab)
    if flush < _JOIN_FLUSH_MIN:                   # 끝이 들쭉날쭉하면 시행·목록이다
        return False
    return abs(right - ab.x1) <= _JOIN_RIGHT_SLACK * line


def join_wrapped_lines(elements: list[dict], page: fitz.Page, *,
                       bbox_space: str, image_width: float,
                       image_height: float) -> list[dict]:
    """줄바꿈으로 쪼개진 이웃 텍스트 요소를 하나로 잇는다. 위 주석의 판정을 쓴다.

    elements: 경계 요소(`id`/`order`/`type`/`content`/`bbox`). 제자리에서 이어 붙이고
              남은 것만 돌려준다.
    bbox_space: "pixel"(2x 렌더 픽셀) | "norm1000"(0~1000). `meta.bbox_space` 값 그대로.
    """
    W, H = page.rect.width, page.rect.height
    if W <= 0 or H <= 0:
        return elements
    if bbox_space == "pixel":
        sx, sy = (W / image_width if image_width else 0.0,
                  H / image_height if image_height else 0.0)
    else:
        sx, sy = W / 1000.0, H / 1000.0
    if sx <= 0 or sy <= 0:
        return elements

    def to_rect(bb):
        return fitz.Rect(bb[0] * sx, bb[1] * sy, bb[2] * sx, bb[3] * sy)

    # ★ 단 오른쪽 끝은 **이어붙이기 전 줄**로 잰다. 이어붙이면 bbox 가 여러 줄의
    #   합집합으로 바뀌는데, 그게 같은 dict 라 재는 쪽 시야가 같이 망가진다
    #   (문단 중간에서 사슬이 끊겼다 — 한 번 밟았다).
    lines = [to_rect(e["bbox"]) for e in elements
             if e.get("type") in _JOIN_TYPES and e.get("bbox")]
    out: list[dict] = []
    tail: fitz.Rect | None = None    # out[-1] 의 마지막 줄
    tail_text = ""                   # 그 줄의 글(이어붙이기 전 것) — 이음매 판정용
    left_ok = False                  # out[-1] 이 왼쪽으로 쓸 수 있는가(한 줄이었거나 우리가 이은 것)
    for el in elements:
        bb = el.get("bbox")
        if out and tail is not None and left_ok and bb and _can_join(
                lines, out[-1], tail, el, to_rect(bb)):
            prev = out[-1]
            # ⚠ 이음매는 **마지막 줄의 글**로 판정한다. 이어붙인 prev["content"] 를 주면
            #   두 번째 이음부터 줄 대조가 어긋나 늘 개행으로 물러선다(한 번 밟았다).
            seam = _line_seam(page, tail, tail_text)
            prev["content"] = f"{prev['content']}{seam}{el['content']}"
            prev["bbox"] = [min(prev["bbox"][0], bb[0]), min(prev["bbox"][1], bb[1]),
                            max(prev["bbox"][2], bb[2]), max(prev["bbox"][3], bb[3])]
            tail, tail_text = to_rect(bb), el["content"]
            continue
        out.append(el)
        tail = to_rect(bb) if bb else None
        tail_text = el.get("content") or ""
        left_ok = "\n" not in (el.get("content") or "").strip()
    for i, el in enumerate(out):     # 두 경로가 쓰는 이름이 다르다
        if "order" in el:
            el["order"] = i + 1
        if "reading_order" in el:
            el["reading_order"] = i
    return out
