"""규정_텍스트.txt 예시 쌍 기반 braillify 회귀 테스트.

각 절에서 decode_ok=True인 쌍을 로드해 translate_tagged_text() 결과를 검증.
규정 원문 → BRF ASCII → Unicode 점자 경로로 추출된 gold 값과 비교.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.ai.braille.translator import translate_tagged_text

_PAIRS_DIR = Path(__file__).parent.parent.parent / "test_data" / "regulation_pairs"


def _load_testable(filename: str, max_korean_len: int = 15) -> list[dict[str, Any]]:
    """decode_ok이고 단어 수준인 쌍만 반환."""
    path = _PAIRS_DIR / filename
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    return [
        p for p in data["pairs"]
        if p["decode_ok"]
        and p["brf_ascii"] != "."          # 설명 줄 마침표 제거
        and len(p["korean"]) <= max_korean_len
        and not p["korean"].startswith("[") # [다만] 등 설명 항목 제거
        and "⠀" not in p["braille_unicode"] # 공백 포함 쌍 제거 (braillify는 공백 미삽입)
    ]


def _pairs_to_params(filename: str, max_n: int = 12) -> list[tuple[str, str, str]]:
    pairs = _load_testable(filename)[:max_n]
    return [(p["korean"], p["braille_unicode"], p["item"]) for p in pairs]


# ── 제1절: 첫소리 자음자 ─────────────────────────────────────────────────────

_SEC01 = _pairs_to_params("section_01_choseong.json")


@pytest.mark.parametrize("korean,expected,item", _SEC01)
def test_sec01_choseong(korean: str, expected: str, item: str) -> None:
    """제1절 첫소리 자음자 예시 쌍."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{item}] {korean!r}\n"
        f"  got:      {result!r}\n"
        f"  expected: {expected!r}"
    )


# ── 제2절: 받침 ──────────────────────────────────────────────────────────────

_SEC02 = _pairs_to_params("section_02_jongseong.json")


@pytest.mark.parametrize("korean,expected,item", _SEC02)
def test_sec02_jongseong(korean: str, expected: str, item: str) -> None:
    """제2절 받침 예시 쌍."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{item}] {korean!r}\n"
        f"  got:      {result!r}\n"
        f"  expected: {expected!r}"
    )


# ── 제3절: 모음자 ─────────────────────────────────────────────────────────────

_SEC03 = _pairs_to_params("section_03_vowels.json")


@pytest.mark.parametrize("korean,expected,item", _SEC03)
def test_sec03_vowels(korean: str, expected: str, item: str) -> None:
    """제3절 모음자 예시 쌍."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{item}] {korean!r}\n"
        f"  got:      {result!r}\n"
        f"  expected: {expected!r}"
    )


# ── 제6절: 숫자 (decode_ok 쌍) ───────────────────────────────────────────────

_SEC06 = _pairs_to_params("section_06_numbers.json")


@pytest.mark.parametrize("korean,expected,item", _SEC06)
def test_sec06_numbers(korean: str, expected: str, item: str) -> None:
    """제6절 숫자 예시 쌍."""
    result = translate_tagged_text(korean)
    assert result == expected, (
        f"[{item}] {korean!r}\n"
        f"  got:      {result!r}\n"
        f"  expected: {expected!r}"
    )


# ── 스모크 테스트: 섹션별 파일 존재 확인 ──────────────────────────────────────

_EXPECTED_FILES = [
    "section_01_choseong.json",
    "section_02_jongseong.json",
    "section_03_vowels.json",
    "section_04_abbreviations.json",
    "section_05_abbreviated_words.json",
    "section_06_numbers.json",
    "section_07_punctuation.json",
    "section_08_foreign.json",
    "section_09_special.json",
    "section_10_marks.json",
    "section_11_english.json",
    "section_12_numbers2.json",
    "section_13_misc.json",
    "section_14_layout.json",
]


@pytest.mark.parametrize("filename", _EXPECTED_FILES)
def test_regulation_pairs_file_exists(filename: str) -> None:
    assert (_PAIRS_DIR / filename).exists(), f"규정 쌍 파일 없음: {filename}"


@pytest.mark.parametrize("filename", _EXPECTED_FILES)
def test_regulation_pairs_has_decode_ok(filename: str) -> None:
    """각 섹션에 decode_ok 쌍이 하나 이상 있어야 함."""
    path = _PAIRS_DIR / filename
    if not path.exists():
        pytest.skip("파일 없음")
    data = json.loads(path.read_text(encoding="utf-8"))
    ok = [p for p in data["pairs"] if p["decode_ok"]]
    assert len(ok) >= 1, f"{filename}: decode_ok 쌍 0개"


class TestBracketRegulation:
    """원문 대괄호 [ ] → 규정 제49항 대괄호 셀 82…;0 (⠦⠆…⠰⠴). 2026-07-27 결정.

    기대값은 **규정·지침 원문의 점자 예시에서 그대로 옮겼다**(순환검증 금지) —
    우리 출력으로 만들지 않았다. 인용 위치는 각 케이스 주석에 적는다.

    · 「한국 점자 규정」 제49항 표(braille-source/text/규정_텍스트.txt 2163~2168행)
        ( = 8' · ) = ,0   |   [ = 82 · ] = ;0
    · 정답 코퍼스는 원문 대괄호를 소괄호 셀로 적어(471/471) 이 기대값과 어긋난다.
      코퍼스가 아니라 규정을 따르기로 한 결정이므로, 코퍼스 대조 지표는 내려간다.
    """

    def _brf(self, text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        from app.utils.braille_ascii import unicode_to_ascii
        return unicode_to_ascii(translate_tagged_text(text))

    # ── 지침 원문이 점자까지 실어 둔 예시 — 셀 단위 전부 대조 ──────────────────
    # 「점자 도서 제작 지침」 발음 표기 예(braille-source/text/점자 도서 제작 지침_text.txt
    # 1299~1301행). 네 쌍이 한 문단 안에 연달아 있고 모두 대괄호 셀 82…;0이다.
    @pytest.mark.parametrize("korean,expected", [
        ("나뭇가지[나무까지]", "cem'$.o82cem,$.o;0"),
        ("머릿기름[머리끼름]", "es\"o'@o\"{582es\"o,@o\"{5;0"),
        ("귓병[귀뼝]", "@mr'~}82@mr,~};0"),
        ("전셋집[전세찝]", ".),n'.ob82.),n,.ob;0"),
    ])
    def test_지침_발음표기_대괄호(self, korean: str, expected: str) -> None:
        assert self._brf(korean) == expected

    def test_지침_배점_대괄호(self) -> None:
        # 「점자 자료 제작 지침」 [예] 배점(점자 자료 제작 지침_text.txt 1627행) = 82#a.s5;0
        assert self._brf("[1점]") == "82#a.s5;0"
        # 「점자 도서 제작 지침」 [예 3-57] 발문(점자 도서 제작 지침_text.txt 3058행) = 82#c.s5;0
        assert self._brf("[3점]") == "82#c.s5;0"

    # ── 화이트리스트가 소괄호로 내리던 부류 — 이제 규정형이어야 한다 ────────────
    # 안쪽 점형은 이 테스트의 주장이 아니므로 여닫는 괄호 셀만 본다(비순환).
    @pytest.mark.parametrize("korean", ["[2012 수능]", "[16]", "[A]", "[실험 과정]"])
    def test_화이트리스트_부류도_규정_대괄호(self, korean: str) -> None:
        brf = self._brf(korean)
        assert brf.startswith("82") and brf.endswith(";0"), brf
        assert not brf.startswith("8'"), f"소괄호 셀로 새고 있다: {brf}"

    def test_수식_대괄호는_별도_점형(self) -> None:
        # 「한국 점자 규정」 수학 제6항(규정_텍스트.txt 3100~3112행)의 수학 대괄호 ('…,).
        # 문장부호 대괄호(82…;0)와 다른 체계라 이 변경이 수식 경로를 건드리면 안 된다.
        assert self._brf("<!수식>[3,5]<!/수식>") == "('#c1e,)"

    def test_관행_복귀_스위치(self, monkeypatch) -> None:
        """_BRACKET_BOOK_STYLE=True 한 줄로 코퍼스 관행(소괄호 셀)으로 되돌아간다."""
        from app.ai.braille import translator
        monkeypatch.setattr(translator, "_BRACKET_BOOK_STYLE", True)
        assert self._brf("[3점]") == "8'#c.s5,0"
        assert self._brf("[2012 수능]").startswith("8'")


class TestBookStyleConventions:
    """정답 도서 표기 관행(BRAILLE_STYLE=book, 기본값) — 규정과 다른 자리.

    ★ 기본=관행(태민 2026-07-17 재판정). 텍스트 축의 잣대가 정답 도서라 정답 표기가 기본.
      시각자료의 관행/규정 갈림은 4안 제공으로 해소(모드 선택 불필요). 규정 경로는
      BRAILLE_STYLE=regulation 스위치로 유지 — TestRegulationSwitch가 검증한다.

    근거: 정답 코퍼스(수능특강 점역본 1131p) 전수 관찰.
      · 화살괄호 〈〉《》: 코퍼스에 0회 → 작은따옴표(3618회)로 적음
        (신규 2027 코퍼스로도 재확인: 화살괄호 70 vs 작은따옴표 4,902 — 유지)

    ★ **표시 문자 괄호는 2026-08-06 판정 번복**(원장 R-06). "붙임표로 감쌈(-가- 1217회)"의
      근거가 **구판 수능특강 한 종류**였다. 신규 2027 코퍼스 48쪽 gold / 우리(종전):
        한글 1~2자  소괄호 331 / 10  · 붙임표  13 / 569
        숫자        소괄호  16 /  0  · 붙임표   0 /  74
        대문자 1자   소괄호 100 /  0  · 붙임표   0 /  22
        약어        소괄호   7 /  0  · 붙임표   0 /  14
      네 범주가 전부 뒤집힌다. 규정 제49항도 소괄호라 규정·관행이 같은 쪽을 가리킨다.
      효과: dev-2027 48쪽 CER 65.8% → 67.2%(편집 -1,375셀).
    """

    @pytest.fixture(autouse=True)
    def _book_mode(self, monkeypatch):
        """_BOOK_STYLE은 import 시점 상수라 env만 바꿔선 안 먹는다 — reload가 필요하다."""
        import importlib
        from app.ai.braille import translator
        monkeypatch.setenv("BRAILLE_STYLE", "book")
        importlib.reload(translator)
        yield
        monkeypatch.delenv("BRAILLE_STYLE")
        importlib.reload(translator)

    def _brf(self, text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        from app.utils.braille_ascii import unicode_to_ascii
        return unicode_to_ascii(translate_tagged_text(text))

    def test_한글_표시문자는_소괄호(self):
        assert self._brf("(가)") == "8'$,0"        # 소괄호 8'(⠦⠄) + 가$ + ,0(⠠⠴)
        assert self._brf("(나)") == "8'c,0"

    def test_숫자_표시문자는_소괄호(self):
        assert self._brf("(1)") == "8'#a,0"

    def test_단일_대문자_괄호는_소괄호(self):
        # gold 100회 형: 소괄호 안에 로마자표 0(⠴)+대문자표 ,(⠠). 한글 문맥에서 나온다.
        assert self._brf("(A)와 (B)").startswith("8'0,a,0")
        # ⚠ 단독 "(A)"만 넣으면 로마자표가 안 붙는다(문맥이 없어 로마자 런이 안 열린다).
        #   실사용은 항상 한글 문맥이라 위 형이 기준이다.
        assert self._brf("(A)") == "8',a,0"

    def test_약어_괄호도_소괄호(self):
        assert self._brf("(SNS)를").startswith("8'0,,sns,0")   # 대문자 단어표 ,, 포함
        # (단독은 로마자표 0 없이 — (A)와 같은 사정)
        assert self._brf("(B)") == "8',b,0"
        # 소문자 (x)는 수학 변수(수학2 수식괄호 1609건)라 소괄호 유지 — 회귀 방지
        assert self._brf("(x)") == "8'x,0"

    def test_일반_한글_괄호도_소괄호(self):
        # 2026-08-06 번복: 표시 문자뿐 아니라 일반 괄호도 붙임표가 아니라 소괄호다.
        for t in ("(조사)", "(2,575)"):
            assert self._brf(t).startswith("8'") and self._brf(t).endswith(",0")

    def test_배열형_답지는_동그라미형_유지(self):
        # (A)-(B)-(C) 배열형만 gold가 동그라미형 묶음으로 적는다(구판 외국어 516건).
        # 신규 코퍼스에 외국어 권이 없어 재확인 못 했으므로 종전 형을 유지한다.
        assert self._brf("(A)-(B)").startswith("7,a7")

    def test_홑화살괄호는_그대로_나간다(self):
        """★ 2026-08-26 뒤집힘 — 종전 기대값은 `‘보기’`(작은따옴표)였다.

        그 근거("정답 코퍼스에 화살괄호 0회, 작은따옴표 3618회")가 **frozen(구판) 실측**이다.
        dev-2027 60쪽 실측(eval E001): 〈 gold 100건/22쪽 대 우리 1건 · 〉 gold 65건 대 우리 0건.
        규정도 화살괄호 쪽이다 — symbol_table 에 〈 = ⠐⠶ · 〉 = ⠶⠂ 가 이미 있다.

        원인은 순서 충돌이었다 — `_ANGLE_LABEL_RE` 가 `<보기>` 를 `〈보기〉` 로 먼저 옳게
        바꾸는데 `_ANGLE_RE` 가 그것까지 다시 잡아 작은따옴표로 되돌렸다. 결과가 두 겹으로
        나빴다: **닫는 ⠴⠄ 가 앞 음절에 붙어 '보기'가 '보깋'이 됐다.**
        """
        assert self._brf("〈보기〉") == '"7~u@o71'      # ⠐⠶보기⠶⠂
        assert self._brf("<보기>") == '"7~u@o71'       # ASCII 도 같은 자리로

    def test_홑낫표는_그대로_둔다(self):
        """「 」는 안 건드린다 — gold ⠐⠦ dev 70 대 묵자 「 47 로 셀이 겹친다(eval 08-22)."""
        assert self._brf("「국어」") != '"7~u@o71'


class TestRegulationSwitch:
    """BRAILLE_STYLE=regulation 스위치가 살아 있다는 계약(기본=관행, 태민 2026-07-17 재판정).

    기본 동작은 TestBookStyleConventions가 검증한다(이제 autouse env 없이도 기본이 관행).
    여기서는 규정 모드로 전환했을 때 규정 표기가 나오는지만 본다.
    """

    @pytest.fixture(autouse=True)
    def _reg_mode(self, monkeypatch):
        import importlib
        from app.ai.braille import translator
        monkeypatch.setenv("BRAILLE_STYLE", "regulation")
        importlib.reload(translator)
        yield
        monkeypatch.delenv("BRAILLE_STYLE")
        importlib.reload(translator)

    def _brf(self, text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        from app.utils.braille_ascii import unicode_to_ascii
        return unicode_to_ascii(translate_tagged_text(text))

    def test_표시문자는_규정_소괄호(self):
        assert self._brf("(가)") == "8'$,0"          # 제49항 소괄호 (관행이면 -$-)

    def test_화살괄호는_규정_기호(self):
        # 제63항 〈…〉 — 관행(작은따옴표 ,8~u@o0')로 새지 않아야 한다
        assert self._brf("〈보기〉") != ",8~u@o0'"


class TestCircledJamoReg64:
    """동그라미 자모·음절 = 규정 제64항 감쌈형 ⠶…⠶ (2026-08-06 판정 번복).

    종전에는 "도서는 맨 글자로 적는다"고 봤는데, 그 실측이 **구판 수능특강 한 종류**였다.
    신규 2027 코퍼스 48쪽에서 묵자 ㉠ 개수와 gold `⠶⠿⠁⠶` 개수가 쪽마다 1:1로 맞는다
    (4개 책 전부). 규정도 관행도 감쌈형이다.
    """

    @staticmethod
    def _t(text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        return translate_tagged_text(text)

    def test_자모는_온표까지_감싼다(self) -> None:
        assert self._t("㉠") == "⠶⠿⠁⠶"          # ⠶ + 온표⠿ + ㄱ⠁ + ⠶
        assert self._t("㉡") == "⠶⠿⠒⠶"

    def test_음절은_온표가_없다(self) -> None:
        assert self._t("㉮") == "⠶⠫⠶"           # ⠶ + 가⠫ + ⠶

    def test_뒤에_조사가_붙어도_감쌈이_남는다(self) -> None:
        assert self._t("㉠은").startswith("⠶⠿⠁⠶")

    def test_맨_자모는_감싸지_않는다(self) -> None:
        assert self._t("ㄱ") == "⠿⠁"            # 글머리 ㄱ은 온표+자모 그대로

    def test_동그라미_숫자는_수표_그대로(self) -> None:
        assert self._t("①").startswith("⠼")     # 규정=도서 일치라 건드리지 않는다


class TestOXMark:
    """맞고 틀림 기호 (「점자 자료 제작 지침」 2장 (4) · 예 2-31, 원장 C-14).

    원문: "동그라미나 숫자 0은 로마자 O로, 도형 형태의 가위표(×)는 로마자 X로,
    세모는 _+으로 적는다."  예 2-31 BRF 가 `0,o`(⠴⠠⠕) · `0,x`(⠴⠠⠭) 로 값을 확인해 준다.
    실측(desk, dev-2027): 78조각·16쪽·4권 전부.

    ⚠ 세모(△)와 `○`(U+25CB)는 **일부러 뺐다.** 둘은 숨김표·도형 기호로 이미 쓰여
    (제40항 · `_UNLISTED_SHAPE_RUN_RE`) 맞고 틀림 문맥인지를 글만 보고 못 가른다.
    넣어 봤더니 단위 테스트 28건이 깨졌다. 실측이 잡은 것도 `◯`(U+25EF)와 `×` 둘뿐이다.
    """

    def test_지침_예2_31(self):
        from app.ai.braille.translator import translate_plain
        got = translate_plain("일치하면 ◯, 일치하지 않으면 ×에 표시해 봅시다.")
        assert "⠴⠠⠕" in got, got
        assert "⠴⠠⠭" in got, got

    def test_홀로_선_자리만_바꾼다(self):
        from app.ai.braille.translator import translate_plain
        assert "⠴⠠⠕" in translate_plain("※ ◯ 또는 ×")
        assert "⠴⠠⠭" in translate_plain("3. ◯  4. ×")

    def test_곱셈은_안_건드린다(self):
        """곱셈 × 는 늘 피연산자 사이에 있다 — 여기 걸리면 수식이 깨진다."""
        from app.ai.braille.translator import translate_plain
        for s in ("2 × 3", "넓이는 3×4이다", "가로 × 세로", "2 × 3 = 6",
                  "반지름×반지름", "넓이 = 3 × 4"):
            assert "⠴⠠⠭" not in translate_plain(s), s

    def test_계열_코드포인트를_다_잡는다(self):
        """★ 2026-08-26 2차 — 1차는 U+25EF 만 넣어 `〇`(U+3007)·`⭕`(U+2B55)가
        점형이 없어 **빈 문자열로 사라졌다**(eval 실측). 매핑 없는 글자가 조용히
        없어지거나 원문자 그대로 실리면 안 된다."""
        from app.ai.braille.translator import translate_plain
        for c in "◯〇⭕":
            assert translate_plain(c) == "⠴⠠⠕", (c, translate_plain(c))
        for c in "×✕✖":
            assert translate_plain(c) == "⠴⠠⠭", (c, translate_plain(c))

    def test_답지_번호_사이는_정오표시다(self):
        """`3. × 4. ◯` — 앞뒤가 다 답지 번호면 곱셈이 아니다(실물 d020 001/body/0184)."""
        from app.ai.braille.translator import translate_plain
        got = translate_plain("3. × 4. ◯")
        assert "⠴⠠⠭" in got and "⠴⠠⠕" in got, got


class TestHancomMathFont:
    """한컴 수식 글꼴 흔적 되살리기 (대표 결재 2026-08-26).

    한컴 수식 글꼴 PDF 는 함수 이름을 **ASCII 로 31 내려서** 싣는다
    (T+31='s' · J+31='i' · O+31='n'). eval 실측 18건/3쪽.
    ⚠ 시프트를 통째로 걸면 멀쩡한 대문자 낱말이 다 깨진다 — 아는 토막만 되살린다.
    """

    def test_함수_이름을_되살린다(self):
        from app.ai.braille.translator import _decode_hancom_math as d
        assert d("TJO x") == "sin x"
        assert d("DPT 2x") == "cos 2x"
        assert d("UBO a") == "tan a"

    def test_멀쩡한_대문자는_안_건드린다(self):
        from app.ai.braille.translator import _decode_hancom_math as d
        assert d("SUBJECT TJOB") == "SUBJECT TJOB"     # 낱말 경계 밖은 손 안 댄다
        assert d("ATJO") == "ATJO"

    def test_아는_모지바케만_되살린다(self):
        """É 는 문맥으로 ≤ 가 확정됐다(`2p-a<xÉ2p`). Û·Á·Ñ·Ú 는 정체를 몰라
        **추정으로 넣지 않는다**(대표 지시) — 그대로 두고 로그만 남긴다."""
        from app.ai.braille.translator import _decode_hancom_math as d
        assert d("2p-a<xÉ2p") == "2p-a<x≤2p"
        assert d("MOÛST") == "MOÛST"


class TestNonBraillableChars:
    """점자로 못 가는 글자 (C033 전수, dev-2027 d025 60쪽).

    초안 묵자에 실리는 비-한글/비-ASCII 1,646개 중 **점자 경로도 못 넘기는 것이 198개·54종**
    이었다. 값이 확실한 셋만 손댄다 — 나머지(한자·아랍 숫자·도형)는 규정 판단이 필요하다.
    """

    def test_제로폭_조합문자는_지운다(self):
        """눈에 안 보이는데 점역만 방해한다. ZWNJ 23건 · 조합 네모 14건 실측."""
        from app.core.pipeline import _draft_print_text
        assert "\u200c" not in _draft_print_text("\u200c공유한")
        assert "\u20de" not in _draft_print_text("답\u20de ③")

    def test_괄호숫자를_편다(self):
        """유니코드 이름이 PARENTHESIZED DIGIT 다 — 추정이 아니라 정의다(19건)."""
        from app.core.pipeline import _draft_print_text
        from app.ai.braille.translator import translate_plain
        assert _draft_print_text("⑴ 방정식").startswith("(1)")
        assert "⑴" not in translate_plain("⑴ 방정식")

    def test_C1_제어문자도_지운다(self):
        """`_CTRL_RE` 가 C0 만 잡고 있었다 — `\x93` 실측 37건."""
        from app.core.pipeline import _draft_print_text
        assert "\x93" not in _draft_print_text("O.\x93= L")

    def test_모르는_것은_안_건드린다(self):
        """한자·아랍 숫자·도형은 규정 판단이 필요하다. 추정으로 바꾸지 않는다."""
        from app.core.pipeline import _draft_print_text
        assert "非" in _draft_print_text("비(非)수급자")
        assert "▽" in _draft_print_text("▽▽연구소")
