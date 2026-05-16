"""PART 5-1 — PP-FormulaNet gRPC 수식 OCR — 단계 3 구현 예정.

formulanet-service (:50052) gRPC 호출 스켈레톤.
"""

from __future__ import annotations

import asyncio
import io
import logging
from typing import TYPE_CHECKING

from app.core.config import config
from app.schemas.content import ExtractedContent
from app.schemas.layout import BBoxItem

if TYPE_CHECKING:
    from PIL import Image as PILImage

logger = logging.getLogger(__name__)

# LaTeX 복잡도 임계값: S 모델 / L 모델 경계
_COMPLEXITY_THRESHOLD = 0.7

# 복잡도 높은 토큰 목록 (분수·적분·합·극한 등)
_COMPLEX_TOKENS = {
    r"\frac", r"\int", r"\sum", r"\prod", r"\lim",
    r"\sqrt", r"\binom", r"\matrix", r"\begin",
    r"\partial", r"\nabla", r"\infty",
}


def _latex_complexity(latex: str) -> float:
    """LaTeX 문자열 복잡도 점수 0~1 반환."""
    if not latex:
        return 0.0
    tokens = latex.split()
    if not tokens:
        return 0.0
    complex_count = sum(1 for t in tokens if any(c in t for c in _COMPLEX_TOKENS))
    return min(1.0, complex_count / max(len(tokens), 1) * 3.0)


def _validate_latex(latex: str) -> bool:
    """pylatexenc 기반 LaTeX 파싱 검증. 미설치 환경에서는 True 반환 (서버에서 설치됨)."""
    try:
        from pylatexenc.latexwalker import LatexWalker
        walker = LatexWalker(latex)
        walker.get_latex_nodes()[0]
        return True
    except ImportError:
        return True   # pylatexenc 미설치 → 검증 스킵
    except Exception:
        return False


def _crop_to_bytes(img: "PILImage.Image") -> bytes:
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _call_formulanet_sync(image_bytes: bytes, model_size: str) -> tuple[str, float]:
    """formulanet-service gRPC 동기 호출."""
    import grpc
    from protos.generated.formulanet_service_pb2 import RecognizeRequest
    from protos.generated.formulanet_service_pb2_grpc import FormulaNetServiceStub

    channel = grpc.insecure_channel(config.formulanet_service_addr)
    try:
        stub = FormulaNetServiceStub(channel)
        req = RecognizeRequest(image_bytes=image_bytes, model_size=model_size)
        resp = stub.Recognize(req, timeout=15.0)
        return resp.latex_string, resp.confidence
    finally:
        channel.close()


class FormulaOCR:
    """Worker B: 수식 이미지 → LaTeX 문자열."""

    async def process(
        self,
        element_crops: list[tuple[BBoxItem, "PILImage.Image"]],
    ) -> list[ExtractedContent]:
        tasks = [self._process_one(elem, crop) for elem, crop in element_crops]
        return await asyncio.gather(*tasks)

    async def _process_one(
        self,
        elem: BBoxItem,
        crop: "PILImage.Image",
    ) -> ExtractedContent:
        image_bytes = await asyncio.to_thread(_crop_to_bytes, crop)
        complexity = 0.5  # gRPC 호출 전 기본값

        try:
            # 1차 호출: S 모델 (빠름)
            latex, confidence = await asyncio.to_thread(
                _call_formulanet_sync, image_bytes, "S"
            )
            complexity = _latex_complexity(latex)

            # 복잡도 높으면 L 모델로 재호출
            if complexity > _COMPLEXITY_THRESHOLD:
                latex_l, conf_l = await asyncio.to_thread(
                    _call_formulanet_sync, image_bytes, "L"
                )
                if conf_l > confidence:
                    latex, confidence = latex_l, conf_l

            # LaTeX 검증
            if not _validate_latex(latex):
                logger.warning("LaTeX 검증 실패 id=%s latex=%.60s", elem.element_id, latex)
                return ExtractedContent(
                    element_id=elem.element_id,
                    corrected_text="[처리 불가: LaTeX 검증 실패 — 수식 재확인 필요]",
                    latex_string=latex,
                    ocr_confidence=confidence,
                    flags=["C3_FALLBACK"],
                )

            return ExtractedContent(
                element_id=elem.element_id,
                latex_string=latex,
                corrected_text=latex,
                ocr_confidence=confidence,
            )

        except Exception as exc:
            logger.error("FormulaOCR 예외 id=%s: %s", elem.element_id, exc)
            return ExtractedContent(
                element_id=elem.element_id,
                corrected_text="[처리 불가: 수식 OCR 오류]",
                ocr_confidence=0.0,
                flags=["C3_FALLBACK"],
            )
