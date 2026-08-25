"""회전 지면의 벡터 특징 검출 — #250.

get_drawings·rawdict 는 **회전 전(mediabox)** 좌표로 나오는데 page.rect 는 회전 후 크기다.
둘을 섞으면 회전 지면에서 글상자가 엉뚱한 자리로 정규화된다(180° 는 쪽 높이의 0.18 어긋남,
90°·270° 는 딴 자리). #228 이 extract_text_blocks 만 고쳐 형제 셋이 남아 있었다.
"""
from __future__ import annotations

import fitz
import pytest

from app.ai.preprocessor.pdf_analyzer import box_rects_norm

# 쪽 대비 비율로 놓은 글상자 하나 — 감쌀 글이 있어야 후보로 잡힌다.
_BOX = (0.10, 0.20, 0.90, 0.70)   # 돌려도 폭 하한(_BOX_MIN_W)을 넘도록 넉넉히


def _page(rotation: int) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    r = fitz.Rect(_BOX[0] * 595, _BOX[1] * 842, _BOX[2] * 595, _BOX[3] * 842)
    page.draw_rect(r, color=(0, 0, 0), width=1.0)
    page.insert_textbox(r + (4, 4, -4, -4), "보기 상자 안의 글", fontname="korea", fontsize=13)
    if rotation:
        page.set_rotation(rotation)
    data = doc.tobytes()
    doc.close()
    return data


def _truth(data: bytes) -> list[float]:
    """표시 좌표로 옮긴 진짜 자리(쪽 비율)."""
    doc = fitz.open(stream=data, filetype="pdf")
    page = doc[0]
    w, h = page.rect.width, page.rect.height
    r = fitz.Rect(_BOX[0] * 595, _BOX[1] * 842, _BOX[2] * 595, _BOX[3] * 842) * page.rotation_matrix
    r.normalize()
    doc.close()
    return [r.x0 / w, r.y0 / h, r.x1 / w, r.y1 / h]


@pytest.mark.parametrize("rotation", [0, 90, 180, 270])
def test_회전해도_글상자가_제자리에_잡힌다(rotation: int) -> None:
    data = _page(rotation)
    got = box_rects_norm(data, 1)
    assert got, f"{rotation}°에서 글상자를 못 잡았다"
    frac = [v / 1000 for v in got[0]]
    assert max(abs(a - b) for a, b in zip(frac, _truth(data))) < 0.01, (
        f"{rotation}°: 우리 {frac} vs 진짜 {_truth(data)}")


def test_회전_없는_쪽은_동작이_그대로다() -> None:
    """회전 0°면 rotation_matrix 가 항등이라 값이 바뀌면 안 된다(A4 회귀 가드)."""
    frac = [v / 1000 for v in box_rects_norm(_page(0), 1)[0]]
    assert max(abs(a - b) for a, b in zip(frac, _BOX)) < 0.01
