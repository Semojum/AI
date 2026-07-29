"""
MinerU VLM 백엔드로 PDF 단일 페이지 처리.

입력:  pdf_path, page_no (1-indexed), job_id, extraction_method
출력:  storage/jobs/{job_id}/temp/page_{no:03d}/
        mineru_raw/images/{element_id}.jpg  (이미지/표 요소)
       debug=True 시 추가:
        storage/jobs/{job_id}/temp/page_{no:03d}/merged_layout.json
반환:  merged_layout (list[dict])
"""
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import fitz

TYPE_MAP = {
    "title":               "title",
    "text":                "text",
    "caption":             "caption",
    "interline_equation":  "formula",
    "inline_equation":     "formula",
    "equation":            "formula",
    "list":                "list_item",
    "footnote":            "footnote",
    "sidebar":             "sidebar",
    "header":              "header_footer",
    "header_footer":       "header_footer",
    "page_number":         "page_number",
    "table":               "table",
    "image":               "image",
    "chart":               "chart_graph",
    "cartoon":             "cartoon",
    "figure":              "image",
}


def _run_mineru(pdf_path: Path, out_dir: Path, page_idx: int, timeout: float | None = None) -> None:
    # MinerU는 별도 env에 설치(transformers 버전 충돌 회피). bare 'mineru'가 PATH에
    # 없을 수 있어 MINERU_BIN으로 실행 파일 경로를 덮어쓸 수 있게 한다(GCP는 심볼릭).
    mineru_bin = os.environ.get("MINERU_BIN", "mineru")
    cmd = [
        mineru_bin, "-p", str(pdf_path), "-o", str(out_dir),
        "-s", str(page_idx), "-e", str(page_idx),   # 도착 PDF 내 0-based 인덱스
    ]
    # 영구 mineru-api가 떠 있으면 thin client로 붙어 모델 재로드를 피한다(추출 대폭 단축).
    # 없으면 요청마다 로컬 VLM 로드(vlm-engine 폴백).
    from app.ai.parser import mineru_service
    api_url = mineru_service.get_url()
    # ★ 2026-07-29 — 백엔드를 **경로와 무관하게 명시**한다.
    #   종전엔 영구 서비스가 떠 있으면 -b를 안 넘겨 MinerU 기본값 **hybrid-engine**이 쓰이고,
    #   서비스가 없을 때만 vlm-engine이 쓰였다. 즉 **같은 문서가 서비스 가동 여부에 따라 다른
    #   백엔드로** 처리됐다. 실측 피해(사회문화 p178, 동일 페이지):
    #     hybrid+effort medium(구 기본) → text 35 · list **0**   (본문 과분절·목록 소실)
    #     vlm-engine 또는 hybrid+high   → text  8 · list  7      (07-17 캐시와 일치)
    #   목록이 사라지면 글머리 3칸 들여쓰기(BBPG 2장3절5)가 통째로 빠진다.
    backend = os.environ.get("MINERU_BACKEND", "hybrid-engine")
    cmd += ["-b", backend]
    if api_url:
        cmd += ["--api-url", api_url]
    # hybrid 백엔드의 파싱 강도. **기본 medium은 이미지·차트 분석을 끄고 목록 구조도 잃는다.**
    # 동일 페이지(사회문화 p178) 실측 — medium: text 35·list 0 (8초) / high: text 8·list 7 (40초)
    #   / vlm-engine: text 8·list 7 (40초). 즉 품질 차이는 백엔드가 아니라 **effort**이고,
    #   high는 vlm-engine과 같은 결과를 같은 시간에 낸다.
    # ⚠ 속도 5배 차이는 원가 모형의 '읽어내기' 항목을 직접 바꾼다 — 운영 기본값을 바꿀 때는
    #   비용 재산정이 따라야 한다. 그래서 env로 내렸다: MINERU_EFFORT=medium 이면 구 동작.
    effort = os.environ.get("MINERU_EFFORT", "high" if "hybrid" in backend else None)
    if effort in ("medium", "high"):
        cmd += ["--effort", effort]
    try:
        # timeout: 페이지 예산(C7)을 MinerU가 다 태우기 전에 서브프로세스를 끊는다(C9).
        # 초과 시 subprocess가 프로세스를 kill하므로 고아 프로세스가 남지 않는다.
        result = subprocess.run(cmd, capture_output=False, text=True, timeout=timeout)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(
            f"MinerU 추출 타임아웃 (>{exc.timeout:.0f}s, page_idx={page_idx}) — 텍스트레이어 폴백 대상"
        ) from exc
    if result.returncode != 0:
        # sys.exit 금지: 라이브러리가 프로세스를 죽이면 안 된다. 예외를 올려 호출자
        # (pipeline 페이지 격리 / 러너)가 해당 페이지만 ERROR 처리하고 계속하게 한다.
        raise RuntimeError(f"MinerU 실행 실패 (returncode={result.returncode}, page_idx={page_idx})")


def _find_content_list(out_dir: Path) -> Path:
    candidates = list(out_dir.rglob("*_content_list.json"))
    if not candidates:
        raise FileNotFoundError(f"content_list.json not found under {out_dir}")
    return candidates[0]


def _cleanup_mineru_output(raw_dir: Path) -> None:
    for pattern in ("*_content_list_v2.json", "*.md", "*_layout.pdf", "*_origin.pdf"):
        for f in raw_dir.rglob(pattern):
            f.unlink()


def _flatten_mineru_output(raw_dir: Path) -> None:
    """
    MinerU가 만든 {pdf_stem}/{backend}/ 중첩 구조를 raw_dir/ 바로 아래로 펼침.
    JSON → raw_dir/*.json
    이미지 → raw_dir/images/*.jpg
    빈 서브디렉토리 제거
    """
    images_dir = raw_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # JSON 파일 → raw_dir 루트
    for f in list(raw_dir.rglob("*.json")):
        if f.parent != raw_dir:
            shutil.move(str(f), str(raw_dir / f.name))

    # 이미지 파일 → raw_dir/images/
    for f in list(raw_dir.rglob("*.jpg")):
        if f.parent != images_dir:
            dst = images_dir / f.name
            if not dst.exists():
                shutil.move(str(f), str(dst))

    # 빈 서브디렉토리 제거
    for item in list(raw_dir.iterdir()):
        if item.is_dir() and item != images_dir:
            shutil.rmtree(str(item))


def _extract_text_native(fitz_page: fitz.Page, bbox: list[float]) -> str:
    w, h = fitz_page.rect.width, fitz_page.rect.height
    rect = fitz.Rect(
        bbox[0] / 1000 * w, bbox[1] / 1000 * h,
        bbox[2] / 1000 * w, bbox[3] / 1000 * h,
    )
    return fitz_page.get_text("text", clip=rect).strip()


# ── 텍스트 레이어 우선(하이브리드) ────────────────────────────────────────────
# MinerU는 레이아웃(블록 경계·읽기순서·시각자료 탐지)에 쓰고, 글자는 PDF 텍스트 레이어에서
# 가져온다. 교과서 PDF는 대부분 텍스트 레이어가 있는데도 표·그림 때문에 STANDARD(OCR)로
# 라우팅돼 VLM이 글자를 다시 읽었고, 그 과정에서 오탈자가 났다
# (예: "내동댕이치고"→"내동 Charging이치고", "불을 살랐다"→"붙을 살랐다").
# dev 18p 측정: 무수정 실패 요소의 절반 이상이 이 추출 오탈자였다.
_NATIVE_TEXT_TYPES = frozenset({
    "text", "title", "caption", "list_item", "footnote", "sidebar",
    "header_footer", "page_number",
})
# 수식은 제외 — 한컴 수식 폰트 PDF는 수식을 PUA로 인코딩해 텍스트 레이어가 깨진다.
# 표도 제외 — MinerU가 내는 건 HTML 구조(table_body)라 평문으로 대체하면 구조가 사라진다.
_PUA_RATIO_MAX = 0.05     # 사설 영역 글리프가 이 비율을 넘으면 텍스트 레이어를 믿지 않는다
_SIM_MIN = 0.45           # MinerU 결과와 이만큼도 안 닮으면 bbox가 어긋난 것 → 대체 안 함


# ── 표 셀 글머리 기호 복원 ───────────────────────────────────────────────────
# 「한국 점자 규정」 제72항(규정_텍스트.txt:2892)은 ○ □ △ •를 **글머리 기호**로 규정한다.
# 즉 표 셀 안의 •는 장식이 아니라 항목 경계다. MinerU가 이를 놓치면(통째 소실 또는
# 가운뎃점 ·로 하향 오독) 셀이 "…가능함연구 대상에…"처럼 항목이 들러붙은 런온 문장이 되고,
# 점자에서도 항목 구분이 사라진다.
# 표는 위 _NATIVE_TEXT_TYPES에서 제외돼 있다(HTML 구조를 평문으로 덮으면 표가 깨진다).
# 그래서 텍스트 전면 대체 대신 **글머리 글리프만** 텍스트 레이어를 근거로 되돌린다.
# 판단 근거는 PDF 원문(레이어)이지 정답 코퍼스가 아니며, 특정 페이지·과목 조건은 쓰지 않는다.
_BULLET_GLYPHS = "•‣▪▫●■∙⁃"      # 원문이 글머리로 쓰는 글리프
_BULLET_DEGRADED = "·・･‧"        # 글머리가 하향 오독되는 가운뎃점 계열
_BULLET_KEY_LEN = 10              # 글머리 뒤 본문 n글자를 '항목 지문'으로 삼아 셀에서 찾는다
_BULLET_KEY_MIN = 6               # 이보다 짧아지면 우연 일치 위험 → 셀 첫머리에서만 인정
_BULLET_ANY_RE = re.compile(f"[{_BULLET_GLYPHS}]")
# 레이어 대조에서 무시할 마크업: MinerU가 셀 안 수식에 두르는 $ (묵자 원문에 없다)
_BULLET_SKIP_CHARS = " \t\r\n\f\v$　"


def _bullet_item_keys(layer: str) -> list[str]:
    """레이어 텍스트에서 '글머리 뒤 본문 지문'을 등장 순서대로 뽑는다(공백 제거 기준).

    항목이 짧으면(예 '배우자') 지문도 짧다 — 버리지 않고 그대로 두고, 대조 쪽에서
    셀 첫머리 조건으로 안전을 확보한다.
    """
    ns = re.sub(r"\s+", "", layer)
    keys: list[str] = []
    for m in _BULLET_ANY_RE.finditer(ns):
        tail = ns[m.end():m.end() + _BULLET_KEY_LEN]
        keys.append(_BULLET_ANY_RE.split(tail)[0])   # 다음 글머리 전까지만
    return keys


def _restore_table_bullets(fitz_page: fitz.Page, bbox: list[float], html: str) -> str:
    """표 셀에서 유실·오독된 글머리 기호를 텍스트 레이어를 근거로 되살린다.

    레이어에 글머리가 없으면 아무것도 하지 않는다(대다수 표는 여기서 끝난다).
    ★ 부분 복원 금지: 한 항목이라도 못 찾으면 그 표는 통째로 손대지 않는다. 같은 셀에서
    항목 하나만 글머리를 달면 나머지 항목이 그 항목의 이어짐처럼 읽혀, 아무것도 안 한
    것보다 위계가 더 어긋난다(생물 p180 실측: 10개 중 4개만 복원 시 편집 +36셀).
    """
    if not html or not bbox:
        return html
    layer = _extract_text_native(fitz_page, bbox)
    if not layer or not _BULLET_ANY_RE.search(layer):
        return html
    if _pua_ratio(layer) > _PUA_RATIO_MAX:
        return html
    keys = _bullet_item_keys(layer)
    if not keys or not all(keys):
        return html

    # 공백·수식 구분자를 뺀 대조본 ↔ 원문 인덱스 대응표
    # (지문은 이 대조본에서 찾고, 수정은 원문 자리에 한다)
    ns_chars, ns_idx = [], []
    for i, ch in enumerate(html):
        if ch not in _BULLET_SKIP_CHARS:
            ns_chars.append(ch)
            ns_idx.append(i)
    ns = "".join(ns_chars)

    ops: dict[int, int] = {}   # 원문 위치 → 덮어쓸 길이(0=삽입, 1=글리프 교체)
    cur = 0
    for key in keys:
        # 지문 꼬리는 레이어 줄바꿈 때문에 옆 블록 글자를 물고 올 수 있다 → 뒤에서 줄여 가며
        # 확실히 공유되는 앞부분만 쓴다.
        occ: list[int] = []
        used_len = len(key)
        for ln_ in range(len(key), 0, -1):
            occ = [m.start() for m in re.finditer(re.escape(key[:ln_]), ns)]
            if occ:
                used_len = ln_
                break
        if not occ:
            return html                     # 한 항목이라도 못 찾으면 이 표는 포기
        if len(occ) == 1:
            p = occ[0]                      # 유일하면 순서와 무관하게 확정
        else:
            later = [x for x in occ if x >= cur]   # 같은 문구가 여러 행에 반복되는 표
            if not later:
                return html
            p = later[0]
        cur = max(cur, p + 1)
        start = ns_idx[p]
        j = start - 1                       # 항목 바로 앞의 '내용' 글자(공백·$ 건너뜀)
        while j >= 0 and html[j] in _BULLET_SKIP_CHARS:
            j -= 1
        if j >= 0 and html[j] in _BULLET_GLYPHS:
            continue                        # 이미 살아 있다
        if used_len < _BULLET_KEY_MIN and not (j >= 0 and html[j] in ">" + _BULLET_DEGRADED):
            return html   # 짧은 지문은 셀 첫머리(또는 남은 글머리 자리)에서만 믿는다
        if j >= 0 and html[j] in _BULLET_DEGRADED:
            pos, ln_over = j, 1             # 가운뎃점으로 하향 오독 → 글머리로 환원
        else:
            # 통째 소실 → 항목 앞 빈 구간 중 **수식 밖**인 가장 이른 자리에 되살린다.
            # ($ 짝 안쪽에 넣으면 수식이 깨진다 — MinerU가 셀 안 수식을 $…$로 감싼다.)
            pos, ln_over = start, 0
            for k in range(j + 1, start + 1):
                if html.count("$", 0, k) % 2 == 0:
                    pos = k
                    break
        if pos in ops:
            return html                     # 두 항목이 같은 자리를 가리킨다 → 신뢰 불가
        ops[pos] = ln_over
    if not ops:
        return html
    out = html
    for pos in sorted(ops, reverse=True):
        out = out[:pos] + "•" + out[pos + ops[pos]:]
    return out


def _pua_ratio(s: str) -> float:
    if not s:
        return 0.0
    pua = sum(1 for ch in s if 0xE000 <= ord(ch) <= 0xF8FF)
    return pua / len(s)


def _native_text_spaced(fitz_page: fitz.Page, bbox: list[float]) -> str:
    """bbox 안의 텍스트를 어절 경계 복원해서 뽑는다.

    ⚠ get_text("text")를 그대로 쓰면 안 된다 — 교과서 PDF 다수가 공백 글리프 없이 글자
    위치(커닝)로만 어절을 띄우므로 "명중기왕수인이성리학의"처럼 붙어 나온다. 점자는 띄어쓰기가
    규칙이라 그대로 점역하면 정답과 크게 어긋난다(세계사 p086 실측: cell_ns 0.87→0.39).
    pdf_analyzer의 글자 간격 기반 복원(_page_text_blocks_spaced)을 재사용한다.
    """
    from app.ai.preprocessor.pdf_analyzer import _line_text_with_word_gaps, underline_rects

    w, h = fitz_page.rect.width, fitz_page.rect.height
    uls = underline_rects(fitz_page)   # 밑줄(드러냄표, 규정 제56항) — 벡터 선으로만 존재
    rect = fitz.Rect(bbox[0] / 1000 * w, bbox[1] / 1000 * h,
                     bbox[2] / 1000 * w, bbox[3] / 1000 * h)
    # ⚠ 회전된 페이지(교과서 PDF에 흔함 — 언어 영역은 270°): rawdict의 줄 bbox는 회전 전
    # 좌표계라 MinerU가 쓰는 렌더(표시) 좌표와 어긋난다. rotation_matrix로 표시 좌표로 옮긴다.
    # (이걸 빠뜨리면 회전 페이지에서 매칭이 전부 실패해 OCR 오탈자가 그대로 남는다.)
    rot = fitz_page.rotation_matrix
    lines: list[str] = []
    for blk in fitz_page.get_text("rawdict").get("blocks", []):
        if blk.get("type") != 0:      # 0 = 텍스트 블록
            continue
        for ln in blk.get("lines", []):
            lb = fitz.Rect(ln.get("bbox") or (0, 0, 0, 0)) * rot
            # 줄 단위로 고른다(블록 단위는 다단 레이아웃에서 요소 경계와 어긋난다).
            # 줄 면적의 과반이 요소 bbox 안에 들어와야 채택 — 이웃 단 글자 혼입 방지.
            if lb.get_area() <= 0 or (lb & rect).get_area() / lb.get_area() < 0.6:
                continue
            t = _line_text_with_word_gaps(ln, rot, uls)
            if t:
                lines.append(t)
    return "\n".join(lines).strip()


def _native_override(fitz_page: fitz.Page, bbox: list[float], mineru_text: str) -> str | None:
    """텍스트 레이어로 대체할 값. 못 믿으면 None(= MinerU 결과 유지)."""
    native = _native_text_spaced(fitz_page, bbox)
    if not native or _pua_ratio(native) > _PUA_RATIO_MAX:
        return None
    base = (mineru_text or "").strip()
    if not base:
        return native
    # 같은 블록을 가리키는지 확인 — clip은 겹치는 글리프를 다 가져오므로 bbox가 어긋나면
    # 옆 블록 글자가 섞여 들어온다. 그런 경우는 MinerU 쪽을 그대로 둔다.
    from difflib import SequenceMatcher
    a = "".join(native.split())
    b = "".join(base.split())
    if SequenceMatcher(None, a, b).ratio() < _SIM_MIN:
        return None
    return native


_MD_SEP_RE = re.compile(r"^\s*\|?[\s:|-]+\|?\s*$")


def _chart_data_table(md: str) -> str:
    """MinerU가 차트에서 뽑은 markdown 표 → 표 점역이 먹는 '|' 격자. 표가 아니면 "".

    MinerU는 그래프(막대·원·꺾은선)를 읽어 `| Category | Value |` 형태의 데이터 표를 낸다.
    정답 도서도 그래프를 이렇게 전사하므로(수치가 본문에 살아 있어야 함) 그대로 표로 넘긴다.
    """
    if not md or "|" not in md:
        return ""
    if "mermaid" in md or "-->" in md:
        return ""   # 흐름도(mermaid)는 라벨에 '|'를 쓴다 — 표로 오인하면 도식이 깨진다
    rows: list[str] = []
    for ln in md.splitlines():
        s = ln.strip()
        if not s or "|" not in s or _MD_SEP_RE.match(s):   # markdown 구분선(|---|) 제거
            continue
        cells = [c.strip() for c in s.strip("|").split("|")]
        if any(cells):
            rows.append(" | ".join(cells))
    return "\n".join(rows) if len(rows) >= 2 else ""


# mermaid 노드 선언: A["영국"] · B(청) — 따옴표형을 먼저 잡는다("청 (광저우)"처럼 괄호가
# 라벨 안에 들어 있어 따옴표 없이 자르면 잘린다).
_MM_NODE_Q = re.compile(r'(\w+)\s*[\[({]\s*"([^"]*)"\s*[\])}]')
_MM_NODE_U = re.compile(r'(\w+)\s*[\[({]\s*([^"\])}]+?)\s*[\])}]')
_MM_ARROW = re.compile(r"(?:-->|---|==>|-\.->)")
_MM_EDGE_RE = re.compile(r"(\w+)\s*(?:-->|---|==>|-\.->)\s*(?:\|([^|]*)\|)?\s*(\w+)")
_HANGUL_RE = re.compile(r"[가-힣]")


def _flowchart_lines(md: str) -> str:
    """MinerU가 흐름도에서 뽑은 mermaid → 정답 도서식 화살표 줄.

    정답 표기: "영국-은-→청"(라벨 있는 간선) · "영국→청"(라벨 없음).
    MinerU가 도식을 이미 구조로 읽어 주므로 캡셔닝 없이 그대로 옮긴다(rule-based).
    """
    if not md or ("mermaid" not in md and not _MM_ARROW.search(md)):
        return ""
    names: dict[str, str] = {}
    for k, v in _MM_NODE_U.findall(md):
        names[k] = v.strip()
    for k, v in _MM_NODE_Q.findall(md):      # 따옴표형이 우선
        names[k] = v.strip()
    # 노드 선언을 식별자만 남기고 지운다 — 안 지우면 `A["영국"] --> B` 의 첫 간선이 안 잡힌다
    stripped = _MM_NODE_Q.sub(r"\1", md)
    stripped = _MM_NODE_U.sub(r"\1", stripped)
    lines: list[str] = []
    for src, label, dst in _MM_EDGE_RE.findall(stripped):
        a, b = names.get(src, src), names.get(dst, dst)
        lab = (label or "").strip()
        lines.append(f"{a}-{lab}-→{b}" if lab else f"{a}→{b}")
    text = "\n".join(lines)
    return text if _HANGUL_RE.search(text) else ""



def run(
    pdf_path: str,
    page_no: int,
    job_id: str,
    extraction_method: str,
    mineru_cache_dir: str | None = None,
    debug: bool = False,
    timeout: float | None = None,
) -> list[dict]:
    """
    pdf_path: 전체 PDF 경로
    page_no: 1-indexed
    job_id: 저장 경로 식별자
    extraction_method: 'TEXT_NATIVE' | 'OCR'
    mineru_cache_dir: 이미 mineru 결과가 있으면 재사용 (None이면 새로 실행)
    debug: True이면 merged_layout.json을 test/results/page_{no:03d}/에 저장
    timeout: MinerU 서브프로세스 타임아웃(초). None이면 무제한(오프라인 러너 호환)

    반환: merged_layout (list[dict])
    """
    pdf_path = Path(pdf_path)
    base = Path("storage") / "jobs" / job_id / "temp" / f"page_{page_no:03d}"

    # proto 계약상 pdf_data는 '단일 페이지' PDF(BE가 페이지마다 1장씩 전송). page_no는
    # 원본 문서 페이지 번호(저장경로용)이므로 도착 PDF 인덱스로 그대로 쓰면 단일 페이지에서
    # 범위 초과. 페이지 수에 맞게 클램프(단일=0, 멀티=page_no-1).
    with fitz.open(str(pdf_path)) as _d:
        page_idx = max(0, min(page_no - 1, _d.page_count - 1))

    raw_dir = Path(mineru_cache_dir) if mineru_cache_dir else base / "mineru_raw"
    if not list(raw_dir.rglob("*_content_list.json")):
        raw_dir.mkdir(parents=True, exist_ok=True)
        _run_mineru(pdf_path, raw_dir, page_idx, timeout=timeout)
        _cleanup_mineru_output(raw_dir)
        _flatten_mineru_output(raw_dir)

    cl_path = _find_content_list(raw_dir)
    with open(cl_path, encoding="utf-8") as f:
        content_list = json.load(f)

    images_dir = raw_dir / "images"
    images_dir.mkdir(exist_ok=True)

    # 이미지 이름 매핑 (hash_stem → element_id): 캐시 재실행 시에도 동일 element_id 유지
    mapping_file = images_dir / "mapping.json"
    hash_to_eid: dict[str, str] = {}
    if mapping_file.exists():
        hash_to_eid = json.loads(mapping_file.read_text(encoding="utf-8"))

    # PDF 페이지 크기 (bbox 픽셀 변환용, 2x 렌더 기준)
    doc = fitz.open(str(pdf_path))
    fitz_page = doc[page_idx]
    rect = fitz_page.rect
    img_w = int(rect.width * 2)
    img_h = int(rect.height * 2)

    merged_layout = []
    order = 1

    for item in content_list:
        item_type = item.get("type", "text")
        mapped_type = TYPE_MAP.get(item_type, "text")
        if mapped_type == "image" and item.get("sub_type") == "flowchart":
            mapped_type = "chart_graph"
        # 인쇄 캡션이 있는 시각자료는 생성 설명(GPT-4o+점역자주) 대신 인쇄 캡션을 그대로
        # plain text(caption)로 방출한다 — 정답 점역 컨벤션 정렬(rule-based vs generation 분리).
        # 캡션 없는 도식만 생성 경로로 남긴다.
        # ★ 단, MinerU가 도식/그래프에서 데이터를 뽑아 준 경우에는 캡션으로 갈아치우지 않는다.
        #   ("(가)" 캡션 하나만 남고 삼각무역 도식이 통째로 사라지던 버그 — 세계사 p160)
        printed_cap = item.get("image_caption")
        if isinstance(printed_cap, list):
            printed_cap = " ".join(x for x in printed_cap if x)
        forced_caption = (printed_cap or "").strip() if mapped_type in ("image", "chart_graph", "cartoon") else ""
        has_data = bool(_chart_data_table(item.get("content", ""))
                        or _flowchart_lines(item.get("content", "")))
        if forced_caption and not has_data:
            mapped_type = "caption"
        bb = item.get("bbox")
        if bb is None:
            continue

        element_id = str(uuid.uuid4())
        img_path_rel = item.get("img_path")
        image_path = None

        if img_path_rel:
            # flatten 후 이미지는 raw_dir/images/{hash}.jpg 에 있음
            hash_stem = Path(img_path_rel).stem
            src = images_dir / Path(img_path_rel).name
            if src.exists():
                dst = images_dir / f"{element_id}.jpg"
                shutil.move(str(src), str(dst))
                hash_to_eid[hash_stem] = element_id
                image_path = str(dst)
            elif hash_stem in hash_to_eid:
                # 캐시 재실행: 이미 이름 변경된 파일 재사용
                element_id = hash_to_eid[hash_stem]
                existing = images_dir / f"{element_id}.jpg"
                if existing.exists():
                    image_path = str(existing)
            if item_type == "table":
                content = item.get("table_body", "")
            elif mapped_type in ("image", "chart_graph", "cartoon"):
                # ★ MinerU가 차트에서 데이터 표를 뽑아 주면(markdown) 그걸 쓴다 — 정답 도서도
                #   그래프를 데이터 표로 전사한다("언어 문제  64.9"). 이걸 버리고 캡셔닝을
                #   기다리면 API 없이는 요소가 통째로 비고, 있어도 생성 설명이 수치를 놓친다.
                #   (rule-based vs generation 분리 원칙: 추출된 데이터는 규칙으로 옮긴다)
                raw_content = item.get("content", "")
                data = _chart_data_table(raw_content)
                flow = _flowchart_lines(raw_content) if not data else ""
                if data:
                    content, mapped_type = data, "table"
                elif flow:
                    # 흐름도(삼각무역 도식 등) — 정답도 화살표 줄로 전사한다.
                    # 인쇄 캡션("(가)")이 있으면 앞에 붙여 어느 도식인지 알 수 있게 한다.
                    content = f"{forced_caption}\n{flow}" if forced_caption else flow
                    mapped_type = "text"
                else:
                    # ⚠ 그림 속 평문(지도 지명 라벨 등)은 쓰지 않는다. MinerU가 "전(합)"처럼
                    #   같은 라벨을 수십 번 게워내고, 정답 도서도 지명을 그렇게 나열하지 않는다
                    #   (실측: 세계사 p022 정밀도 0.954→0.518). 지도 설명은 캡셔닝 소관.
                    content = "이미지 캡셔닝 대기"
            else:
                content = item.get("content", "")
        elif mapped_type in ("image", "chart_graph", "cartoon"):
            content = "이미지 캡셔닝 대기"
        elif item_type == "list":
            content = "\n".join(item.get("list_items", []))
        else:
            content = item.get("text", "")

        # MinerU 첨자 마크업 정화(2026-07-19): 외국어 장식 타이포("Reaching beyond…"의
        # 글자 크기 변주)를 MinerU가 <sub>/<sup>로 도배 — 태그가 그대로 점역돼 페이지가
        # 폭주했다(외국어 p014: 6045셀 vs gold 1434, CER 201%). 태그만 벗기고 글자는 보존.
        # 진짜 수식 첨자는 interline_equation(LaTeX) 경로라 여기 영향 없다.
        if content and "<su" in content:
            content = re.sub(r"</?su[bp]>", "", content)

        # 글자는 PDF 텍스트 레이어 우선(하이브리드) — 티어와 무관하게 블록별로 시도한다.
        # TEXT_NATIVE(스캔 아님이 확실)면 가드 없이 대체, 그 외(OCR 라우팅)는 가드 통과 시만.
        if mapped_type in _NATIVE_TEXT_TYPES:
            if extraction_method == "TEXT_NATIVE":
                content = _native_text_spaced(fitz_page, bb) or content
            else:
                content = _native_override(fitz_page, bb, content) or content
        elif mapped_type == "table":
            # 표는 구조 때문에 전면 대체를 못 하므로 글머리 기호(제72항)만 되돌린다.
            content = _restore_table_bullets(fitz_page, bb, content)

        # 인쇄 캡션 강제 적용(위 forced_caption) — 생성 placeholder/빈 content를 덮어쓴다.
        if forced_caption and mapped_type == "caption":
            content = forced_caption

        # page_number인데 숫자가 아닌 경우 type을 text로 정정
        if mapped_type == "page_number" and not content.strip().lstrip('-').isnumeric():
            mapped_type = "text"

        # MinerU bbox는 0~1000 정규화 좌표 → 실제 픽셀로 변환
        bb_px = [bb[0] / 1000 * img_w, bb[1] / 1000 * img_h,
                 bb[2] / 1000 * img_w, bb[3] / 1000 * img_h]

        merged_layout.append({
            "element_id": element_id,
            "reading_order": order,
            "type": mapped_type,
            "bbox": bb,
            "bbox_px": bb_px,
            # 페이지 픽셀 크기(2x 렌더 기준) — bbox_px와 같은 좌표계. BE/FE가 bbox를
            # image_width/height에 대한 비율로 매핑할 수 있게 경계파일까지 흘려보낸다.
            "page_width": img_w,
            "page_height": img_h,
            "content": content,
            "image_path": image_path,
            "heading_level": None,
            "caption_ref": None,
            "flags": [],
        })
        order += 1

    doc.close()

    # 매핑 파일 업데이트 (다음 캐시 재실행에 대비)
    with open(mapping_file, "w", encoding="utf-8") as f:
        json.dump(hash_to_eid, f)

    if debug:
        layout_json = [
            {k: v for k, v in el.items() if k not in ("bbox_px", "content")}
            for el in merged_layout
        ]
        with open(base / "merged_layout.json", "w", encoding="utf-8") as f:
            json.dump(layout_json, f, ensure_ascii=False, indent=2)

    print(f"[mineru_runner] page {page_no}: {len(merged_layout)}개 요소, "
          f"이미지 {sum(1 for e in merged_layout if e.get('image_path'))}개")
    return merged_layout
