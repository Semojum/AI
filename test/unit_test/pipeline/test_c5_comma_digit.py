"""C5 · 쉼표 바로 뒤 숫자에 수표가 빠지던 것 (배포 차단 조건).

★ 이 테스트가 `test_rule_engine.py` 와 **다른 층**이라는 게 요점이다.
  규칙 엔진 단위 테스트 83건은 전수 통과하는데 실지면에서 이 오류가 났다.
  단위 테스트는 규칙 엔진을 직접 태우고, 이건 **실지면이 파이프라인을 지나며** 생긴다.
  진입점이 다르면 다른 층에서 잡아야 한다(메모리 `verify-on-every-entrypoint`).

원인은 braillify 2.0.0 이다. `,4문단` 에 수표를 안 붙인다 —
`4문단`·`가나다4문단`·`하여, 4문` 은 붙는데 **쉼표 바로 뒤만** 빠진다.
수표가 빠지면 숫자 점형이 한글로 읽힌다: `65세 이상` → `카마세이상`.
**점역사가 아니라 독자가 틀리게 읽는다.**
"""
import pytest

from app.ai.braille.number_sign import has_number_sign
from app.ai.braille.translator import translate_tagged_text


def _cells(src: str) -> str:
    return translate_tagged_text(src)


class TestCommaDigitNumberSign:
    # M018 런타임 플래그에서 나온 **실물** — 재현 케이스가 곧 회귀 검사다(pm 지시)
    @pytest.mark.parametrize("src", [
        "관련하여,4문단에서공연포스터를구체적으로분석한후",     # 005 body p0157
        "관련하여,4문단에서모차르트가언급한내용을직접인용",     # 005 body p0157
        "관련하여,4문단에서의문문형식을활용하여",             # 005 body p0157
        "논의에덧붙여,65세이상의지역어르신들이",              # 005 body p0169
        "제재를 소개할 때에는,2.4밀리그램이라고 하면",         # 005 body p0019 꼴
    ])
    def test_실물_다섯건에_수표가_붙는다(self, src):
        cells = _cells(src)
        assert has_number_sign(src, cells), f"수표가 빠졌다: {src!r} → {cells!r}"

    @pytest.mark.parametrize("src", [",4문단", "가,4나", "하여,65세"])
    def test_쉼표_뒤_숫자(self, src):
        assert has_number_sign(src, _cells(src)), f"수표가 빠졌다: {src!r}"

    @pytest.mark.parametrize("src", ["4문단", "가나다4문단", "하여, 4문", "7시간", "5월"])
    def test_종전에도_되던_자리는_그대로(self, src):
        assert has_number_sign(src, _cells(src))


class TestThousandsSeparatorUntouched:
    """★ 자릿점을 깨뜨리면 안 된다(제41항). 조건을 단순화하면 여기서 잡힌다.

    끊는 조건은 **앞이 숫자가 아닐 때만**이다. `(?<!\\d)(?<=,)` 로 쓰면 두 lookbehind 가
    같은 위치를 봐서 부정 lookbehind 가 항상 참이 되고 `1,000` 이 ⠼⠁⠐⠼⠚⠚⠚ 로 깨진다.
    처음 그렇게 썼다가 검증에서 잡았다 — 그래서 이 테스트가 있다.
    """
    @pytest.mark.parametrize("src,expect_marks", [
        ("1,000원", 1), ("12,345개", 1), ("3,4번", 1), ("1,000,000", 1),
    ])
    def test_자릿점은_수표가_하나뿐이다(self, src, expect_marks):
        cells = _cells(src)
        assert cells.count("⠼") == expect_marks, f"자릿점이 깨졌다: {src!r} → {cells!r}"
        assert "⠂" in cells, f"자릿점 ⠂ 가 사라졌다: {src!r} → {cells!r}"

    @pytest.mark.parametrize("src", ["안녕, 반가워", "가나다", "쉼표, 뒤에 글자"])
    def test_숫자가_아니면_안_건드린다(self, src):
        assert "⠼" not in _cells(src)
