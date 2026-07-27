"""여는 부호에 묶인 로마자의 로마자표 ⠴ (제34항) + 중복 개시 억제 (제29항 후단).

**이 파일이 지키는 것 — 그리고 지키지 *않는* 것**

지킨다(뿌리 A): 여는 문장부호·붙임표가 substitute_symbols에서 미리 점자 셀이 되면
`_emit_mixed`가 텍스트를 그 자리에서 쪼개고, `_split_english`는 잘린 조각만 보고
"한글 없음"으로 판정해 로마자표 ⠴를 빠뜨렸다. 제34항은 **종료표 ⠲만** 생략하라는
조항이고 **로마자표 ⠴는 여는 부호 안쪽에 그대로 적는다** — 규정 예문 셋이 전부 그렇다.

지키지 않는다(뿌리 B): 요소·줄에 한글이 정말 없는 순수 로마자는 **현행대로 ⠴ 없이**
적는다(제29항 [다만]). `test_다만_*`가 그 자리를 못박는 가드다. 두 뿌리를 하나로
뭉쳐 고치면 정상인 수천 자리가 오염된다(정답 코퍼스 국소 대조 dev 96% · val 95%가
현행 일치, 재현 `V2/temp/s2_gate.py`).

**순환검증 금지**: 기대값은 「한국 점자 규정」 원문 BRF를 그대로 옮겼고 생산 코드로
만들지 않았다. 조항 위치 = `braille-source/text/규정_텍스트.txt`
  제29항 1495행 · 제29항 [다만] 1506행 · 제34항 1708행(예문 1710·1713·1716행)
  「수학 점자」 1호 3321행 · 「과학 점자」 제6항 4437행
규정 BRF는 backtick="space" 관례다(코퍼스 gold의 "cell"과 **반대**).

대조는 **셀만** 본다 — 규정 원문이 32칸 줄로 접혀 있어 줄끝 채움 백틱과 진짜 칸
띄우기를 구별할 수 없기 때문이다(`test_roman_span_regulation.py`와 같은 이유).
"""
from __future__ import annotations

import pytest

from app.ai.braille import translator
from app.ai.braille.translator import translate_tagged_text
from app.utils.braille_ascii import ascii_to_unicode

_ROMAN = "⠴"          # 로마자표 (제29항)


def _cells(s: str) -> str:
    return "".join(ch for ch in s if 0x2800 <= ord(ch) <= 0x28FF and ch != "⠀")


def _reg(brf: str) -> str:
    """규정 원문 BRF → 셀 문자열."""
    return _cells(ascii_to_unicode(brf, backtick="space"))


def _ours(text: str) -> str:
    return _cells(translate_tagged_text(text))


@pytest.fixture
def regulation_mode(monkeypatch):
    """규정 모드 — 괄호를 도서 관행 붙임표가 아니라 규정 소괄호로 적는다."""
    monkeypatch.setattr(translator, "_BOOK_STYLE", False)


class Test제34항_묶인_로마자:
    """"로마자가 따옴표나 괄호 등으로 묶일 때에는 로마자 종료표를 적지 않는다"(1708행).

    없애는 것은 종료표뿐 — 로마자표는 여는 부호 **안쪽**에 적는다.
    """

    def test_겹따옴표(self):
        # 1710행: 문 앞에 "Open"이라고 쓰여 있었다. = ``eg`<4n`80,op50o"<@u`,,{:`o/s/`i4
        src = "문 앞에 “Open”이라고 쓰여 있었다."
        assert _ours(src) == _reg('``eg`<4n`80,op50o"<@u`,,{:`o/s/`i4')

    def test_소괄호(self, regulation_mode):
        # 1716행: 링컨(Lincoln)은 미국의 제16대 대통령이다.
        #         = ``"o7f)8'0,l9coln,0z`eo@maw`.n``#af`ir`irh="}oi4
        src = "링컨(Lincoln)은 미국의 제16대 대통령이다."
        assert _ours(src) == _reg('``"o7f)8\'0,l9coln,0z`eo@maw`.n``'
                                  '#af`ir`irh="}oi4')

    def test_홑따옴표_로마자표_개시(self):
        # 1713행: … 어말에서는 'k, t, p'로 적는다. = … ,80k1`;t1`;p0'"u`.?czi4
        # 여는 홑따옴표 ⠠⠦ 바로 뒤에 로마자표 ⠴가 서고 첫 낱자 k가 온다.
        # ※ 전체 일치는 아직 못 한다 — 규정은 낱자 b·c·t·p 앞에 통일영어점자 grade-1
        #   지시부호 ⠰를 두는데 미구현이다(test_roman_span_regulation.py의 xfail과 동일
        #   건). 이 테스트는 그 미구현과 무관한 '로마자표 개시'만 단언한다.
        out = _ours("‘ㄱ, ㄷ, ㅂ’은 자음 앞이나 어말에서는 ‘k, t, p’로 적는다.")
        assert _reg("`,80k") in out          # ⠠⠦ + ⠴ + k

    def test_대괄호(self):
        # 규정에 대괄호 예문은 없다. 제34항의 "괄호 등"에 대괄호가 들어간다는 판단은
        # 정답 도서가 뒷받침한다 — 한글 문장 속 [A]류는 dev 29/29 · val 123/126이
        # 로마자표를 적었다(재현 `V2/temp/s2_gate.py`). 대괄호 셀 자체는 D-12 결정.
        out = _ours("[A]는 무엇인가")
        assert _ROMAN + "⠠⠁" in out


class Test제29항_후단_중복개시_억제:
    """"로마자가 둘 이상 연이어 나오면 **첫** 로마자 앞에 로마자표를 적고"(1496행)."""

    def test_대괄호_두_개는_첫_번째만(self):
        # 정답 도서 언어 p049도 같다: ⠦⠄⠴⠠⠁⠠⠴⠤⠤⠦⠄⠠⠑⠠⠴ — 둘째 [E]엔 ⠴가 없다.
        out = _ours("34. [A]~[E]에 대한 감상으로 가장 적절한 것은?")
        assert _ROMAN + "⠠⠁" in out          # 첫 로마자 A 앞에는 로마자표
        assert _ROMAN + "⠠⠑" not in out      # 둘째 로마자 E 앞에는 없다

    def test_구분자로_쪼개진_한_구간은_한_번만(self):
        # (mg/kg·일) — '/'가 점자 셀이라 세그가 쪼개지지만 로마자런은 이어진다.
        # 제69항 예문 2704행 `160㎎/㎗를` = #afj0mg_/dl4 도 ⠴를 한 번만 적는다.
        out = _ours("다음 중 (mg/kg·일) 단위를 쓰는 것은?")
        assert out.count(_ROMAN) == 1

    def test_한글이_끼면_구간이_다시_열린다(self):
        # 제29항 후단의 '연이어'가 끊기는 자리 — 각각 새 구간이다.
        out = _ours("[A]와 [B]는 다르다")
        assert _ROMAN + "⠠⠁" in out
        assert _ROMAN + "⠠⠃" in out


class Test제29항_다만_뿌리B_가드:
    """"문단 전체가 로마자일 때에는 로마자표와 로마자 종료표를 생략할 수 있다"(1506행).

    ★ 이 클래스가 깨지면 고칠 대상은 이 테스트가 아니라 그 변경이다.
      한글 없는 순수 로마자에 ⠴를 붙이는 순간 정답 코퍼스 수천 자리가 어긋난다.
    """

    def test_다만_영어_제목(self):
        assert _ROMAN not in _ours("Table of Contents")

    def test_다만_영어_문장(self):
        # ⚠ 영어 예문을 고를 때 by·was를 피할 것 — 통일영어점자 낱말표가 둘 다 ⠴여서
        #   로마자표와 같은 셀이 나온다("… mean by that" → ⠍⠂⠝⠴⠞⠁⠞). 판정이 아니라
        #   테스트가 틀리는 자리다.
        assert _ROMAN not in _ours("The quick brown fox jumps over the lazy dog.")

    def test_다만_한글_거의_없는_영어_지문(self):
        # 조사 몇 개만 붙은 영어 인용은 사실상 '문단 전체가 로마자'다.
        assert _ROMAN not in _ours("(Grammatical and Ungrammatical Strings)에")


class Test줄_문맥은_전역이_아니다:
    """_break_offsets가 접두를 수천 번 재점역하므로 문맥을 전역에 두면 안 된다."""

    def test_다른_줄을_사이에_끼워도_같은_결과(self):
        src = "[A]는 무엇인가"
        first = _ours(src)
        _ours("Table of Contents")            # 한글 없는 줄
        _ours("아무 한글 줄")                  # 로마자 없는 줄
        assert _ours(src) == first

    def test_접두_재점역이_본문을_바꾸지_않는다(self):
        from app.ai.braille.translator import translate_with_breaks
        src = "[A]는 무엇인가"
        lines, _ = translate_with_breaks(src)
        assert lines[0] == translate_tagged_text(src)


@pytest.mark.xfail(
    reason="「과학 점자」 제6항(4437행) '식에 포함된 로마자는 로마자표를 적지 않는다' · "
           "「수학 점자」 1호(3321행) '수식에 사용하는 로마자는 로마자표를 적지 않고'. "
           "그런데 inline_math.wrap이 'a>1일 때'를 수식으로 라우팅하지 못해 텍스트 "
           "경로로 새고, 텍스트 경로는 줄에 한글이 있으니 로마자표를 연다. "
           "고칠 자리는 로마자표 규칙이 아니라 **수식 라우팅**이다 — 여기에 수학 예외를 "
           "박으면 같은 판정이 두 층에 흩어진다. 라우팅이 고쳐지면 이 xfail을 지울 것. "
           "실측 손해: 요소 이진 dev 4 · val 1 (재현 V2/temp/i3_cmp.py).",
    strict=True,
)
def test_수식_속_로마자에는_로마자표_없음() -> None:
    """정답 도서 수학2 p055도 `⠤⠼⠁⠤⠁⠢⠢⠼⠁⠕⠂` — 변수 a 앞에 ⠴가 없다."""
    assert _ROMAN not in _ours("a>1일 때")
