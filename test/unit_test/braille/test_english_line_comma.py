"""한글 없는 영어 줄의 구간 밖 쉼표 → 통일영어점자 ⠂ (이슈 #1214).

「한국 점자 규정」 제7·28항(영어는 통일영어점자) · 제33항(쉼표는 두 규정 점형이 다르다).
기대값은 gold 영어책 줄 그대로(책/부분/쪽 · 줄 번호는 쪽 안 0부터). 한글 줄 쉼표는 종전대로 ⠐.
"""
import pytest

from app.ai.braille.translator import translate_body


def _br(text: str) -> str:
    return "".join(translate_body(text)[0]).strip("⠀")


@pytest.mark.parametrize("text,cells", [
    # EBS-E26-008 ans p0002 줄 103 — 줄 끝 쉼표
    ("risk of an accident. For your safety,", "⠗⠊⠎⠅⠀⠷⠀⠁⠝⠀⠁⠒⠊⠙⠢⠞⠲⠀⠠⠿⠀⠽⠗⠀⠎⠁⠋⠑⠞⠽⠂"),
    # EBS-E26-008 ans p0055 줄 70 — 숫자 뒤 쉼표
    ("A256, but I can't find my bag.", "⠠⠁⠼⠃⠑⠋⠂⠀⠃⠀⠠⠊⠀⠉⠄⠞⠀⠋⠔⠙⠀⠍⠽⠀⠃⠁⠛⠲"),
    # EBS-E26-008 ans p0153 줄 44 — 따옴표 앞 쉼표
    ('actively ask questions like, "Why did the', "⠁⠉⠞⠊⠧⠑⠇⠽⠀⠁⠎⠅⠀⠐⠟⠎⠀⠇⠂⠀⠦⠠⠱⠽⠀⠙⠊⠙⠀⠮"),
])
def test_영어_줄_쉼표(text, cells):
    assert _br(text) == cells


def test_자릿점은_그대로():
    assert _br("It costs 1,000 won, a lot.").startswith("⠠⠭⠀⠉⠕⠌⠎⠀⠼⠁⠂⠚⠚⠚")


@pytest.mark.parametrize("text", ["나는 사과, 배를 좋아한다.", "1, 2, 3"])
def test_한글_줄과_숫자_나열은_종전대로(text):
    assert "⠐⠀" in _br(text)        # 한글 쉼표 ⠐ (제49항)
