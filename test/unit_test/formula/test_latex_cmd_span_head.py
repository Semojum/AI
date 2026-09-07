r"""수식 구간이 **앞머리 LaTeX 명령에서 시작**해야 한다 (원장 R-71).

종전 `_LATEX_SPAN_RE` 는 열다섯 개 명령 이름표로만 구간을 열었다. 이름표에 없는 명령이
식 앞머리에 있으면 구간이 그 뒤에서 열려, 앞머리가 로마자로 점역돼 나갔다 —
`\overline{\mathrm{PI}}=…` → `⠸⠡⠴⠕⠧⠻⠇⠔⠑⠦⠂`(= "\overline{" 열 셀).

정답은 「한국 점자 규정」 **제35항**(재추출 3728행) 선분 ⠈⠉ + [붙임] 대문자 단어표 ⠠⠠.
"""
from app.ai.braille import inline_math as IM
from app.ai.braille.translator import translate_plain
from app.utils.braille_back import decode


def test_이름표에_없는_명령도_구간을_연다():
    w = IM.wrap(r"\overline{\mathrm{PI}}=\overline{\mathrm{IQ}}=t")
    assert w.startswith("<!수식>") and "\\overline" not in decode(translate_plain(w))


def test_선분은_제35항_점형으로_나간다():
    b = translate_plain(r"\overline{\mathrm{PI}}")
    assert b == "⠈⠉⠠⠠⠏⠊"          # ⠈⠉ 선분(제35항) + ⠠⠠ 대문자 단어표([붙임])


def test_깊이0_한글은_수식이_안_먹는다():
    # 이름표를 넓히면서 줄 끝까지 삼키면 조사 '의' 가 수식에 먹힌다.
    d = decode(translate_plain(r"선분 \overline{AB}의 길이는 5이다."))
    assert "의 길이는" in d


def test_중괄호_안_한글은_그대로_수식이다():
    w = IM.wrap(r"\frac{\text{득표수}}{\text{유효 투표수}} \times 100")
    assert w.count("<!수식>") == 1


def test_평범한_한글_본문은_안_건드린다():
    assert "<!수식>" not in IM.wrap("가나다 라마 바사입니다.")
