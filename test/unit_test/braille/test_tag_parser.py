"""인라인 태그 파서 회귀 테스트 — plan §3-5 / testdata_complex.txt 정본 대조.

순환검증 금지(test_guide 원칙 1): 기대 점자 글리프는 BBPG 규정·testdata_complex.txt에서
수동 도출한다(생산 코드로 생성하지 않음). 테두리·마커 글리프는 braillify 유무와 무관하게
고정이므로 결정적으로 단언한다. 제목 텍스트 점자(braillify 의존)는 구조만 검사하거나
braillify 설치 시에만 정본 대조한다.
"""
from __future__ import annotations

import pytest

from app.ai.braille import translator as _tr
from app.ai.braille.translator import (
    TN_MARKER,
    substitute_tags,
    tn_marker_spans,
    translate_tagged_text,
)


class TestPointMarkers:
    def test_점역자주_양끝_마커(self):
        out = translate_tagged_text("<!점역자주>그림 설명<!/점역자주>")
        assert out.startswith(TN_MARKER)
        assert out.endswith(TN_MARKER)
        assert out.count(TN_MARKER) == 2  # 내부 ⠠⠄ 없는 일반 텍스트 → 양끝만

    def test_점역자주_한글음절_버그_없음(self):
        # 구버그: [점역사주]/점역자주 한글이 그대로 점자화되면 안 됨
        out = translate_tagged_text("<!점역자주>치킨<!/점역자주>")
        assert "⠨⠎⠢⠱⠁⠇⠨⠍" not in out   # "점역자주" 음절
        assert "⠨⠎⠢⠱⠁⠠⠣⠨⠍" not in out  # "점역사주" 음절

    def test_점역자주_구형식_동일토큰(self):
        out = translate_tagged_text("<!점역자주>X<!점역자주>")
        assert out.startswith(TN_MARKER) and out.endswith(TN_MARKER)

    def test_표빈칸(self):
        assert "⠿⠿" in substitute_tags("성명 <!표빈칸>")

    def test_네모빈칸(self):
        assert "⠸⠦" in substitute_tags("동의 <!네모빈칸> 예 <!네모빈칸> 아니오")

    def test_미지태그_안전제거(self):
        out = substitute_tags("도형 1<!직사각형> 끝")
        assert "<!직사각형>" not in out
        assert "<!" not in out and "!>" not in out


class TestBorder:
    """글상자=표 테두리 (BBPG-1.2.5). 캡 ⠿, 위 채움 ⠛(=g), 아래 채움 ⠶(=7), 32칸."""

    def test_위테두리_제목없음_전체채움(self):
        out = substitute_tags("<!표윗테두리><!/표윗테두리>")
        assert out == "⠿" + "⠛" * 30 + "⠿"
        assert len(out) == 32

    def test_아랫테두리_제목없음_전체채움(self):
        out = substitute_tags("<!표아랫테두리><!/표아랫테두리>")
        assert out == "⠿" + "⠶" * 30 + "⠿"
        assert len(out) == 32

    def test_위테두리_제목_32칸_7칸배치(self):
        # BBPG-1.2.5(4)②: 제목 7번째 칸부터, 양옆 한 칸 띔
        out = substitute_tags("<!표윗테두리>범례<!/표윗테두리>")
        assert len(out) == 32
        assert out.startswith("⠿⠛⠛⠛⠛⠀")  # 캡1+채움4+빈칸1 → 제목 col7
        assert out.endswith("⠿")

    def test_위테두리_구형식_동일토큰(self):
        out = substitute_tags("<!표윗테두리>범례<!표윗테두리>")
        assert len(out) == 32

    @pytest.mark.skipif(not _tr._BRAILLIFY_AVAILABLE,
                        reason="braillify 필요 — testdata_complex.txt 정본 점자 대조")
    def test_위테두리_범례_testdata_정본대조(self):
        # testdata_complex.txt 60행 (글상자 범례 위 테두리, 태민 정본)
        expect = "⠿⠛⠛⠛⠛⠀⠘⠎⠢⠐⠌⠀⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠛⠿"
        assert substitute_tags("<!표윗테두리>범례<!/표윗테두리>") == expect


class TestTnMarkerSpans:
    def test_open_close(self):
        assert tn_marker_spans("⠠⠄⠁⠃⠠⠄") == [(0, 2, "tn_open"), (4, 6, "tn_close")]

    def test_단일마커_open만(self):
        assert tn_marker_spans("⠠⠄⠁⠃") == [(0, 2, "tn_open")]

    def test_마커없음(self):
        assert tn_marker_spans("⠁⠃⠉") == []
