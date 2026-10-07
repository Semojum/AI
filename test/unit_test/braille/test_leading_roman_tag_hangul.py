"""태그 이름의 한글을 본문 한글로 세지 않는다 — `_fix_leading_roman` (이슈 #1173).

태그 이름(`<!밑줄>`·`<!굵은>`·`<!네모>`, `$…$` 가 바뀐 `<!수식>`)은 한글이지만 본문이 아니다. 종전에는 이것을 세어 한글 없는 영어 줄을
한영 혼합으로 보고 첫 낱말에 로마자표·종료표를 붙였다(`I want to ___ you.` → ⠴⠠⠊⠲⠀…).
「한국 점자 규정」 제29항(재추출 1496행)은 **국어 문장 안**의 로마자에 로마자표를 적게 한다. 한글 없는 영어 줄은 그 자리가 아니다.
gold 영어책 대문자로 시작하는 한글 없는 영어 줄 6,219 중 첫 토막이 `⠴…⠲` 인 줄은 33(0.5%)이고, 그것도
`Q1.`·`Hello.` 처럼 ⠲ 가 마침표인 자리다(holdout 제외, 2026-10-07 전수).
"""
from app.ai.braille.translator import translate_body


def _br(text: str) -> str:
    return "".join(translate_body(text)[0])


def test_밑줄_태그가_든_영어_줄():
    """gold MS-REF-007 꼴 — 첫 낱말 `I` 에 ⠴…⠲ 가 붙지 않는다."""
    assert _br("I want to <!밑줄> you.").startswith("⠠⠊⠀⠺⠁⠝⠞")


def test_굵은_네모_태그가_든_영어_줄():
    """종전 `⠴⠠⠓⠑⠲⠀…` · `⠴⠠⠮⠲⠀…`."""
    assert _br("He <!굵은>is<!/굵은> tall.").startswith("⠠⠓⠑⠀")
    assert _br("The answer is <!네모>.").startswith("⠠⠮⠀")


def test_수식_태그가_든_좌표_줄():
    """gold EBS-E26-009 ans p0021 `B(π+α, −sin α)` = ⠠⠃⠦… (로마자표 없음). 종전 `⠴⠠⠃⠦⠄⠲`."""
    assert _br("B( $\\pi+\\alpha$ , -sin $\\alpha$ )").startswith("⠠⠃⠦⠄⠀")


def test_진짜_한글이_있으면_종전대로():
    """한영 혼합 줄은 제29항 그대로 로마자표 ⠴ … 종료표 ⠲."""
    assert _br("Korea는 나라다.").startswith("⠴⠠⠅⠕⠗⠑⠁⠲")
