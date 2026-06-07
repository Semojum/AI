"""역점역(braille_back) 회귀 테스트 — 점자 BRF → 텍스트 근사 복원.

입력 점자 셀과 기대 텍스트는 규정·braillify 점형에서 수동 도출(순환검증 금지).
decode는 커밋된 음절 역맵(braille_syllable_map.json)만 사용 → braillify 없이 결정적.
역점역은 검증 보조(근사)이지 정본이 아니다 — 본질적 모호성 케이스는 단언하지 않는다.
"""
from __future__ import annotations

from app.utils.braille_back import decode


class TestNumbers:
    def test_수표_숫자(self):
        assert decode("⠼⠙⠓") == "48"        # 수표 + 4 + 8
        assert decode("⠼⠁⠚⠚") == "100"      # 수표 + 1 + 0 + 0


class TestRoman:
    def test_로마숫자_II(self):
        # 로마자표 ⠴ + 대문자단어 ⠠⠠ + ii + 종료표 ⠲ → II
        assert decode("⠴⠠⠠⠊⠊⠲") == "II"

    def test_단독_대문자_I(self):
        assert decode("⠴⠠⠊⠲") == "I"


class TestUnitsAndMarkers:
    def test_섭씨_단위(self):
        assert decode("⠴⠙⠠⠉") == "℃"       # 단위(℃)를 로마자로 오인하지 않는다

    def test_점역자주_마커(self):
        assert decode("⠠⠄") == "【점역자주】"


class TestHangul:
    def test_음절_복원(self):
        assert decode("⠑⠯") == "물"
        assert decode("⠑⠯⠨⠕⠂") == "물질"

    def test_공백_보존(self):
        assert decode("⠑⠯⠀⠑⠯") == "물 물"

    def test_마침표_분리(self):
        # 다(⠊) + 마침표(⠲) = 닾와 같은 셀 → '다.'로 분리돼야(닾로 오인 금지)
        assert decode("⠊⠲") == "다."


class TestUnknown:
    def test_미지_셀_표시(self):
        # 어떤 맵에도 없는 셀은 ⟨코드포인트⟩로 정직하게 남긴다.
        out = decode("⣿")
        assert out.startswith("⟨") and out.endswith("⟩")

    def test_줄바꿈_보존(self):
        assert decode("⠑⠯\n⠑⠯") == "물\n물"
