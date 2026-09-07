"""스캔본 위에 얹힌 남의 OCR 텍스트 레이어를 MinerU 결과 위에 덮어쓰지 않는다.

결함 G(2026-09-08) — `정답해설.pdf` 는 지면 전체가 스캔 이미지고 그 위에 다른 도구가 만든
OCR 레이어가 얹혀 있다. 그 OCR 이 `h(s)` 를 `》(s)` 로, `f` 를 `乃`·`九` 로 잘못 읽었는데
`_native_override` 가 MinerU 의 올바른 결과를 그 글자로 덮어써서 점역 앞에서 이미 깨졌다.
PUA 0% · 글자가 전부 정상 한자라 종전 `_layer_untrustworthy` 신호에는 안 걸린다.
"""
import sys
from pathlib import Path

import fitz

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.parser.mineru_runner import (  # noqa: E402
    _is_scanned_page, _layer_untrustworthy, _native_override,
)

_GARBLED = "(iv)》(s)=4인 경우 : lim》(Z)=4이므로"   # 남의 OCR 이 낸 글자
_GOOD = "(iv) h(s)=4 인 경우: lim h(t)=4 이므로"     # MinerU 가 낸 글자


def _page(scanned: bool) -> fitz.Page:
    doc = fitz.open()
    page = doc.new_page(width=595, height=842)
    page.insert_text((60, 100), _GARBLED, fontname="china-s", fontsize=11)
    if scanned:
        # 지면 전체를 덮는 이미지 한 장 = 스캔본
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, 60, 85))
        pix.clear_with(255)
        page.insert_image(page.rect, pixmap=pix)
    return page


def test_full_page_image_is_a_scan():
    assert _is_scanned_page(_page(True)) is True
    assert _is_scanned_page(_page(False)) is False


def test_scan_layer_is_untrustworthy_even_though_glyphs_look_normal():
    """한자·CJK 부호뿐이라 글리프 신호로는 못 잡는다 — 스캔 신호가 잡아야 한다."""
    assert _layer_untrustworthy(_GARBLED) is False          # 종전 신호로는 통과한다
    assert _layer_untrustworthy(_GARBLED, _page(True)) is True


def test_native_override_keeps_mineru_text_on_a_scan():
    bbox = [0, 0, 1000, 1000]        # 0~1000 정규화(요소 전체)
    assert _native_override(_page(True), bbox, _GOOD) is None   # MinerU 결과 유지


def test_scan_check_is_not_cached_on_the_page_object():
    """`fitz.Page`를 키로 캐시하면 안 된다 — 파이썬 기본 해시는 객체 id다.

    Page가 수거된 뒤 같은 주소에 다른 Page가 앉으면 캐시가 엉뚱한 답을 주고, 비스캔 쪽이
    스캔으로(또는 그 반대로) 판정돼 텍스트레이어 우선이 조용히 뒤집힌다. `get_image_info()`는
    같은 호출부의 `rawdict` 파싱 대비 몇 %라 캐시할 이유도 없다(#721).
    """
    assert not hasattr(_is_scanned_page, "cache_info"), "_is_scanned_page 를 캐시하지 말 것"
