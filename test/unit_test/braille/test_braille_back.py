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
        """로마자표 ⠴ + **대문자 단어표** ⠠⠠ + ii → 유니코드 Ⅱ.

        Ⅱ 이상은 대문자 단어표로 적혀 변수 `I` 와 셀이 구분된다.
        실물 1,180쪽 A/B 좋아짐 72 · 나빠짐 1 로 유니코드 쪽을 채택했다
        (종전 기대값은 ASCII `II` 였다).
        """
        assert decode("⠴⠠⠠⠊⠊⠲") == "Ⅱ"

    def test_단독_로마숫자_I(self):
        """Ⅰ 은 제36항이 `0,i4`(⠴⠠⠊⠲ = 로마자표+대문자표+i+종료표)로 정한다.

        변수 `I` 와 셀이 같지만, **로마자표로 연 런의 내용이 대문자 I 하나뿐**일
        때로 좁히면 실물에서 거의 전부 로마 숫자다(1,180쪽 대조 이득 279·손해 17).
        원장 R-51.
        """
        assert decode("⠴⠠⠊⠲") == "Ⅰ"
        assert decode("⠴⠠⠊⠈⠔⠠⠠⠊⠊⠊⠲") == "Ⅰ~Ⅲ"      # Ⅰ~Ⅲ — 앞머리도 로마 숫자다

    def test_로마자표_없는_대문자_I는_그대로(self):
        """로마자표로 열리지 않은 런의 I 는 건드리지 않는다 — 화학식·유전자형 보호."""
        assert decode("⠠⠠⠊⠁") == "IA"                  # 대문자 단어표 — 로마자표 없음


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
