"""놓친 그림 회수 — 앞단이 시각 요소를 0개 낸 쪽만 비전 모델로 다시 본다.

**왜 필요한가.** 평가 실측(dev-2027 32쪽, LLM 켬):
    시각 요소를 잡은 쪽  6쪽 : 우리 3,786셀 / gold   995셀 = 381%
    시각 요소가 0인 쪽  26쪽 : 우리    25셀 / gold 3,411셀 =   1%
프롬프트·포장을 아무리 고쳐도 그 26쪽은 안 움직인다(상한 1%). 레버는 **검출**이다.

**규칙 기반으로는 안 됐다.** 캡션 신호 정밀 1/1·재현 1/6, 벡터 그림·임베디드 이미지를
합쳐도 3/6이었다. 그림이 벡터로 그려져 있거나 MinerU 레이아웃이 통째로 놓친다.

**비전 모델 실측**(우리가 놓쳤고 gold는 설명을 쓴 4쪽 / gold도 안 쓴 10쪽):
    재현 4/4 (100%) · 오검출 0/10 (opus) · 1/10 (sonnet)
처음에는 오검출이 7/10이었다 — 단원 번호 배지·문제 번호 그래픽 같은 **장식**을 그림으로 셌다.
"그 자료가 없으면 학생이 문제를 못 푸는가"를 기준으로 넣으니 0으로 떨어졌다.
"""
from __future__ import annotations

import base64
import json
import os
import re

from app.core.config import config
from app.utils.logger import get_logger

logger = get_logger(__name__)

MODEL = os.environ.get("FIGDET_MODEL", "claude-sonnet-5")
_DPI = 130
_MAX_FIGS = 8                      # 한 쪽에 이보다 많으면 장식을 센 것이다

# 유형 → 우리 요소 타입. 체인이 갈리므로 여기서 정한다.
_KIND_TYPE = {
    "그래프": "chart_graph", "도표": "chart_graph",
    "모식도": "diagram", "개념도": "diagram", "흐름도": "diagram",
    "만화": "cartoon",
    "사진": "image", "그림": "image", "지도": "image",
}

_ASK = """이 교과서 페이지에서 **시각자료**를 모두 찾아 주십시오.

시각자료 = 학생이 **문제를 풀거나 본문을 이해하는 데 쓰는** 그림·사진·그래프·모식도·도표·만화입니다.

다음은 **시각자료가 아닙니다. 절대 넣지 마십시오.**
- 단원 번호·문제 번호를 감싼 원·배지·색 블록 (예: 동그라미 안의 05, 굵은 01)
- 머리말 띠, 구분선, 모서리 장식, 아이콘, 로고
- 표(격자로 된 것)와 글상자(테두리 친 글) — 그건 글입니다
- 글자를 꾸민 것(밑줄·음영·강조 배경)

판단 기준: **그 자료가 없으면 학생이 문제를 못 푸는가?** 아니면 넣지 마십시오.
장식뿐인 페이지는 반드시 빈 목록을 내십시오.

각 자료마다 유형과 위치(페이지를 가로 0~100, 세로 0~100으로 봤을 때의 상자),
그리고 한 줄 요약을 적으십시오.

**JSON 하나만** 출력하십시오. 설명 금지.
{"figures":[{"kind":"그래프|모식도|사진|만화|지도|그림","x0":0,"y0":0,"x1":0,"y1":0,
 "what":"한 줄 요약"}]}"""


def enabled() -> bool:
    """켤 조건 — A/B(무-LLM) 실행과 키 없는 환경에서는 돌지 않는다."""
    if os.environ.get("DISABLE_LLM_FALLBACK") == "1":
        return False
    if os.environ.get("FIGURE_DETECT", "1") != "1":
        return False
    return bool(getattr(config, "anthropic_api_key", None))


def detect(pdf_data: bytes, page_no: int) -> list[dict]:
    """[{kind, x0..y1(0~100), what}] — 실패하면 빈 목록(본문은 나가야 한다)."""
    try:
        import anthropic
        import fitz

        from app.ai.preprocessor.pdf_analyzer import _coerce_pdf_bytes
        doc = fitz.open(stream=_coerce_pdf_bytes(pdf_data), filetype="pdf")
        try:
            page = doc[max(0, min(page_no - 1, doc.page_count - 1))]
            png = page.get_pixmap(dpi=_DPI).tobytes("png")
        finally:
            doc.close()
        client = anthropic.Anthropic(api_key=config.anthropic_api_key)
        m = client.messages.create(
            model=MODEL, max_tokens=2000,
            messages=[{"role": "user", "content": [
                {"type": "image", "source": {"type": "base64", "media_type": "image/png",
                                             "data": base64.standard_b64encode(png).decode()}},
                {"type": "text", "text": _ASK}]}])
        txt = "".join(b.text for b in m.content if b.type == "text")
        g = re.search(r"\{.*\}", txt, re.DOTALL)
        figs = (json.loads(g.group()) if g else {}).get("figures", []) if g else []
        return [f for f in figs if isinstance(f, dict)][:_MAX_FIGS]
    except Exception as exc:  # noqa: BLE001 — 회수는 있으면 좋은 것이다
        logger.warning("그림 검출 실패(없이 진행): %s", exc)
        return []


def to_elements(figs: list[dict], width: float, height: float, start_order: int) -> list[dict]:
    """검출 결과 → 경계 요소. bbox는 부르는 쪽 좌표계(width/height)로 환산한다."""
    from uuid import uuid4
    out: list[dict] = []
    for i, f in enumerate(sorted(figs, key=lambda x: float(x.get("y0") or 0))):
        what = (f.get("what") or "").strip()
        if not what:
            continue
        try:
            bb = [float(f["x0"]) / 100 * width, float(f["y0"]) / 100 * height,
                  float(f["x1"]) / 100 * width, float(f["y1"]) / 100 * height]
        except (KeyError, TypeError, ValueError):
            continue
        if bb[2] <= bb[0] or bb[3] <= bb[1]:
            continue
        out.append({
            "id": str(uuid4()), "order": start_order + i,
            "type": _KIND_TYPE.get((f.get("kind") or "").strip(), "image"),
            "content": what, "bbox": [int(round(v)) for v in bb],
            "flags": ["FIGURE_RECOVERED"],      # 회수분 표시 — 품질 추적용
        })
    return out
