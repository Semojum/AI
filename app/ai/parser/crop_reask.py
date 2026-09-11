"""고급 점역 crop 모드 — **깨진 요소만 잘라** 한 요청에 배치로 되묻는다.

대표 지적(2026-09-10): "그냥 깨진 거 다시 배치로 모아서 돌리는 게 그렇게 비쌀 일이야?"
쪽 전체를 LLM 에 다시 읽히는 지금 방식(`opus_fallback.extract_advanced`)은 깨진 데가 두 곳이어도
지면 전체를 읽는다. 여기서는 MinerU 요소 가운데 **기계 신호가 켜진 것**의 bbox 만 지면에서
잘라 한 요청에 묶어 보내고, 돌아온 글자를 그 요소에 갈아 끼운다. bbox·유형·읽기순서는
MinerU 것 그대로다.

실측(`temp/n10/결과_cropbatch.md` — 스캔본 정답해설 6쪽, 눈으로 센 깨진 요소 125건 원장):

    팔                          고침/125    쪽당 $    쪽당 LLM 시간
    MinerU 만                      6        0          0
    쪽 전체 LLM(page)             70~73     0.14      45~102초 (MinerU 와 나란히)
    크롭 배치(crop)               70        0.05      10~27초  (MinerU 뒤에)
    둘 다(both, **기본**)         82        0.16      page + 4~21초

신호는 부류마다 따로 세웠다. 정밀도는 6쪽 422요소 **전수**에서 "켜진 자리가 실제로 깨졌나"다.

    부류            신호                                    정밀      원장 재현
    한자            CJK 통합한자 블록                        12/12
    원문자          ⑦~⑳ · Ⓐ~ⓩ · ⊙☐\\textcircled ·          27/27     N 27/29
                    ^{\\circ} · 홑 \\circ · ①~⑤+조사 · 문장끝 ①~⑤
    깨진 글자       한글 사이 라틴 덩어리 · KS X 1001 밖 음절  4/4       (G 44 중 4)
    잘림            낱 음절+쉼표(`최,`) · 수식 끝 \\text{가}   9/9       T 5/13
    구조            \\frac 분모에 = 또는 한글 · \\xrightarrow    7/7       S 7/9
    누락            요소가 안 덮은 잉크 구역(`_page_gaps`)     —         M 25/30

  ⚠ 한글이 다른 한글로 깨진 것(`극숫값`·`획률`)은 신호가 없다 — 코퍼스 음절 bigram(정밀 36%)·
    수식 요소 안 한글(34%)은 재봤고 기각했다. 이 부류(원장 G 44 중 25)는 crop 모드가 못 고친다.
    쪽 전체 LLM 이 이것을 고치고, crop 이 원문자·구조·누락을 더 잘 고쳐 둘이 보완 관계다(both 82).

크롭 여유는 실측으로 정했다 — 세로 0.3줄·가로 1줄이 맞고, 1.5줄 여유에 빨간 테두리로 표적을
표시하는 방식은 모델이 테두리를 무시하고 이웃 줄까지 적어 **25/125** 로 무너졌다.

프롬프트 캐싱: 고정 지시문을 `system` 첫 블록(캐시 경계)에 두고 크롭은 `messages` 뒤에 둔다
(`captioner._caption_anthropic` 선례). 다만 지시문이 Sonnet 5 최소 캐시 길이(1,024토큰)에
못 미쳐 실측 `cache_read=0` 이다 — 쓰기 과금도 0 이라 손해는 없다.
"""
from __future__ import annotations

import base64
import difflib
import io
import json
import logging
import os
import re

from app.core.config import config

logger = logging.getLogger(__name__)

# ── 부류별 깨짐 신호 ─────────────────────────────────────────────────────────
_HANJA = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\uf900-\ufaff\u2f00-\u2fdf\u2e80-\u2eff]")
# 낱 음절 + 쉼표는 잘린 낱말(`실수 α의 최,`)이다. 낱말로 성립하는 음절은 뺀다 — 이 목록은
# 표본 6쪽에서 헛검출을 걷어 내며 만든 것이라(값·때 따위) 다른 책에서는 더 늘 수 있다.
_ONE_SYL = ("즉|또|단|곧|및|한|이|그|자|더|왜|뒤|앞|위|밑|안|밖|약|때|후|전|중|등|시|것|수|데|곳|년|월|일|번|개|명|점|쪽|초|분|배"
            "|외|내|저|막|끝|첫|값|식|항|선|면|각|변|꼴|쌍")
_TRUNC = re.compile(r"(?<![가-힣$)\]])(?!(?:%s),)([가-힣]),(?=\s*$|\s*\$|\s*\[|\s*\n)" % _ONE_SYL)
_JOSA = r"(에|이|을|를|의|로|과|와|은|는|에서|이다|이고|이므로|이며)"


def _rare_syllable(ch: str) -> bool:
    """KS X 1001 완성형(2,350자) 밖의 한글 음절 — `힜`·`꽀` 같은 것은 오독이다."""
    try:
        b = ch.encode("cp949")
    except UnicodeEncodeError:
        return True
    return not (0xB0 <= b[0] <= 0xC8 and 0xA1 <= b[1] <= 0xFE)


def _frac_den_bad(c: str) -> bool:
    """`\\frac{A}{B}` 의 분모에 `=` 나 한글 \\text 가 있나 — 곁주석이 분모로 들어간 꼴."""
    i = 0
    while (i := c.find(r"\frac", i)) >= 0:
        j = i + 5
        groups = []
        for _ in range(2):
            while j < len(c) and c[j] in " \t":
                j += 1
            if j >= len(c) or c[j] != "{":
                break
            d, s = 0, j
            while j < len(c):
                if c[j] == "{":
                    d += 1
                elif c[j] == "}":
                    d -= 1
                    if d == 0:
                        break
                j += 1
            groups.append(c[s + 1:j])
            j += 1
        if len(groups) == 2 and ("=" in groups[1] or re.search(r"\\text\s*\{[^}]*[가-힣]", groups[1])):
            return True
        i = max(j, i + 5)
    return False


SIGNALS = {
    # 원문자 — MinerU 가 ㉠·㉡ 을 ⑦·Ⓥ·⊙·\circ 따위로 적는다
    "circ7+": lambda c: re.search(r"[⑦-⑳]", c),
    "circLet": lambda c: re.search(r"[Ⓐ-ⓩ]", c),
    "oddglyph": lambda c: re.search(r"⊙|☐|\\textcircled", c),
    "circ-sup": lambda c: re.search(r"\^\s*\{?\s*\\circ", c),
    "circ-bare": lambda c: re.search(r"\\circ(?![a-zA-Z])", c) and not re.search(r"\^\s*\{?\s*\\circ", c),
    "circ1-5+josa": lambda c: re.search(r"[①-⑤]\s*" + _JOSA, c),
    "circ1-5-end": lambda c: re.search(r"[.?!]\s*[①-⑤]\s*$", c.strip()),
    # 한자·깨진 글자
    "hanja": lambda c: _HANJA.search(c),
    "latin-glue": lambda c: re.search(r"[가-힣][A-Za-z]{2,}|[A-Z][a-z]{2,}[A-Za-z]*\s+[0-9가-힣]",
                                      re.sub(r"\$[^$]*\$", "", c)),
    "ksx-rare": lambda c: any("가" <= ch <= "힣" and _rare_syllable(ch) for ch in c),
    # 잘림
    "trunc-comma": lambda c: _TRUNC.search(c),
    "text-tail-1syl": lambda c: re.search(r"\\text\s*\{\s*[가-힣]\s*\}\s*$", c.strip()),
    # 구조
    "frac-den": _frac_den_bad,
    "arrow/underset": lambda c: re.search(r"\\xrightarrow\s*\[|\\underset\s*\{\s*\\frac|\\underline\s*\{\{?\\angle", c),
}


def broken_signals(content: str) -> list[str]:
    """켜진 신호 이름들. 비어 있으면 멀쩡한 요소로 본다."""
    return [n for n, f in SIGNALS.items() if f(content or "")]


# ── 표적 잡기 ───────────────────────────────────────────────────────────────
_LH = 12                # 한 줄 높이(norm1000 — 지면 높이의 1.2%)
_SKIP_TYPES = ("image", "chart_graph", "diagram", "table")


def advanced_mode() -> str:
    """`page`(쪽 전체 LLM) · `crop`(깨진 요소만) · `both`(둘 다 — 기본). 호출 때 읽는다.

    **기본은 `both` 다(2026-09-11 대표 결재).** 같은 6쪽·같은 커밋에서 잰 세 팔:

        팔                          고침/125        쪽당 $     쪽당 LLM 시간
        MinerU 만                   6   (4.8%)      0          0
        쪽 전체 LLM(page)           70~73(56~58%)   0.135      45~102초
        크롭 배치(crop)             67~70(54~56%)   0.041      11~28초
        둘 다(both)                 82~84(66~67%)   0.155      page + 6~22초

    page 와 crop 은 **고치는 부류가 다르다.** page 만 한글→한글 깨짐(`극숫값`·`획률`)을 고치고,
    crop 만 원문자·구조·누락을 고친다. 그래서 둘을 같이 걸면 58.4% → 67% 로 +9~11건이다.
    값은 쪽당 +$0.02 — 고급 점역은 유료 옵션이라 그 옵션을 켠 건에만 든다.

    되돌리려면 `ADVANCED_EXTRACT_MODE=page`(종전) 또는 `=crop`(비용 1/3·시간 1/3, 교정률은 page 와 같은 띠).
    실측 원장은 `temp/n10/결과_cropbatch.md`(PR #835) · `temp/n10/결과_d1-bothdefault.md`.
    """
    return os.environ.get("ADVANCED_EXTRACT_MODE", "both")


def _ok_box(b) -> bool:
    return isinstance(b, (list, tuple)) and len(b) == 4 and b[2] > b[0] and b[3] > b[1]


def _attached(g: list[int], b: list[int]) -> bool:
    """빈 구역이 요소에 붙어 있나 — 같은 줄 옆, 또는 바로 아래(가로 절반 이상 겹침·4줄 이내)."""
    vo = min(g[3], b[3]) - max(g[1], b[1])
    if vo >= 0.5 * (g[3] - g[1]) and (abs(g[0] - b[2]) <= 2 * _LH or abs(b[0] - g[2]) <= 2 * _LH):
        return True
    ho = min(g[2], b[2]) - max(g[0], b[0])
    return ho >= 0.5 * (g[2] - g[0]) and 0 <= g[1] - b[3] <= 1.2 * _LH and g[3] - g[1] <= 4 * _LH


def crop_targets(elements: list[dict], gaps: list[list[int]]) -> list[tuple[int | None, list[int]]]:
    """(요소 번호 또는 None=빈 구역, 잘라낼 bbox). 요소에 붙은 빈 구역은 그 요소 상자에 합친다.

    MinerU 는 지면 여러 줄을 한 요소로 뭉치고 bbox 는 첫 줄만 잡는 일이 잦다 — 그때 남은 줄이
    빈 구역으로 잡히므로, 붙은 구역을 합쳐 잘라야 요소 전문이 한 크롭에 든다(p1#23 실측).
    """
    boxes: dict[int, list[int]] = {}
    for i, e in enumerate(elements):
        if e.get("type") in _SKIP_TYPES or not _ok_box(e.get("bbox")):
            continue
        if broken_signals(e.get("content") or ""):
            boxes[i] = list(e["bbox"])
    rest: list[list[int]] = []
    for g in gaps:
        if g[0] <= 10 or g[2] >= 990:          # 지면 가장자리 탭·귀(`15회`)는 글이 아니다
            continue
        cand = [(i, boxes.get(i, e["bbox"])) for i, e in enumerate(elements)
                if e.get("type") not in _SKIP_TYPES and _ok_box(e.get("bbox"))
                and _attached(g, boxes.get(i, e["bbox"]))]
        if cand:
            i, b = min(cand, key=lambda x: abs(x[1][3] - g[1]) + abs(x[1][0] - g[0]))
            boxes[i] = [min(b[0], g[0]), min(b[1], g[1]), max(b[2], g[2]), max(b[3], g[3])]
        else:
            rest.append(g)
    return [(i, boxes[i]) for i in sorted(boxes)] + [(None, g) for g in rest]


# ── 되묻기 ─────────────────────────────────────────────────────────────────
_MAX_TOKENS = 8000
_PROMPT = """당신은 한국어 수학 교재 지면의 조각 이미지를 **글자 그대로** 옮겨 적는 필사기입니다.
이미지마다 한 줄 또는 몇 줄의 글자가 들어 있습니다. 보이는 글자를 있는 그대로 적고, 지어내거나 고치거나 요약하지 않습니다.

규칙
- 한글은 한글 그대로. 지면에 없는 한자를 넣지 않습니다. 흐릿해서 못 읽는 글자는 `□` 하나로 적습니다.
- 수식은 LaTeX 으로 적습니다. 문장 안에 섞인 수식은 `$...$` 로 감싸고, 이미지 전체가 독립된 수식 한 줄이면 `$` 없이 LaTeX 만 적습니다.
  · 유니코드 수학 기호를 그대로 쓰지 마세요. `≤`는 `\\le`, `≥`는 `\\ge`, `≠`는 `\\neq`, `∫`는 `\\int`, `∑`는 `\\sum`,
    `√`는 `\\sqrt{}`, `→`는 `\\to`, `×`는 `\\times`, `⊥`는 `\\perp`, `∠`는 `\\angle`, `∈`는 `\\in`, `∞`는 `\\infty`, `∴`는 `\\therefore`, `∵`는 `\\because`, `⋯`는 `\\cdots`.
  · 분수는 `\\frac{분자}{분모}`, 첨자는 `x^{2}`·`a_{n}`, 선분은 `\\overline{AB}`, 조합은 `{}_{n}C_{r}`.
  · 그리스 글자는 `\\alpha`·`\\theta`처럼 적습니다. 라틴 글자 `a`와 그리스 `α`를 구분해서 적습니다.
- **원 안에 글자가 든 이름표(㉠ ㉡ ㉢ ㉣ ① ② ③ ④ ⑤)는 수학 기호가 아니라 이름표입니다.** 수식 안에서도 그 글자 그대로 적습니다. `\\bigcirc`·`○` 로 바꾸지 않습니다.
  네모 안에 든 숫자(카드 등)는 그 숫자만 적습니다.
- 줄이 여러 개면 줄바꿈으로 나눕니다. 곁주석(파란 글씨)이 본문 옆에 있으면 별도 줄로 적습니다.
- 이미지 위·아래 가장자리에 반쯤 잘린 줄은 적지 않습니다.

출력은 JSON 배열 하나입니다. 이미지 순서대로, 이미지마다 문자열 하나. 이미지 수와 배열 길이가 같아야 합니다. JSON 외 출력 금지."""


def _crop_b64(im, bbox: list[int]) -> str:
    """norm1000 bbox → JPEG base64. 가로 1줄·세로 0.3줄 여유, 작으면 2배 확대(150dpi 지면 실측)."""
    from PIL import Image
    W, H = im.size
    lh = H * 0.012
    x0, y0 = max(0, int(bbox[0] / 1000 * W - lh)), max(0, int(bbox[1] / 1000 * H - lh * 0.3))
    x1, y1 = min(W, int(bbox[2] / 1000 * W + lh)), min(H, int(bbox[3] / 1000 * H + lh * 0.3))
    c = im.crop((x0, y0, x1, y1)).convert("RGB")
    if c.height < 60:
        c = c.resize((c.width * 2, c.height * 2), Image.LANCZOS)
    buf = io.BytesIO()
    c.save(buf, format="JPEG", quality=92)
    return base64.b64encode(buf.getvalue()).decode()


def _ask(image_path: str, boxes: list[list[int]], model: str) -> list | None:
    """크롭 여럿을 한 요청에 묶어 되묻는다. 실패하면 None."""
    import anthropic
    from PIL import Image

    from app.ai.parser.opus_fallback import _parse
    from app.core.limits import estimate_tokens, llm_limiter
    from app.utils.req_log import record_anthropic
    im = Image.open(image_path)
    content: list[dict] = []
    nbytes = 0
    for k, b in enumerate(boxes):
        b64 = _crop_b64(im, b)
        nbytes += len(b64) * 3 // 4
        content.append({"type": "text", "text": f"[{k + 1}]"})
        content.append({"type": "image",
                        "source": {"type": "base64", "media_type": "image/jpeg", "data": b64}})
    content.append({"type": "text",
                    "text": f"이미지 {len(boxes)}장입니다. JSON 배열로 {len(boxes)}개의 문자열을 순서대로 적으세요."})
    try:
        llm_limiter().acquire_sync(estimate_tokens(_PROMPT, nbytes), _MAX_TOKENS)
        client = anthropic.Anthropic(api_key=config.anthropic_api_key or None,
                                     timeout=120.0, max_retries=1)
        # 사고를 끈다 — 필사 과제라 사고가 품질을 안 올리고, 켜 두면 상한을 사고가 먹는다(캡셔너 실측).
        resp = client.messages.create(
            model=model, max_tokens=_MAX_TOKENS, thinking={"type": "disabled"},
            system=[{"type": "text", "text": _PROMPT, "cache_control": {"type": "ephemeral"}}],
            messages=[{"role": "user", "content": content}])
        record_anthropic("크롭되묻기", model, getattr(resp, "usage", None))
        got = _parse("".join(b.text for b in resp.content if b.type == "text"))
    except Exception as exc:  # noqa: BLE001 — 되묻기 실패는 호출부가 판단한다
        logger.warning("크롭 되묻기 실패: %s", exc)
        return None
    if not isinstance(got, list) or len(got) != len(boxes):
        logger.warning("크롭 되묻기 개수 불일치(크롭 %d · 답 %s)", len(boxes),
                       len(got) if isinstance(got, list) else type(got).__name__)
        return None
    return got


# ── 갈아 끼우기 ─────────────────────────────────────────────────────────────
_KEEP = 0.6             # 갈아 끼울 글자가 원래의 이만큼은 돼야 한다. 크롭은 자리를 아니까 이식(0.85)보다 느슨하다 —
                        # MinerU 가 깨뜨리며 늘어난 글자(`∘|旦豆`·겹친 조각) 때문에 옳은 답이 더 짧은 일이 잦다(p2#29).
_DUP = 0.8
_CIRC = {c: chr(0xE000 + k) for k, c in enumerate(
    "".join(chr(x) for x in range(0x3260, 0x326F)) + "".join(chr(x) for x in range(0x2460, 0x2474))
    + "".join(chr(x) for x in range(0x24B6, 0x24EA)))}


def _norm(t: str) -> str:
    """제어어·공백·부호를 걷은 글자. 원문자는 지킨다(`\\W` 가 ㉠ 을 지우고 ⑦ 은 남겨 길이가 어긋난다)."""
    t = "".join(_CIRC.get(c, c) for c in t or "")
    t = re.sub(r"\\(begin|end)\s*\{[a-z*]+\}(\s*\{[^}]*\})?", " ", t)
    return re.sub(r"[\s\W_]+", "", re.sub(r"\\[a-zA-Z]+", " ", t))


def _covered(a: str, b: str) -> float:
    if not a:
        return 0.0
    return sum(x.size for x in difflib.SequenceMatcher(None, a, b).get_matching_blocks()) / len(a)


def _fit_math(txt: str, typ: str) -> str:
    """MinerU 유형에 맞춘다 — formula 요소엔 `$` 없이, text 요소의 벌거벗은 LaTeX 는 `$` 로 감싼다."""
    t = txt.strip()
    if typ == "formula":
        if t.startswith("$") and t.endswith("$") and t.count("$") == 2:
            t = t[1:-1].strip()
        return t
    bare = re.sub(r"\$[^$]*\$", "", t)
    if (re.search(r"\\[a-zA-Z]+|\^\{|_\{", bare)
            and not re.search(r"[가-힣]", re.sub(r"\\text\s*\{[^}]*\}", "", bare))):
        return "$" + t + "$"
    return t


def _clean(a: str) -> str:
    """점선 리더(`……`·`----`)를 부호 줄로 옮긴 것을 걷는다 — 실측 헤더 줄마다 붙어 나왔다."""
    a = re.sub(r"(?:[-–—·.]\s?){4,}|[⋯…]{2,}", " ", a)
    return re.sub(r"[ \t]{2,}", " ", a).strip()


def _apply(elements: list[dict], targets: list[tuple[int | None, list[int]]], answers: list) -> int:
    from app.ai.captioning.captioner import guard_llm_text   # 지연 — openai SDK
    from app.core.pipeline import _insert_recovered
    n_orig = [_norm(e.get("content")) for e in elements]
    changed = 0
    plan: list[tuple[int, list[int], str]] = []

    def neighbour_has(nl: str, ks, *, own: str = "") -> bool:
        return any(len(n_orig[k]) >= 5 and _covered(nl, n_orig[k]) >= _DUP and _covered(nl, own) < _DUP
                   for k in ks)

    for (i, box), a in zip(targets, answers):
        if not isinstance(a, str):
            continue
        a = _clean(guard_llm_text(a, "body"))
        lines = [ln for ln in a.split("\n") if _norm(ln)]
        if i is None:
            # 빈 구역 — 근처 요소가 이미 가진 줄은 걷고, 남는 것이 있어야 세운다
            near = [k for k, e in enumerate(elements) if _ok_box(e.get("bbox"))
                    and max(e["bbox"][0], box[0]) - min(e["bbox"][2], box[2]) < 3 * _LH
                    and max(e["bbox"][1], box[1]) - min(e["bbox"][3], box[3]) < 4 * _LH]
            keep = [ln for ln in lines
                    if not any(len(n_orig[k]) >= 5 and (_covered(_norm(ln), n_orig[k]) >= _DUP
                                                        if len(_norm(ln)) >= 5 else _norm(ln) in n_orig[k])
                               for k in near)]
            txt = "\n".join(keep)
            if len(_norm(txt)) < 4:
                continue
            def ov(b):
                return (min(b[2], box[2]) - max(b[0], box[0])) / max(1, box[2] - box[0])
            above = [k for k, e in enumerate(elements) if _ok_box(e.get("bbox")) and ov(e["bbox"]) >= 0.3
                     and e["bbox"][3] <= box[1] + 5]
            below = [k for k, e in enumerate(elements) if _ok_box(e.get("bbox")) and ov(e["bbox"]) >= 0.3
                     and e["bbox"][1] >= box[3] - 5]
            if above:
                pos = max(above, key=lambda k: elements[k]["bbox"][3]) + 1
            elif below:
                pos = min(below, key=lambda k: elements[k]["bbox"][1])
            else:
                continue
            plan.append((pos, box, txt))
            continue
        # 요소 — 크롭이 물고 온 이웃 줄은 걷고, 글자 수가 너무 줄면 손대지 않는다
        ks = [k for k in range(max(0, i - 4), min(len(elements), i + 5)) if k != i]
        keep = [ln for ln in lines if not (len(_norm(ln)) >= 5 and neighbour_has(_norm(ln), ks, own=n_orig[i]))]
        txt = "\n".join(keep)
        if len(_norm(txt)) < _KEEP * len(n_orig[i]):
            continue
        new = _fit_math(txt, elements[i].get("type") or "text")
        if new != elements[i].get("content"):
            elements[i]["content"] = new
            changed += 1
    return changed + _insert_recovered(elements, plan)


def reask_crops(elements: list[dict], image_path: str, model: str | None = None) -> int | None:
    """깨진 요소·빈 구역을 잘라 되묻고 갈아 끼운다. 바뀐 요소 수(되물을 것이 없으면 0), 못 물으면 None.

    bbox 는 norm1000 이어야 한다(MinerU 경로). 끝에 `relabel_circles` 를 건다 — 크롭에서도 수식
    문맥의 ㉠ 을 `\\bigcirc`·ⓒ 로 적는 판이 있어(#814 와 같은 현상) 그 자리만 한 번 더 묻는다.
    """
    from app.ai.parser import opus_fallback as OF
    from app.core.pipeline import _page_gaps
    model = model or OF.ADVANCED_MODEL
    boxes = [e.get("bbox") for e in elements]
    targets = crop_targets(elements, _page_gaps(image_path, boxes) if any(_ok_box(b) for b in boxes) else [])
    if not targets:
        return 0
    got = _ask(image_path, [b for _, b in targets], model)
    if got is None:
        return None
    n = _apply(elements, targets, got)
    OF.relabel_circles(elements, image_path)
    logger.info("크롭 되묻기 %d장 → %d요소 갈아 끼움", len(targets), n)
    return n
