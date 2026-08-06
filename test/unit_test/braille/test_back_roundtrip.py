"""역점역 왕복 — 묵자 → 점자 → 묵자 (2026-08-06, S6).

역점역은 검수 보조 도구다(점역사가 아니어도 출력이 원문과 맞는지 눈으로 본다).
100% 가역은 원리상 불가능하지만(약자·다대일), **알아낼 수 있는 것을 놓치면 안 된다.**

## 이 파일이 지키는 것

  1. **로마자표 ⠴로 시작하는 기호와의 충돌** — `%`=⠴⠏ 인데 로마자표+p 도 ⠴⠏다.
     `pH`가 `%`+미지셀로 깨졌다. 긴 쪽이 이긴다.
  2. **영어 Grade 2 약자 역매핑** — `Player`의 `er`(⠻), `Windows`의 `in`(⠔).
     모르면 그 셀에서 런이 끊겨 뒤가 통째로 한글로 오독된다.
  3. **로마자 구간 안 숫자**(제35항) — `A4`·`MP3`·`V1`. 다만 종료표가 없으면 잇지 않는다
     (`A4용지`가 `A4inggg지`로 깨진 실측).
  4. **감쌈 붙임표 → 괄호 복원** — 정방향이 `(가)`를 ⠤가⠤로 바꾼다. 되돌린다.
     **토큰 전체가 `-X-`일 때만** — 줄 안 아무 데나 바꾸면 진짜 붙임표가 깨진다.

## 손대지 않은 것

  · **공백을 넘는 로마자 구간**(제32항, `MP4 Player`) — `decode`가 줄을 공백 단위로
    쪼개고, 구간 경계를 못 믿는다(⠴=닫는따옴표·⠲=마침표와 셀이 같아 정답 도서에서
    `⠴…⠲` 15,996건 중 절반이 한글 오탐).
  · **로마자표 없는 순수 영문**(제4항 생략, `computer`·URL) — 한글 셀과 겹쳐 못 가른다.
"""
from __future__ import annotations

import pytest

from app.ai.braille.translator import translate_tagged_text
from app.utils.braille_back import decode


def _rt(text: str) -> str:
    return decode(translate_tagged_text(text))


class TestRomanSymbolCollision:
    """⠴로 시작하는 기호와 로마자 런이 같은 셀을 다툰다 — 긴 쪽이 이긴다."""

    @pytest.mark.parametrize("text", ["pH 농도", "mV 측정"])
    def test_로마자가_길면_로마자(self, text: str) -> None:
        """`%`=⠴⠏ 와 로마자표+p 가 같은 셀이라 `pH`가 `%`+미지셀로 깨졌었다."""
        assert _rt(text) == text

    @pytest.mark.parametrize("text", ["25℃ 물", "5㎏ 짐", "3㎝ 길이", "10㎞ 거리",
                                      "50% 확률", "2㎡ 넓이"])
    def test_길이가_같으면_기호가_이긴다(self, text: str) -> None:
        """℃(⠴⠙⠠⠉)·㎏(⠴⠅⠛⠲)은 로마자로 읽어도 같은 셀 수라 단위 기호로 남는다."""
        assert _rt(text) == text


class TestEnglishContractions:
    """영어 Grade 2 약자 역매핑. 표는 `eng_braille`에서 뒤집어 만든다."""

    @pytest.mark.parametrize("text", ["Windows 10 설치", "Player 기능"])
    def test_약자_든_낱말이_복원된다(self, text: str) -> None:
        assert _rt(text) == text

    def test_역표가_정방향에서_왔다(self) -> None:
        """손으로 적은 표면 정방향과 어긋난다 — 뒤집어 만든 것인지 확인."""
        from app.ai.braille import eng_braille
        from app.utils import braille_back as B

        for word, cell in eng_braille.STRONG_GROUPS.items():
            assert B._ENG_ANY.get(cell) is not None
        assert B._ENG_ANY[eng_braille.STRONG_GROUPS["and"]] == "and"


class TestRomanRunNumbers:
    """제35항 — 구간 안 숫자는 구간을 끊지 않는다. 단 종료표가 증거다."""

    @pytest.mark.parametrize("text", ["A4용지", "MP3 파일", "V1 단계"])
    def test_숫자가_끼어도_안_깨진다(self, text: str) -> None:
        assert _rt(text) == text

    def test_종료표_없으면_한글을_안_삼킨다(self) -> None:
        """`A4용지`는 종료표가 없다 — 이어 가면 `A4inggg지`가 된다(실측)."""
        assert _rt("A4용지") == "A4용지"


class TestWrapParens:
    """감쌈 붙임표 → 괄호. 토큰 전체가 `-X-`일 때만."""

    def test_감쌈이_괄호로_돌아온다(self) -> None:
        assert _rt("(가) 항목") == "(가) 항목"

    def test_약어_감쌈도_돌아온다(self) -> None:
        assert _rt("(SNS) 이용") == "(SNS) 이용"

    @pytest.mark.parametrize("text", ["가-나 관계", "고복지-저부담 국가"])
    def test_진짜_붙임표는_안_건드린다(self, text: str) -> None:
        """줄 단위로 바꾸면 여기가 깨진다 — 실측 악화 4건의 정체."""
        assert _rt(text) == text


class TestNoRegression:
    """고치는 과정에서 깨진 적이 있는 것들 — 다시 깨지지 않게 못 박는다."""

    @pytest.mark.parametrize("text", [
        "EBS 교재를 본다", "ATP 합성", "TV 방송", "숫자 100개",
        "DNA 구조 분석", "pH 농도",
    ])
    def test_기존_동작_유지(self, text: str) -> None:
        assert _rt(text) == text


class TestKnownLimits:
    """못 하는 것을 **명시**한다 — 동작이 바뀌면 판단을 뒤집은 것이므로 알아야 한다."""

    def test_로마자표_없는_영문은_못_읽는다(self) -> None:
        """제4항으로 로마자표를 생략한 표기. 한글 셀과 겹쳐 문맥 없이는 못 가른다."""
        assert _rt("computer") != "computer"

    @pytest.mark.parametrize("text", ["pH", "mV"])
    def test_단독_소문자_약어는_못_읽는다(self, text: str) -> None:
        """제4항 — 전체가 외국어면 로마자표를 생략한다. 그러면 단서가 없다.

        한글이 섞이면(`pH 농도`) 로마자표가 붙어 제대로 읽힌다. 대문자 약어(`ATP`)는
        대문자 단어표 ⠠⠠가 단서가 되어 로마자표 없이도 읽힌다.
        """
        assert _rt(text) != text

    def test_대문자_약어는_단독이어도_읽힌다(self) -> None:
        assert _rt("ATP") == "ATP"

    def test_공백_넘는_구간은_못_읽는다(self) -> None:
        """제32항 `MP4 Player`. decode가 공백 단위로 쪼개고 구간 경계를 못 믿는다."""
        got = _rt("MP4 Player를 샀다")
        assert got.startswith("MP4 ")
        assert "Player" not in got
