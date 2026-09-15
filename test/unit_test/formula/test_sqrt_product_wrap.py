"""#877 — 근호 안 곱은 묶음 괄호로 묶는다.

규정 — 「수학 점자」 **제14항 [붙임 2]**(규정 재추출 3615~3618행):
    "근호 안이 분수, 곱, 다항식 등일 때에는 묶음 괄호로 묶어 나타낸다."  보기 `√―xy → >(xy)`
제6항 2호(3110행)도 같은 보기를 든다.

관행 쪽은 **증거가 없다.** 동결 코퍼스 gold 의 근호 중 묶음 괄호를 쓴 것은 4건이고 넷 다
다항식이며, 안 묶은 258건은 전부 `√3` 꼴 단항이다. 근호 안 곱이 gold 에 0건이라
book 모드의 곱 묶음 해제(2026-07-22 A/B)가 이 자리를 잰 적이 없다.
그래서 **두 모드 모두** 규정대로 묶는다.

⚠ 함께 막는 것 — 기각 이력이 지목한 과잉 묶음. `f(x)`·`\\sin x`·`\\sqrt{3}` 같은
**단일 함수값**을 인수 둘로 세면 안 된다(2026-07-22 에 인라인 수식 38건이 이렇게 깨졌다).
"""
import importlib
import os

import pytest

from app.ai.braille import kor_math_rules as k

OPEN = "⠷"

WRAP = [
    (r"\sqrt{xy}", "규정 보기 그대로 — √xy"),
    (r"\sqrt{ab}", "문자 두 개의 곱"),
    (r"\sqrt{2x}", "계수 × 문자"),
    (r"\sqrt{2\times 3}", "곱셈 기호를 쓴 곱"),
    (r"\sqrt{2\pi}", "계수 × 그리스 문자"),
    (r"\sqrt{2\sqrt{3}}", "계수 × 근호"),
    (r"\sqrt{x+y}", "다항식 — 종전에도 묶었다"),
    (r"\sqrt[3]{ab}", "세제곱근도 같은 조항이다"),
]

BARE = [
    (r"\sqrt{3}", "단일 수"),
    (r"\sqrt{10}", "두 자리 수는 수 하나다"),
    (r"\sqrt{x}", "단일 문자"),
    (r"\sqrt{x^{2}}", "거듭제곱은 곱이 아니다"),
    (r"\sqrt{\pi}", "단일 명령"),
    (r"\sqrt{f(x)}", "함수값 — 기각 이력이 지목한 과잉 묶음"),
    (r"\sqrt{\sin x}", "괄호 없는 함수 적용"),
    (r"\sqrt{\sin(x)}", "괄호 있는 함수 적용"),
    (r"\sqrt{\sqrt{3}}", "중첩 근호는 구성 하나다"),
    (r"\sqrt{\overline{AB}}", "\\cmd{…} 는 이름이 무엇이든 구성 하나"),
]


class TestBookMode:
    """기본값(book)에서도 묶는다 — 규정이 근호 자리를 따로 집어 말한다."""

    @pytest.mark.parametrize("latex, 왜", WRAP)
    def test_곱은_묶는다(self, latex, 왜) -> None:
        out = k.convert_latex(latex)
        assert OPEN in out, f"{왜}: {latex} → {out!r} 에 묶음 괄호가 없다"

    @pytest.mark.parametrize("latex, 왜", BARE)
    def test_단항은_안_묶는다(self, latex, 왜) -> None:
        out = k.convert_latex(latex)
        assert OPEN not in out, f"{왜}: {latex} → {out!r} 에 묶음 괄호가 붙었다"

    def test_규정_보기와_같은_셀이_나온다(self) -> None:
        """제14항 [붙임 2] `√―xy → >(xy)` — BRF `>` `(` `)` = ⠜ ⠷ ⠾."""
        assert k.convert_latex(r"\sqrt{xy}") == "⠜⠷⠭⠽⠾"


class TestRegulationMode:
    @pytest.fixture()
    def regulation(self):
        os.environ["BRAILLE_STYLE"] = "regulation"
        importlib.reload(k)
        yield k
        os.environ.pop("BRAILLE_STYLE", None)
        importlib.reload(k)

    @pytest.mark.parametrize("latex, 왜", WRAP)
    def test_곱은_묶는다(self, regulation, latex, 왜) -> None:
        assert OPEN in regulation.convert_latex(latex), 왜

    @pytest.mark.parametrize("latex, 왜", BARE)
    def test_단항은_안_묶는다(self, regulation, latex, 왜) -> None:
        # 규정 모드도 같다 — 과잉 묶음은 규정이 요구한 것이 아니다.
        assert OPEN not in regulation.convert_latex(latex), 왜


class TestOtherCallSitesUnchanged:
    """근호 밖에서는 book 모드의 곱 묶음 해제가 그대로다(2026-07-22 A/B 를 되돌리지 않는다)."""

    def test_분수_분자의_곱은_book_에서_안_묶는다(self) -> None:
        assert not k._needs_wrap("xy")
        assert k._needs_wrap("xy", radicand=True)
