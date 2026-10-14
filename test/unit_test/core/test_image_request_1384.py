"""쪽 이미지(image_data, V4 정본 8)만 온 요청을 한 쪽 PDF 로 감싸 mode a 로 돌린다(이슈 #1384).

종전엔 `from_proto` 가 `pdf_data` 만 옮겨 이미지 한 장만 오면 C1 "도착 데이터 길이 0" 으로 막혔다.
소비처가 전부 `pdf_data` 를 렌더하므로 감싸기만 한다. 텍스트 층이 없으니 스캔 쪽 길을 탄다.
같이 고친 것: 환각 검사(#1078)가 빈 층과 맞대면 영어 · 로마자 표기 낱말이 전부 R4 가 됐다.
"""
from __future__ import annotations

import asyncio
from io import BytesIO
from unittest.mock import MagicMock

import fitz
import pytest
from PIL import Image

from app.ai.parser import mineru_runner as M
from app.core import grpc_server
from app.schemas.task import PageTask
from protos.generated import braille_service_pb2 as pb


def _image(w: int, h: int, fmt: str = "PNG", orientation: int = 0) -> bytes:
    img = Image.new("RGB", (w, h), "white")
    buf = BytesIO()
    if orientation:
        exif = Image.Exif()
        exif[0x0112] = orientation          # EXIF Orientation
        img.save(buf, fmt, exif=exif)
    else:
        img.save(buf, fmt)
    return buf.getvalue()


def _page(task: PageTask) -> fitz.Page:
    doc = fitz.open(stream=task.pdf_data, filetype="pdf")
    assert len(doc) == 1
    return doc[0]


def test_이미지만_오면_한_쪽_PDF_로_감싼다():
    """200 DPI 로 적으므로 쪽 크기(pt)는 픽셀 × 72/200 이다. 텍스트 층이 없고 스캔 쪽으로 판정된다."""
    task = PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="a",
                                                 image_data=_image(400, 300), image_mime_type="image/png"))
    assert task.pdf_data[:5] == b"%PDF-"
    page = _page(task)
    assert (round(page.rect.width, 1), round(page.rect.height, 1)) == (144.0, 108.0)
    assert page.get_text().strip() == ""
    assert M._is_scanned_page(page)


def test_사진_방향을_바로잡는다():
    """EXIF Orientation 6(시계 방향 90도로 돌려 보기) — 가로 300 · 세로 200 사진은 세로로 선 쪽이 된다."""
    task = PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="a",
                                                 image_data=_image(300, 200, "JPEG", orientation=6)))
    page = _page(task)
    assert (round(page.rect.width, 1), round(page.rect.height, 1)) == (72.0, 108.0)


def test_PDF_가_오면_PDF_를_쓰고_둘_다_없으면_빈_값이다():
    pdf = fitz.open()
    pdf.new_page()
    data = pdf.tobytes()
    both = PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="a", pdf_data=data,
                                                 image_data=_image(10, 10)))
    assert both.pdf_data == data
    assert PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="b", text_data="가")).pdf_data == b""


def test_못_푸는_이미지는_요청_파싱_실패로_답한다():
    with pytest.raises(Exception):
        PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="a", image_data=b"not an image"))
    resp = asyncio.run(grpc_server.BrailleServiceServicer()._process_page(
        pb.BrailleRequest(job_id="j", page_no=1, mode="a", image_data=b"not an image"), MagicMock()))
    assert "요청 파싱 실패" in str(resp)


def test_빈_층이면_로마자_낱말만_안_맞댄다():
    """층이 비면 영어 · 로마자 표기가 전부 '층에 없음'이다(그 요소엔 R13 이 따로 붙는다).
    한자 · 되풀이는 층 없이도 본다. 이미지 길 OCR 이 자모를 한자로 읽는다(언매 p0022 실측 `ㅅ → 人`).
    층이 있으면 종전대로 셋 다 가른다."""
    page = _page(PageTask.from_proto(pb.BrailleRequest(job_id="j", page_no=1, mode="a", image_data=_image(400, 300))))
    empty = lambda: M._page_layer_norm(page)            # noqa: E731 — 이미지 쪽의 실제 층
    assert M._halluc_signs("Baengma Silla camera", empty) == []
    assert M._halluc_signs("Photosynthesis 人 乚", empty) == ["乚", "人"]
    assert M._halluc_signs("ortion ortion ortion ortion ortion", empty)                # 되풀이는 남는다
    assert M._halluc_struct_signs("<td>Glucose</td><td>卄</td>", "table", empty) == ["卄"]
    assert M._halluc_struct_signs(r"\text{糖}", "formula", empty) == ["糖"]
    assert M._halluc_signs("Photosynthesis 人", "가나다") == ["Photosynthesis", "人"]
