"""캡셔닝용 크롭을 원본 PDF에서 고DPI로 다시 자르는 경로(2026-08-10).

지키는 것 둘:
  1. **자리가 맞는가** — 0~1000 정규화 bbox를 페이지 pt로 옮겨 자른 결과가
     MinerU 크롭(200DPI 기준)과 같은 자리·같은 비율이어야 한다. 좌표계를 섞으면
     엉뚱한 자리를 잘라 캡션이 통째로 다른 그림을 설명한다.
  2. **스캔 쪽에서는 안 올린다** — 이미 렌더된 화소를 늘리는 것은 해롭다는 게
     실측이다(3배 업스케일 사실오류 35.0%→44.5%). 래스터 원본 해상도가 상한이다.
"""
from __future__ import annotations

import fitz
import pytest

from app.ai.parser.mineru_runner import _raster_dpi_cap, _recrop_hidpi

_BBOX = [250, 200, 750, 600]        # 0~1000 정규화 — 페이지 가운데 큰 사각형


@pytest.fixture()
def vector_page(tmp_path):
    doc = fitz.open()
    page = doc.new_page(width=600, height=800)
    page.draw_rect(fitz.Rect(150, 160, 450, 480), color=(0, 0, 0), width=1)
    page.insert_text((160, 200), "AB", fontsize=6)
    yield page
    doc.close()


def test_잘린_자리가_bbox와_같다(vector_page, tmp_path):
    dst = tmp_path / "c.jpg"
    assert _recrop_hidpi(vector_page, _BBOX, str(dst), [])
    r = vector_page.rect
    pm = fitz.Pixmap(str(dst))
    want = ((_BBOX[2] - _BBOX[0]) / 1000 * r.width) / ((_BBOX[3] - _BBOX[1]) / 1000 * r.height)
    assert pm.width / pm.height == pytest.approx(want, rel=0.02)   # 가로세로비 보존


def test_MinerU_크롭보다_화소가_많다(vector_page, tmp_path):
    dst = tmp_path / "c.jpg"
    _recrop_hidpi(vector_page, _BBOX, str(dst), [])
    pm = fitz.Pixmap(str(dst))
    r = vector_page.rect
    mineru_w = (_BBOX[2] - _BBOX[0]) / 1000 * r.width / 72 * 200   # MinerU는 200DPI
    assert pm.width > mineru_w * 1.4


def test_긴변은_1568을_넘지_않는다(vector_page, tmp_path):
    # _BBOX는 320pt 세로 — 600DPI로 그대로 렌더하면 2667px라 API가 되레 줄인다.
    dst = tmp_path / "c.jpg"
    assert _recrop_hidpi(vector_page, _BBOX, str(dst), [])
    pm = fitz.Pixmap(str(dst))
    assert max(pm.width, pm.height) <= 1568

def test_통짜_한_쪽은_이득이_없어_건너뛴다(vector_page, tmp_path):
    # 페이지 전체(800pt)는 1568px 상한 때문에 141DPI밖에 못 준다 — MinerU 200DPI만 못하다.
    assert _recrop_hidpi(vector_page, [0, 0, 1000, 1000], str(tmp_path / "c.jpg"), []) is False


def test_스캔쪽은_원본_해상도_위로_안_올린다(vector_page, tmp_path):
    # 페이지 전체를 덮는 150DPI 래스터 한 장 = 스캔 쪽. 200DPI 미만이라 재크롭을 포기한다.
    r = vector_page.rect
    scan = [{"bbox": tuple(r), "width": int(r.width / 72 * 150), "height": int(r.height / 72 * 150)}]
    assert _raster_dpi_cap(fitz.Rect(0, 0, r.width, r.height), scan) == pytest.approx(150, rel=0.01)
    assert _recrop_hidpi(vector_page, _BBOX, str(tmp_path / "c.jpg"), scan) is False
    assert not (tmp_path / "c.jpg").exists()      # 원본 MinerU 크롭이 그대로 남아야 한다


def test_벡터면_상한이_없다():
    assert _raster_dpi_cap(fitz.Rect(0, 0, 100, 100), []) == float("inf")


def test_빈_bbox는_건너뛴다(vector_page, tmp_path):
    assert _recrop_hidpi(vector_page, [500, 500, 500, 500], str(tmp_path / "c.jpg"), []) is False
