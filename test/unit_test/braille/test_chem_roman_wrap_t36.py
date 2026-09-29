"""T36 ②-b 헛 로마자표 갈래 — 연산·화살표가 든 화학식은 로마자표로 감싸지 않는다.

과학 점자 제6항(재추출 4423행): 국어 문장 안에 연산·비교 기호, 화살표 등이 포함된 식은 앞뒤를 두 칸씩
띄우고 식에 포함된 로마자는 로마자표를 적지 않는다 — 예문 `C + O₂ → CO₂이다` =
``,,,C`5`O;#b`3o`CO;#b,'``oi4`. 화학식 하나(`H₂O와` 제7항 1호 `0,h;#b,o4v`)는 감싼다.
"""
from app.ai.braille.kor_math_rules import convert_latex
from app.ai.braille.translator import translate_body


def test_반응식은_로마자표_없이():
    out = convert_latex(r"2\mathrm{H}_{2} + \mathrm{O}_{2} \rightarrow 2\mathrm{H}_{2}\mathrm{O}")
    assert not out.startswith("⠴") and not out.endswith("⠲")


def test_문장_속_반응식은_규정_예문과_같다():
    out = translate_body("이산화탄소의 생성 반응식은 $\\mathrm{C} + \\mathrm{O}_{2} \\rightarrow \\mathrm{CO}_{2}$이다.")[0][0]
    assert "⠀⠀⠠⠠⠠⠉⠀⠢⠀⠕⠰⠼⠃⠀⠒⠕⠀⠉⠕⠰⠼⠃⠠⠄⠀⠀⠕⠊⠲" in out


def test_화학식_하나는_감싼다():
    assert convert_latex(r"\mathrm{H}_{2}\mathrm{O}") == "⠴⠠⠓⠰⠼⠃⠠⠕⠲"


def test_글_경로_반응식은_화살표에서_안_끊긴다():
    # 글 경로(평문 유니코드)도 제품 경로와 같은 한 식으로 — 재추출 4427~4428행 · 4400행 · 4832행
    assert "⠀⠀⠠⠠⠠⠉⠀⠢⠀⠕⠰⠼⠃⠀⠒⠕⠀⠉⠕⠰⠼⠃⠠⠄⠀⠀⠕⠊⠲" in translate_body("이산화탄소의 생성 반응식은 C + O₂ → CO₂이다.")[0][0]
    assert translate_body("2H₂ + O₂ → 2H₂O")[0][0] == "⠼⠃⠠⠓⠰⠼⠃⠀⠢⠀⠠⠠⠠⠕⠰⠼⠃⠀⠒⠕⠀⠼⠃⠐⠓⠰⠼⠃⠕⠠⠄"
    assert translate_body("Ag⁺+ Cl⁻→ AgCl ↓")[0][0] == "⠠⠁⠛⠘⠢⠀⠢⠀⠠⠉⠇⠘⠔⠀⠒⠕⠀⠠⠁⠛⠠⠉⠇⠘⠒⠕"


def test_흐름_화살표는_반응식이_아니다():
    from app.ai.braille.inline_math import chem_chains
    for s in ("Client → 서버: 요청", "Bb → 7 (가) 발현 여자", "㉠ → ㉡+Pᵢ"):
        assert chem_chains(s) == s


def test_반응식_아닌_줄의_수식은_그대로():
    # 화살표가 있어도 반응식 사슬이 아니면 `$…$` 를 풀지 않는다(A/B 001 p039 부작용)
    from app.ai.braille.inline_math import chem_chains
    s = "세포 호흡 → 최종 분해 산물: ㉠, $H_{2}O$."
    assert chem_chains(s) == s
