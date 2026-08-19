"""
merged_layout + 캡셔닝 결과를 읽기 순서대로 병합하여
001_txt_result.json 생성.
debug=True 시 최종 order 기준 layout_viz.jpg를 test/results/page_{no:03d}/에 저장.
"""
import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import fitz
from PIL import Image, ImageDraw, ImageFont

from app.ai.captioning.captioner import caption, log_backend_status
from app.ai.captioning.classifier import classify_with_confidence
from app.ai.llm.diagram_structure import subtype_from_caption
from app.utils.logger import get_logger

logger = get_logger(__name__)

_VISUAL_TYPES = {"image", "cartoon", "chart_graph"}
_HF_TYPES = {"header_footer", "page_number"}
_TOP_Y_MAX = 200   # 0~1000 정규화 좌표 기준 상단 헤더 경계

VIZ_COLORS = {
    "title":         (220, 50,  50),
    "text":          (50,  120, 220),
    "formula":       (50,  180, 50),
    "table":         (220, 140, 50),
    "image":         (50,  200, 200),
    "chart":         (200, 100, 200),
    "caption":       (180, 100, 20),
    "list_item":     (180, 50,  180),
    "footnote":      (120, 120, 120),
    "header_footer": (80,  80,  160),
    "page_number":   (160, 160, 80),
}
DEFAULT_COLOR = (100, 100, 100)


def _reorder(elements: list[dict]) -> list[dict]:
    """
    header_footer/page_number를 상단/하단으로 분리.
    - y < _TOP_Y_MAX  → 맨 앞 (y 오름차순)
    - body            → MinerU 읽기 순서 유지
    - y >= _TOP_Y_MAX → 맨 뒤 (y 오름차순)
    """
    top, body, bottom = [], [], []
    for el in elements:
        if el["type"] in _HF_TYPES:
            y1 = el["bbox"][1]
            if y1 < _TOP_Y_MAX:
                top.append(el)
            else:
                bottom.append(el)
        else:
            body.append(el)

    top.sort(key=lambda e: e["bbox"][1])
    bottom.sort(key=lambda e: e["bbox"][1])
    return top + body + bottom


_CLASSIFY_TYPE_MAP = {
    "cartoon": "cartoon",
    "chart": "chart_graph",
    "image": "image",
    # 'diagram'은 pipeline._TYPE_ALIAS에 이미 있고 _run_diagram_chain이 받는다(§6.6 도표 골격).
    # 하위유형(개념도/흐름도/…)을 모르면 diagram_opt가 공통 3안으로 안전 폴백한다.
    "diagram": "diagram",
}


# API 일시 장애(쿼터·타임아웃·네트워크)는 재시도. 그 외(인증·잘못된 이미지)는 즉시 포기.
_TRANSIENT_EXC = {"RateLimitError", "APITimeoutError", "APIConnectionError", "InternalServerError"}
_CAPTION_RETRIES = 2
_CAPTION_BACKOFF = 1.5   # 초, 지수 증가

# ── 실행 단위 캡셔닝 중단 (2026-08-12) ───────────────────────────────────────
# 캡셔닝 실패는 **그림마다 따로 나지 않는다. 실행 통째로 난다.** 전 job 실측:
# 시각요소 11,483개 중 6,892개(60.0%)가 CAPTION_FAILED인데, job별로 보면
# **실패율 100%인 job 152개 · 0%인 job 215개**로 완전히 갈린다. 중간이 거의 없다.
# 원인은 그림이 아니라 API 접근이다.
#
# ★ 정정(2026-08-12) — 처음엔 이 자리에 "OpenAI(api_key=None)이 생성자에서 터진다"고
#   적었는데 **틀렸다.** 캡셔닝 기본 백엔드는 OpenAI가 아니라 anthropic이다
#   (`captioner.py`·`classifier.py`의 `os.getenv("CAPTION_BACKEND", "anthropic")`,
#   모델 기본값 `claude-sonnet-5`). GPT-4o는 CAPTION_BACKEND를 다른 값으로 줬을 때만 탄다.
#
# 실제 실패 모양은 이렇다(실측):
#   · 키 없음 → anthropic 클라이언트 **생성자는 통과**하고, 첫 호출에서
#     `TypeError: Could not resolve authentication method…`가 난다.
#     예외 이름만 보면 코드 버그와 구분이 안 되므로 **메시지로 가른다**.
#   · 키가 틀림/권한 없음 → `AuthenticationError` · `PermissionDeniedError`
#     (두 SDK가 같은 이름을 쓴다 — anthropic·openai 모두 있다)
#
# 이런 설정성 오류는 다시 해도 결과가 같다. 한 번 만나면 프로세스 단위로 잠그고, 이유를
# 경계 파일 플래그에 실어 보낸다. 종전에는 요소마다 클라이언트를 다시 만들어 같은 예외를
# 다시 맞았고(200요소 페이지면 200번), 그 이유는 **로그에만** 남는데 파일 핸들러가 없어
# 실행이 끝나면 증발했다 — "왜 캡셔닝이 실패하나"를 사후에 알 수가 없던 진짜 이유다.
_FATAL_EXC = {"AnthropicError", "OpenAIError",          # 각 SDK의 기반 예외
              "AuthenticationError", "PermissionDeniedError", "NotFoundError"}
# 이름만으로는 못 가르는 것 — 인증 미해결 TypeError. 메시지로 판별한다.
_FATAL_MSG_RE = re.compile(r"resolve authentication|api[_ ]?key|auth_token", re.I)
_backend_logged = False                # 백엔드·키 상태 1회 로깅 여부
_caption_fatal: str | None = None      # 잠긴 사유(예: "AuthenticationError: …")


def _is_fatal(exc: Exception) -> bool:
    """다시 해도 같은 결과인 설정성 오류인가(키·인증·권한)."""
    name = type(exc).__name__
    if name in _FATAL_EXC:
        return True
    # TypeError는 코드 버그일 수도 있다 — 인증 문구가 있을 때만 설정 오류로 본다.
    return isinstance(exc, TypeError) and bool(_FATAL_MSG_RE.search(str(exc)))


def caption_fatal_reason() -> str | None:
    """이번 프로세스에서 캡셔닝이 통째로 막힌 사유(없으면 None). 보고·진단용."""
    return _caption_fatal


def reset_caption_fatal() -> None:
    """테스트·재시도용 — 잠금 해제."""
    global _caption_fatal
    _caption_fatal = None


def _do_caption(el: dict) -> tuple[str, str, bool, float | None]:
    """(캡션, 확정 타입, 성공여부, 세분류 신뢰도).

    ★ 실패 문자열을 본문으로 흘리지 않는다. 예전에는 "[캡셔닝 실패]"를 content로 반환해
    그 다섯 글자가 그대로 점자로 찍혀 학생에게 나갔다(품질검사도 못 잡아 COMPLETED 처리).
    실패는 빈 캡션 + 성공여부 False로만 알리고, 하위 opt가 규정상 '생략' 표기(§6.3.4(2)②)를
    내며 품질검사가 R11로 점역사에게 띄운다.
    세분류 신뢰도(logprob 기반)는 경계 JSON의 subtype_confidence로 나가 R2 판정에 쓰인다.
    """
    global _caption_fatal
    img_path = el.get("image_path")
    original_type = el.get("type", "image")
    eid = str(el.get("element_id", ""))[:8]

    # 오프라인 차단 스위치 — base_opt와 같은 플래그를 캡셔닝도 본다(2026-08-16).
    # 종전엔 이 가드가 없어 무-LLM 실행에서도 캡셔너가 API를 두드렸다. 키가 비어 있으면
    # SDK가 "Could not resolve authentication method…" **TypeError**를 던지고, 그게
    # _is_fatal에 걸려 실행이 잠긴다. 결과는 설계대로(빈 캡션 + CAPTION_FAILED)지만
    # 로그에 `CAPTION_ERR:TypeError`가 남아 **"캡셔닝이 100% 죽었다"로 읽힌다** —
    # 실제로 그 오독으로 두 세션이 몇 시간을 썼다(2026-08-16). 조용히 건너뛴다.
    if os.environ.get("DISABLE_LLM_FALLBACK") == "1":
        logger.debug("캡셔닝 건너뜀(DISABLE_LLM_FALLBACK=1) id=%s", eid)
        return "", original_type, False, None

    # 설정성 오류로 이미 잠겼으면 API를 다시 두드리지 않는다 — 같은 실패를 요소 수만큼
    # 반복해 봐야 시간만 버린다(200요소 페이지면 재시도 포함 600회).
    if _caption_fatal:
        return "", original_type, False, None

    if not img_path or not Path(img_path).exists():
        logger.warning("캡셔닝 불가 — 이미지 경로 없음 id=%s path=%r", eid, img_path)
        return "", original_type, False, None

    last: Exception | None = None
    for attempt in range(_CAPTION_RETRIES + 1):
        try:
            image_type, subconf = classify_with_confidence(img_path)
            mapped_type = _CLASSIFY_TYPE_MAP.get(image_type, "image")
            text = caption(img_path, image_type)
            # ★ 예외 없이 **빈 캡션**이 오는 길이 있다(모델이 거부하거나 빈 응답을 줌).
            #   그걸 성공으로 넘기면 build()의 `not content.strip()` 가지에서 요소가
            #   통째로 사라진다 — 실측: job_260807160446 p1의 만화가 이렇게 없어졌고
            #   (로그 "캡셔닝 56780743(image→cartoon) 12.5s", 실패 표시 없음),
            #   그 뒤 그림 회수가 같은 그림을 다시 찾아 LLM을 한 번 더 썼다.
            #   빈 응답은 성공이 아니다. 실패로 돌려 요소를 살린다(불변규칙 1).
            if not text.strip():
                logger.error("캡셔닝 빈 응답 id=%s type=%s — 요소는 살린다", eid, image_type)
                return "", mapped_type, False, subconf
            return text, mapped_type, True, subconf
        except Exception as exc:  # noqa: BLE001 — 요소 격리(불변규칙 3)
            last = exc
            name = type(exc).__name__
            if _is_fatal(exc):
                # 키·인증·엔드포인트 문제 — 다시 해도 같다. 실행 단위로 잠근다.
                _caption_fatal = f"{name}: {exc}"
                logger.error("캡셔닝 전면 중단 — %s. 이번 실행의 남은 시각요소는 "
                             "API를 부르지 않고 '생략'으로 나간다.", _caption_fatal)
                break
            if name not in _TRANSIENT_EXC or attempt == _CAPTION_RETRIES:
                break
            time.sleep(_CAPTION_BACKOFF * (2 ** attempt))

    # 삼키지 않는다 — 원인(쿼터 소진·인증 실패 등)이 로그에 남아야 운영에서 추적된다.
    logger.error("캡셔닝 실패 id=%s: %s: %s", eid, type(last).__name__, last)
    return "", original_type, False, None


def _render_page(pdf_path: str, page_no: int) -> Image.Image:
    doc = fitz.open(str(pdf_path))
    # pdf_data는 단일 페이지 PDF(proto 계약). page_no는 원본 페이지 번호이므로
    # 페이지 수에 맞게 클램프(단일=0, 멀티=page_no-1) — 범위 초과 방지.
    page_idx = max(0, min(page_no - 1, doc.page_count - 1))
    pix = doc[page_idx].get_pixmap(matrix=fitz.Matrix(2, 2))
    img = Image.frombytes("RGB", [pix.width, pix.height], pix.samples)
    doc.close()
    return img


def _viz_page(page_img: Image.Image, elements: list[dict]) -> Image.Image:
    img = page_img.copy().convert("RGB")
    draw = ImageDraw.Draw(img, "RGBA")
    try:
        font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 13)
    except Exception:
        font = ImageFont.load_default()

    for el in elements:
        bb = el.get("bbox_px", el["bbox"])
        color = VIZ_COLORS.get(el["type"], DEFAULT_COLOR)
        draw.rectangle(bb, fill=(*color, 35), outline=(*color, 200), width=2)
        lbl = f"{el['final_order']} {el['type']}"[:14]
        tx, ty = bb[0] + 2, max(0, bb[1] - 15)
        draw.rectangle([tx - 1, ty - 1, tx + len(lbl) * 7 + 2, ty + 14], fill=(*color, 170))
        draw.text((tx, ty), lbl, fill=(255, 255, 255), font=font)
    return img


_TEXTUAL_TYPES = {"text", "title", "list_item", "caption", "footnote", "sidebar"}
# 문항 번호는 큰 글씨/색 상자로 조판돼 있어 MinerU가 **앞 문항 본문 끝**에 붙여 내보낸다
# ("…고른 것은?\n02"). 그대로 두면 번호가 엉뚱한 문항에 붙어 점역된다 → 다음 텍스트 요소 앞으로
# 옮긴다(정답 배치 = "02. 다음은…"). dev 18p에서 14건.
_TRAILING_QNUM_RE = re.compile(r"\n\s*(\d{1,2})\s*$")


def _move_trailing_qnum(ordered: list[dict]) -> None:
    """앞 요소 끝에 붙은 다음 문항 번호를 다음 텍스트 요소 앞으로 옮긴다(제자리 수정)."""
    for i, el in enumerate(ordered[:-1]):
        if el.get("type") not in _TEXTUAL_TYPES:
            continue
        text = (el.get("content") or "").rstrip()
        m = _TRAILING_QNUM_RE.search(text)
        if not m or len(text) < 10:
            continue
        nxt = ordered[i + 1]
        if nxt.get("type") not in _TEXTUAL_TYPES:
            continue
        el["content"] = text[: m.start()].rstrip()
        nxt["content"] = f"{m.group(1)}\n{(nxt.get('content') or '').lstrip()}"


_CAPTIONABLE = _VISUAL_TYPES | {"table"}   # 캡션이 가리킬 수 있는 시각요소


def _link_captions(elements: list[dict]) -> None:
    """caption 요소 → 가장 가까운 시각요소(그림/표/차트)에 caption_ref 연결(공간 근접).

    캡션은 보통 대상 그림/표 바로 아래·위에 붙는다. bbox 세로 중심 거리가 가장 가까운
    시각요소를 대상으로 본다. bbox 없거나 시각요소 없으면 빈 값 유지.
    """
    visuals = [e for e in elements if e["type"] in _CAPTIONABLE and e.get("bbox")]
    if not visuals:
        return
    for cap in elements:
        if cap["type"] != "caption" or not cap.get("bbox"):
            continue
        cb = cap["bbox"]
        cy = (cb[1] + cb[3]) / 2
        best, best_d = None, float("inf")
        for v in visuals:
            vb = v["bbox"]
            d = abs(cy - (vb[1] + vb[3]) / 2)
            if d < best_d:
                best, best_d = v, d
        if best:
            cap["caption_ref"] = best["id"]


def _caption_all(ordered: list[dict]) -> dict[int, tuple]:
    """시각요소 캡셔닝을 **동시에** 수행한다. 키 = id(el).

    종전에는 `for el in ordered:` 안에서 한 장씩 순서대로 호출해, 시각요소 개수에
    소요 시간이 정비례했다(실측 8.86초/개 — 그림 11개 페이지에서 캡셔닝만 97.5초).
    캡셔닝은 외부 API 호출이라 GPU를 쓰지 않으므로 동시에 던져도 서로 막지 않는다.

    동시 요청 수는 `CAPTION_CONCURRENCY`(기본 4)로 제한한다 — 무제한으로 던지면
    외부 API 요청 한도(429)에 걸려 오히려 느려진다.
    """
    vis = [el for el in ordered if el["type"] in _VISUAL_TYPES]
    if not vis:
        return {}
    # 백엔드·키 상태를 프로세스당 1회 남긴다 — 키가 없으면 여기서 error로 뜬다.
    # (종전엔 실패가 요소별 로그로만 흘러 실행이 끝나면 원인이 사라졌다.)
    global _backend_logged
    if not _backend_logged:
        _backend_logged = True
        log_backend_status()
    workers = max(1, int(os.environ.get("CAPTION_CONCURRENCY", "4")))
    t0 = time.monotonic()
    out: dict[int, tuple] = {}
    if len(vis) == 1 or workers == 1:
        for el in vis:
            out[id(el)] = _do_caption_logged(el)
    else:
        with ThreadPoolExecutor(max_workers=min(workers, len(vis))) as pool:
            futs = {pool.submit(_do_caption_logged, el): el for el in vis}
            for fut in as_completed(futs):
                el = futs[fut]
                try:
                    out[id(el)] = fut.result()
                except Exception as exc:  # noqa: BLE001 — 요소 격리(불변규칙 3)
                    logger.warning("    캡셔닝 예외 %s: %s", str(el.get("element_id", ""))[:8], exc)
                    out[id(el)] = ("", el["type"], False, None)
    logger.info("  캡셔닝 %d개 동시 %d — %.1fs", len(vis), workers, time.monotonic() - t0)
    return out


def _do_caption_logged(el: dict) -> tuple:
    """`_do_caption` + 요소별 소요시간 로깅.

    프로세스 전역 슬롯을 잡고 호출한다 — 페이지 안 스레드풀(기본 4)만으로는 페이지가
    여러 개 동시에 돌 때 곱해져서 외부 API 한도(429)에 걸린다. 소요시간은 슬롯을 잡은
    뒤부터 잰다(대기를 캡셔닝 시간으로 계상하면 로그가 원인을 가린다).
    """
    from app.core.limits import caption_slot

    with caption_slot():
        t = time.monotonic()
        content, el_type, ok, subconf = _do_caption(el)
        logger.info("    캡셔닝 %s(%s→%s) %.1fs%s", str(el.get("element_id", ""))[:8],
                    el["type"], el_type, time.monotonic() - t, "" if ok else " [실패]")
    return content, el_type, ok, subconf


def build(
    merged_layout: list[dict],
    job_id: str,
    page_no: int,
    extraction_method: str,
    debug: bool = False,
    pdf_path: str | None = None,
) -> dict:
    """
    merged_layout: mineru_runner.run() 반환값 (bbox_px 포함)
    반환: 001_txt_result.json 내용 (dict)
    """
    ordered = _reorder(list(merged_layout))
    _move_trailing_qnum(ordered)

    cap_results = _caption_all(ordered)

    elements = []
    order = 1
    for el in ordered:
        caption_failed = False
        subconf: float | None = None
        if el["type"] in _VISUAL_TYPES:
            content, el_type, ok, subconf = cap_results[id(el)]
            caption_failed = not ok
        else:
            content = el.get("content", "")
            el_type = el["type"]

        # ★ 캡셔닝이 실패한 시각요소는 버리지 않는다. 요소째 사라지면 학생은 거기 그림이
        # 있었다는 사실조차 모른다(불변규칙 1 빈 결과 금지). 빈 캡션 + CAPTION_FAILED로
        # 넘기면 opt가 '생략' 표기를 내고 품질검사가 R11로 점역사에게 띄운다.
        if not content.strip() and not caption_failed:
            continue

        # element_id를 그대로 사용 (새 UUID 생성 안 함)
        # ★경계 bbox는 0~1000 정규화로 통일(2026-07-19). 구판이 rect×2 픽셀(bbox_px)을
        #   "bbox"로 저장해, 0~1000을 가정하는 소비처(수식 crop·opus_extract·caption 링크)가
        #   전부 어긋났다 — 수학2 p008 실측: 원본 y=556이 820으로 저장돼 crop이 다른 수식을
        #   가리킴. MinerU 경로(bbox_px 존재)는 원본 정규화 bbox를 쓰고, 그 외 경로는 종전 유지.
        if el.get("bbox_px") and el.get("bbox"):
            bbox_out = el["bbox"]                    # 0~1000 원본
        else:
            bbox_out = el.get("bbox_px") or el.get("bbox")
        entry = {
            "id": el["element_id"],
            "order": order,
            "type": el_type,
            "content": content,
            "bbox": [int(round(v)) for v in bbox_out] if bbox_out else None,
            "caption_ref": "",   # 아래 _link_captions가 채움
            # CAPTION_FAILED는 quality_checker가 R11로 올리는 정확한 키다(문자열 변경 금지).
            # 사유는 **별도 플래그**로 붙여 사후에 원인을 알 수 있게 한다.
            "flags": (["CAPTION_FAILED"] + ([f"CAPTION_ERR:{_caption_fatal.split(':', 1)[0]}"]
                                            if _caption_fatal else [])) if caption_failed else [],
        }
        # 제목 단계(BBPG 2장2절1) — 여기서 안 실으면 조판이 가운데 정렬·들여쓰기를 못 쓴다.
        # mineru_runner가 MinerU의 text_level을 걸러 넣어 준다.
        if el.get("heading_level"):
            entry["heading_level"] = el["heading_level"]
        if subconf is not None:
            entry["subtype_confidence"] = subconf
        # 도표 세분류(§6.6 8종) — 분류기는 'diagram' 넉 자까지만 낸다. 캡션 첫 줄이 유형어를
        # 달고 오므로(캡셔너 diagram 프롬프트) 거기서 읽어 경계 JSON에 싣는다. 이 칸이
        # 비어 있어서 pipeline._parse_txt_result → diagram_opt._ASSEMBLERS가 한 번도 안 돌았다.
        if el_type == "diagram":
            vsub = subtype_from_caption(content)
            if vsub:
                entry["visual_subtype"] = vsub
        elements.append(entry)

        if debug:
            el["final_order"] = order  # viz용 임시 필드

        order += 1

    _link_captions(elements)

    # 페이지 크기(2x 렌더 픽셀) — 요소들이 공유. bbox와 같은 좌표계로 BE/FE 매핑용.
    page_w = next((el.get("page_width") for el in ordered if el.get("page_width")), 0)
    page_h = next((el.get("page_height") for el in ordered if el.get("page_height")), 0)

    if debug and pdf_path:
        debug_dir = Path("storage") / "jobs" / job_id / "temp" / f"page_{page_no:03d}"
        debug_dir.mkdir(parents=True, exist_ok=True)
        page_img = _render_page(pdf_path, page_no)
        viz = _viz_page(page_img, ordered)
        viz.save(debug_dir / "layout_viz.jpg", quality=90)

    result = {
        "meta": {
            "job_id": job_id,
            "page_no": page_no,
            "extraction_method": extraction_method,
            "image_width": page_w,
            "image_height": page_h,
        },
        "elements": elements,
    }

    out_path = (
        Path("storage") / "jobs" / job_id / "temp"
        / f"page_{page_no:03d}" / "data" / f"{page_no:03d}_txt_result.json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(result, f, ensure_ascii=False, indent=2)

    print(f"[result_builder] {out_path} 저장 ({len(elements)}개 요소)")
    return result
