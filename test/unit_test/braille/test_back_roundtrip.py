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

    @pytest.mark.parametrize("text", ["25℃ 물", "50% 확률"])
    def test_길이가_같으면_기호가_이긴다(self, text: str) -> None:
        """℃(⠴⠙⠠⠉)는 로마자로 읽어도 같은 셀 수라 단위 기호로 남는다."""
        assert _rt(text) == text

    @pytest.mark.parametrize("text,want", [("5㎏ 짐", "5kg 짐"), ("3㎝ 길이", "3cm 길이"),
                                           ("10㎞ 거리", "10km 거리"),
                                           # 제곱 단위는 뒤가 숫자로 끝나 `_join_num_hangul`
                                           # (제17항 [다만])이 뒤 한글의 칸을 먹는다 —
                                           # 전권 18,892쪽에서 1건뿐이라 그대로 둔다.
                                           ("넓이 2㎡", "넓이 2m^2"),
                                           ("넓이 2㎠", "넓이 2cm^2")])
    def test_로마자_단위는_로마자로_돌아온다(self, text: str, want: str) -> None:
        """규정 제69항 — 로마자로 쓰인 단위는 `⠴ + 낱자 + ⠲` 라 사각문자와 점형이 같다.

        어느 쪽으로 펼지는 실측이 정한다: 재추출 묵자 1,361쪽 전수에서 로마자꼴 114회 대
        사각문자 1회(㎢)이고, 그 셀이 실제로 있는 쪽만 봐도 묵자는 cm 19·kg 5·km 6 …
        **사각문자 0회**다(원장 R-27). 기호 매칭이 로마자 런을 이기는 성질은 그대로다 —
        뒤 한글(`짐`·`길이`)이 런에 안 먹혔는지가 이 케이스의 본뜻이다.
        """
        assert _rt(text) == want


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

    @pytest.mark.parametrize("text", ["such tactics", "the main reason", "the rough Atlantic Ocean"])
    def test_로마자표_없는_영어줄을_읽는다(self, text: str) -> None:
        """제29항 [다만] — 문단 전체가 로마자면 로마자표를 생략할 수 있다.

        단서 셀이 없으므로 정방향으로 되짚어(`eng_braille.translate`) 원래 셀과
        같을 때만 영어로 본다. 기능어를 하나 요구해 뜻 없는 알파벳을 걸러 낸다.
        """
        assert _rt(text) == text

    @pytest.mark.parametrize("text", ["우주 그물로 감동 유도", "독자의 공감과 감동 유도"])
    def test_한글줄을_영어로_뒤집지_않는다(self, text: str) -> None:
        """실측 오탐 — 되짚기만으로는 `우주 그물로`가 `dujya Oiu`로 통과했다."""
        assert _rt(text) == text

    @pytest.mark.parametrize("text", ["1년 동안", "비만 3단계인 사람", "2도 올랐다"])
    def test_숫자_뒤_한글을_되붙인다(self, text: str) -> None:
        """제17항 [다만] — 숫자와 혼동되는 ㄴㄷㅁㅋㅌㅍㅎ 첫소리는 붙어 나와도 띄어 쓴다.

        그래서 점자의 그 한 칸은 원문에 없던 것이다. 되돌리지 않으면 `1년`이 `1 년`이 된다.
        코퍼스 실측 4,995건 중 붙여 쓴 원문이 3,786건(75.8%)이라 붙이는 쪽을 택했다.
        """
        assert _rt(text) == text

    @pytest.mark.parametrize("text", ["a<b", "a>b", "(x<t)"])
    def test_부등호를_읽는다(self, text: str) -> None:
        """「수학 점자」 제4항 — <는 ⠔⠔, >는 ⠢⠢. 역표에 ≤·≥·≠만 있어 빠져 있었다."""
        from app.ai.braille.kor_math_rules import convert_latex
        from app.utils.braille_back import decode

        assert decode(convert_latex(text), math=True) == text

    @pytest.mark.parametrize("text", ["a≡b", "a±b", "a⊃b", "a∉b", "a⊥b", "a√b", "a∞b"])
    def test_수학기호를_읽는다(self, text: str) -> None:
        """수식 모드 전용 역표 — 한 칸짜리는 한글과 겹쳐 안 넣는다(∫=⠮는 '을')."""
        from app.ai.braille.kor_math_rules import convert_latex
        from app.utils.braille_back import decode

        assert text[1] in decode(convert_latex(text), math=True)

    def test_수식줄에_영어판정을_대지_않는다(self) -> None:
        """`a √ b`가 `a ar b`로 뒤집히던 회귀 — ⠜는 √이자 영어 약자 ar이다."""
        from app.ai.braille.kor_math_rules import convert_latex
        from app.utils.braille_back import decode

        assert decode(convert_latex("a √ b"), math=True) == "a √ b"

    def test_글상자_테두리를_표시로_읽는다(self) -> None:
        """테두리는 글자가 아니라 도형이다 — 음절로 읽으면 `옹운운운…옹`이 나온다."""
        assert _rt("<!상자><!/상자>") == "【글상자】"
        assert _rt("<!상자>과학 돋보기<!/상자>") == "【글상자 과학 돋보기】"

    @pytest.mark.parametrize("text", ["옹기와 옹달샘", "가운데 옹 하나"])
    def test_약자_옹은_그대로_읽는다(self, text: str) -> None:
        """⠿는 테두리 셀이자 약자 '옹'이다 — 줄 전체가 테두리 꼴일 때만 표시로 바꾼다."""
        assert _rt(text) == text

    def test_짝_없는_드러냄표_닫는표를_버린다(self) -> None:
        """제35항 드러냄표는 글자체 표시라 묵자에 대응 문자가 없다.

        여는 표가 앞 쪽에 있거나 줄임표가 바로 앞이면 짝이 안 잡혀 `-'` 로 샜다.
        묵자 대조(수능특강 문학 p0151): `다행이로다.”` — ⠤⠄ 자리에 글자가 없다.
        실측 48회·45쪽.
        """
        assert decode("⠊⠚⠗⠶⠕⠐⠥⠊⠲⠤⠄⠴") == "다행이로다.”"
        assert decode("⠠⠤⠈⠥⠨⠕⠤⠄") == "고지"      # 짝이 맞으면 종전대로
    def test_원본_페이지_변경선을_읽는다(self) -> None:
        """「점자 자료 제작 지침」 2.4.5 — 1칸부터 붙임표를 채우고 원본 쪽 번호를 오른쪽에 적는다.

        글자가 아니라 조판 표시인데 역맵에 없어 붙임표 런이 줄표로 나오고 뒤 수표가
        `⟨⠼⟩` 로 샜다. 꼬리가 `⠼⠤`(#-)면 선행 번호와 연결되지 않는다는 표시다.
        실측 91줄·38쪽.
        """
        assert decode("⠤" * 30 + "⠼⠤") == "【원본 페이지 변경선】"
        assert decode("⠤" * 22 + "⠼⠋⠤⠼⠛") == "【원본 페이지 변경선 6-7】"
        assert decode("⠤" * 8) == "【표 구분선】"     # 번호 없는 줄은 종전대로

    def test_수식_쉼표와_곱셈점을_가른다(self) -> None:
        """「수학 점자」 제12항 [붙임 1] 쉼표 = 곱셈 [붙임] 점 곱셈 기호 = 같은 셀 ⠐.

        규정 예문이 **띄어쓰기로 갈린다** — 쉼표는 뒤에 빈칸이 있고(`a₁, a₂, a₃,`),
        곱셈점은 앞뒤가 붙어 있다(`6·9`). 종전에는 둘 다 `·` 로 내서
        `Ⅲ이 d_1· Ⅳ가 d_4·` 처럼 쉼표 자리가 가운뎃점으로 나갔다(7,059회·1,380쪽).
        """
        assert decode("⠁⠰⠼⠁⠐⠀⠁⠰⠼⠃⠐⠀⠁⠰⠼⠉⠐") == "a_1, a_2, a_3,"
        assert decode("⠁⠔⠼⠃⠐⠃⠒⠒") == "a-2·b="      # 붙은 것은 곱셈점 그대로

    def test_각_기호를_읽는다(self) -> None:
        """「수학 점자」 제39항 `∠ABC` = ⠹⠠⠠ABC.

        ⠹ 는 한글 약자 `억` 과 같은 셀이라 **뒤가 대문자 단어표 + 낱자일 때만** 본다.
        줄임표 ⠠⠠⠠ 는 +3 이 낱자가 아니라 안 걸린다. 실측 1,023회·143쪽.
        """
        assert decode("⠹⠠⠠⠃⠁⠉⠒⠒⠼⠑⠌⠨⠏") == "∠BAC=5분의π"
        assert decode("⠹⠈⠎") == "억거"                # 홀로 선 ⠹ 는 약자 그대로

    def test_공백_넘는_구간을_읽는다(self) -> None:
        """제32항 `MP4 Player` — 2026-08-24까지는 못 읽던 한계였다.

        decode가 줄을 공백으로 쪼개 둘째 낱말이 문맥을 잃었다. 이제 `_merge_roman_tokens`가
        **종료표 ⠲가 실제로 앞에 있을 때만** 토큰을 합친다. 낱말 앞의 ⠴만 로마자표로 보므로
        (제29항) 닫는 낫표 `』`=⠴⠆를 구간 시작으로 오인하지 않는다.
        """
        assert _rt("MP4 Player를 샀다") == "MP4 Player를 샀다"

    def test_큰_수의_만_단위_구분선을_읽는다(self) -> None:
        """초등 교재 관행 — 큰 수를 네 자리씩 끊어 보일 때 ⠸ 를 넣는다.

        규정 제41항의 자릿점은 쉼표 ⠂ 라 이건 규정형이 아니다. 안 읽으면 ⠸ 가
        미해독으로 새고 **뒤 숫자가 수표 문맥을 잃어 글자로** 떨어졌다
        (`30|6025` → `30⟨2838⟩카합마`). 전권 693회·58쪽.
        """
        assert decode("⠼⠉⠚⠸⠋⠚⠃⠑") == "30|6025"
        assert decode("⠼⠋⠙⠸⠛⠚⠙⠛⠸⠚⠚⠚⠚") == "64|7047|0000"
        assert decode("⠼⠑⠂⠛⠚⠚") == "5,700"      # 규정 자릿점은 종전대로 쉼표

    def test_수_안의_드러냄표가_수를_끊지_않는다(self) -> None:
        """제35항 드러냄표는 폭이 0인 표시다 — 수 안에 있으면 토큰이 갈려 뒤가 글자로 샜다.

        `47⟦2⟧1조`(⠼⠙⠛⠠⠤⠃⠤⠄⠁⠨⠥)가 `47ba조` 로 나갔다. 실측 89회·36쪽.
        """
        assert decode("⠼⠙⠛⠠⠤⠃⠤⠄⠁⠨⠥") == "4721조"
        assert decode("⠠⠤⠈⠥⠨⠕⠤⠄") == "고지"     # 한글 드러냄표는 종전대로

    def test_홀로_선_세로선을_읽는다(self) -> None:
        """표·그래프의 세로선 ⠸ — 글자가 아니라 도형이다.

        역맵에 없어 ⠸ 가 미해독으로 그대로 샜다(전권 726회·57쪽).
        앞뒤가 모두 경계일 때만 본다 — 붙은 ⠸ 는 두 셀 기호·UEB 약자의 앞 셀이다.
        """
        assert decode("⠀⠀⠿⠉⠉⠀⠸⠀⠉⠉⠿").count("|") == 1
        assert decode("⠸⠎⠕⠢") == "것임"          # 붙은 ⠸ 는 한글 약자 '것'

    def test_대문자_구절표로_열린_구간을_읽는다(self) -> None:
        """제28항 [붙임] — 구절표 ⠠⠠⠠ … 종료표 ⠠⠄ 사이는 한 구간이다.

        ⠠⠠⠠ 는 줄임표 `……` 와 같은 셀이라 긴-셀 매칭이 먼저 먹어 런이 시작조차
        못 했다(`……a, _b, _날 _파`). **닫는 표까지 로마자 셀만 있을 때**만 구절로
        본다 — 뒤가 낱자라는 것만으로 가르면 `……나는 갈매기` 가 `CCZ 갈매기` 로 깨진다.
        """
        assert decode("⠠⠠⠠⠊⠂⠀⠊⠊⠂⠀⠊⠊⠊⠠⠄") == "I, II, III"
        assert decode("⠠⠠⠠⠁⠂⠀⠰⠃⠂⠀⠰⠉⠂⠀⠰⠙⠠⠄") == "A, B, C, D"
        assert decode("⠠⠠⠠⠓⠉⠕⠰⠼⠉⠘⠔⠠⠄") == "HCO_3^-"

    def test_줄임표는_그대로_둔다(self) -> None:
        """⠠⠠⠠ 뒤에 한글이 오면 줄임표다 — 전권 실측 7,383회 중 6,416회가 이쪽이다."""
        assert decode("⠠⠠⠠⠉⠉⠵⠀⠫⠂⠑⠗⠈⠕").startswith("……")

    def test_줄표에서_닫히는_구간을_읽는다(self) -> None:
        """제33항 — `, : ; ―` 는 로마자 종료표 **없이** 구간을 닫는다.

        종료표만 증거로 요구하면 규정 예문 `Hedy Lamarr―미국의 여배우`가
        `Hedy 싹우얘—미국의`로 깨진다(둘째 낱말이 문맥을 잃는다).
        ⠤⠤(줄표)는 UEB 약자 com(⠤)과 첫 셀이 같아 약자 가지보다 먼저 봐야 한다.
        """
        got = decode("⠴⠠⠓⠫⠽⠀⠠⠇⠁⠍⠜⠗⠤⠤⠑⠕⠈⠍⠁⠺")
        assert got.startswith("Hedy Lamarr")

    def test_수식_여는_소괄호를_구간_끝으로_보지_않는다(self) -> None:
        """⠦ 는 물음표이자 **수식 여는 소괄호**다(`P(0≤Z≤z)`).

        뒤가 수표·숫자면 문장 부호가 아니므로 구간을 닫지 않는다 — 받아 주면
        표준정규분포표 머리가 `)z`로 깨졌다(전권 실측 13쪽).
        """
        assert decode("⠴⠵⠀⠀⠠⠏⠦⠼⠚⠖⠖⠠⠵⠖⠖⠵⠴") == "z  P(0≤Z≤z)"


class TestPieupFinalAndWrapParens:
    """받침 ㅍ / 감쌈 붙임표 — 같은 셀이 두 뜻을 갖는 자리 (2026-08-06).

    · ⠲ = 마침표이자 받침 ㅍ. 위치로 가르면 닫는 따옴표 앞에서 틀린다
      (`나타난다.’` → `나타난닾’`). 실제로 쓰이는 받침 ㅍ 음절 목록으로 가른다.
    · ⠤…⠤ = 도서 관행의 괄호 감쌈((가) → ⠤가⠤). 말 중간에 박힌 것도 되돌린다.
    실측 600요소: 완전일치 42.2% → 47.3%, 글자 어긋남 16.8% → 15.6%.
    """

    @staticmethod
    def _round(text: str) -> str:
        from app.ai.braille.translator import translate_tagged_text
        from app.utils.braille_back import decode
        return decode(translate_tagged_text(text))

    @pytest.mark.parametrize("word", ["높다", "앞으로", "깊이", "덮개", "옆으로", "숲이", "싶다"])
    def test_받침_ㅍ이_마침표로_깨지지_않는다(self, word: str) -> None:
        assert self._round(word) == word

    @pytest.mark.parametrize("text", ["문장이다.", "나타난다.’", "끝났다. 그리고"])
    def test_진짜_마침표는_그대로(self, text: str) -> None:
        assert self._round(text) == text

    def test_말_중간_감쌈_붙임표를_괄호로(self) -> None:
        assert self._round("생쥐(가)에서") == "생쥐(가)에서"

    @pytest.mark.parametrize("text", ["‘-더-’", "x-5-2"])
    def test_진짜_붙임표는_괄호로_바꾸지_않는다(self, text: str) -> None:
        assert "(" not in self._round(text)


class TestSequenceBrace:
    """수열 묶음표 — 「수학 점자」 제24항 "수열({aₙ})은 7A;N7으로 적는다".

    ⠶ 는 여는 중괄호와 닫는 중괄호가 같은 점형이라 역맵이 둘 다 `{` 로 편다.
    이 꼴에서만 짝이 분명하므로 닫는 쪽을 `}` 로 낸다.
    실측(전권 18,892쪽): 202회·50쪽, 서로 다른 꼴 넷이 전부 수열이다.
    """

    @staticmethod
    def _d(raw: str) -> str:
        from app.utils.braille_back import decode
        return decode(raw)

    @pytest.mark.parametrize("raw,want", [
        ("⠶⠁⠰⠝⠶", "{a_n}"),
        ("⠶⠃⠰⠝⠶", "{b_n}"),
        ("⠶⠠⠎⠰⠝⠶", "{S_n}"),      # 대문자표가 안쪽에 낀 꼴
        ("⠶⠁⠰⠝⠶⠐", "{a_n},"),
    ])
    def test_수열은_중괄호로_닫는다(self, raw: str, want: str) -> None:
        assert self._d(raw) == want

    @pytest.mark.parametrize("raw,want", [
        ("⠰⠝⠈⠳⠚⠣⠱⠌⠊⠲", "체결하였다."),
        ("⠨⠾⠰⠕⠇", "전치사"),
    ])
    def test_아래첨자표_뒤_낱자는_한글로_남는다(self, raw: str, want: str) -> None:
        """⠰+낱자는 초성 ㅊ(체·채·추·치…)과 같은 셀이다.

        전권 실측 39,591건 중 93.2%가 한글이라 첨자로 넓히면 본문을 먹는다 —
        묶음표 안으로만 한정한 이유다.
        """
        assert self._d(raw) == want


class TestFunctionNotation:
    """함수 표기 — 「수학 점자」 제45항 `y=f(x)` = `Y33F8X0`.

    `8`·`0` 은 여는·닫는 소괄호 ⠦·⠴ 다. 수표도 관계 기호도 없어 종전에는 TEXT 로
    떨어졌고, ⠦ 가 여는 큰따옴표라 `f(x)` 가 `캍옥”` 으로 나갔다(전권 3,210회·551쪽).
    """

    @staticmethod
    def _d(raw: str) -> str:
        from app.utils.braille_back import decode
        return decode(raw)

    @pytest.mark.parametrize("raw,want", [
        ("⠋⠦⠭⠴", "f(x)"),
        ("⠛⠦⠭⠴", "g(x)"),
        ("⠧⠦⠞⠴", "v(t)"),
        ("⠋⠦⠼⠁⠴", "f(1)"),
        ("⠋⠦⠭⠴⠒⠒⠼⠚", "f(x)=0"),
    ])
    def test_함수는_괄호로_읽는다(self, raw: str, want: str) -> None:
        assert self._d(raw) == want

    def test_쌍점은_곱셈점이_아니다(self) -> None:
        """⠐⠂ 는 쌍점이다 — 수식 경로에 없어 `f(x)·,` 로 나갔다(107회·65쪽)."""
        assert self._d("⠋⠦⠭⠴⠐⠂") == "f(x):"

    def test_닫는_괄호가_도보다_먼저다(self) -> None:
        """°(제50항 `0d`)의 앞 셀이 닫는 소괄호와 같다. 열린 괄호가 있으면 닫는 쪽이 먼저다."""
        assert self._d("⠋⠦⠭⠴⠙⠭⠢") == "f(x)dx+"
        assert self._d("⠋⠦⠼⠊⠚⠴⠙⠴") == "f(90°)"      # 도는 수 뒤에 온다

    def test_극한은_표에서_잡는다(self) -> None:
        """제51항 `lim;x`(⠇⠊⠍⠰⠭)는 한글 `사두촉` 으로 깨끗이 풀려 꼬리 가드가 물었다."""
        assert self._d("⠋⠦⠭⠴⠒⠒⠇⠊⠍⠰⠭") == "f(x)=lim_{x}"

    @pytest.mark.parametrize("raw,want", [
        ("⠦⠄⠫⠠⠴", "(가)"),
        ("⠦⠄⠼⠃⠠⠴", "(2)"),
        ("⠑⠦⠣⠉⠥⠴⠈⠥", "맡아놓고"),   # 괄호 안에 관행 제곱 ⠣ 를 안 넣은 이유
    ])
    def test_한글_괄호는_그대로(self, raw: str, want: str) -> None:
        assert self._d(raw) == want

class TestRangeUpperLimit:
    """적분·총합의 범위 — 「수학 점자」 제25항(총합)·제57항(정적분).

    두 조항 다 "범위의 시작은 `;`으로 하고 **끝은 한 칸을 띄어 쓴다**" 라 정한다.
    위끝이 따로 떨어진 토큰이라 홑 낱자로 서면 한글로 읽혔다 — `Σ_k=1 n` 의 ⠝ 가 `에`.
    전권 실측: `' ' -> '^'` 872회·141쪽 · `'을' -> '∫'` 799회·119쪽.
    """

    @staticmethod
    def _d(raw: str) -> str:
        from app.utils.braille_back import decode
        return decode(raw)

    @pytest.mark.parametrize("raw,want", [
        ("⠠⠨⠎⠰⠅⠒⠒⠼⠁⠀⠝", "Σ_k=1^n"),
        ("⠠⠨⠎⠰⠅⠒⠒⠼⠁⠀⠼⠛", "Σ_k=1^7"),
        ("⠮⠰⠁⠀⠃", "∫_a^b"),
        ("⠮⠰⠔⠼⠃⠀⠼⠃", "∫_-2^2"),
        ("⠮⠰⠨⠁⠀⠨⠃", "∫_α^β"),
    ])
    def test_위끝은_앞에_붙는다(self, raw: str, want: str) -> None:
        assert self._d(raw) == want

    def test_한글은_안_먹는다(self) -> None:
        """⠮ 는 약자 `을` 이라 홀로 18,156회다. 아래끝까지 범위 꼴이어야 수식으로 본다."""
        assert self._d("⠮⠰⠍⠁⠉⠡") == "을축년"


class TestPermutationCombination:
    """순열·조합 — 「수학 점자」 제62항 2~5.

    두 인자가 묶음 괄호 안에서 **한 칸으로 갈린다**(`,C(N`R)`). 라우터가 그 칸에서
    토큰을 쪼개 `₃C₂` 가 `C(3 2)` 로 나갔다 — 묵자는 `_3C_2` 다.
    """

    @staticmethod
    def _d(raw: str) -> str:
        from app.utils.braille_back import decode
        return decode(raw)

    @pytest.mark.parametrize("raw,want", [
        ("⠠⠉⠷⠼⠉⠀⠼⠃⠾", "_3C_2"),          # 조합 (제62항 3)
        ("⠠⠏⠷⠼⠉⠀⠼⠁⠾", "_3P_1"),          # 순열 (제62항 2)
        ("⠠⠨⠏⠷⠼⠛⠀⠼⠃⠾", "_7Π_2"),        # 중복순열 (제62항 4)
        ("⠠⠓⠷⠼⠛⠀⠼⠃⠾", "_7H_2"),          # 중복조합 (제62항 5)
        ("⠠⠉⠷⠝⠀⠗⠾", "_nC_r"),            # 인자가 낱자면 수표가 없다
        ("⠠⠉⠷⠼⠉⠀⠼⠁⠾⠒⠒⠼⠉", "_3C_1=3"),
    ])
    def test_두_인자를_첨자로_편다(self, raw: str, want: str) -> None:
        assert self._d(raw) == want

    @pytest.mark.parametrize("raw,want", [
        ("⠴⠠⠉⠷⠋⠑⠑⠲", "Coffee"),          # ⠷ 는 UEB 약자 `of` — 짝 맞는 ⠾ 를 요구한다
        ("⠠⠓⠷⠍⠁⠝⠝⠲", "톤욱에에."),
    ])
    def test_짝이_없으면_안_본다(self, raw: str, want: str) -> None:
        assert self._d(raw) == want
