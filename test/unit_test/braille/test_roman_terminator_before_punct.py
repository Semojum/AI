"""로마자 종료표 자리 — 세그가 부호에서 끊겨 빠지거나 더 붙던 자리 (#944).

기대값은 「한국 점자 규정」 원문 BRF 그대로다(생산 코드로 만들지 않았다). 제품 본문 경로로 잰다.
"""
import pytest

from app.ai.braille.translator import translate_body


def _body(text: str) -> str:
    return "".join(translate_body(text)[0])


@pytest.mark.parametrize("src,want", [
    # 제10항(재추출 523행) — 빈칸 뒤 여는 대괄호 앞에서 로마자 구간이 닫힌다
    ("Roma [ㄹㄹ로마]", "⠴⠠⠗⠕⠍⠁⠲⠀⠦⠆⠸⠂⠸⠂⠐⠥⠑⠰⠴"),
    # 제33항 [다만] — ‘/ - ~’ 는 문장 부호 앞에 로마자 종료표를 적는다
    ("KTX/새마을호/무궁화호", "⠴⠠⠠⠅⠞⠭⠲⠸⠌⠠⠗⠑⠣⠮⠚⠥⠸⠌⠑⠍⠈⠍⠶⠚⠧⠚⠥"),
    ("U-도서관", "⠴⠠⠥⠲⠤⠊⠥⠠⠎⠈⠧⠒"),
    # 제35항 — 로마자와 숫자가 이어 나오면 종료표를 적지 않는다(붙임표가 끼어도)
    ("2023학년도 수능 D-100일 학습 전략",
     "⠼⠃⠚⠃⠉⠀⠚⠁⠉⠡⠊⠥⠀⠠⠍⠉⠪⠶⠀⠴⠠⠙⠤⠼⠁⠚⠚⠕⠂⠀⠚⠁⠠⠪⠃⠀⠨⠾⠐⠜⠁"),
])
def test_규정_예문(src, want):
    assert _body(src) == want


@pytest.mark.parametrize("src,absent", [
    # `4000 kcal/년` 은 제69항 보류건으로 여기 있다가 #958 에서 풀렸다 — 규정 `80 ㎞/시` = ⠴⠅⠍⠲⠸⠌⠠⠕ 대로
    #   종료표를 적는다(test_latin_unit_958.py).
    ("생성량(mL/분)", "⠇⠲⠸⠌"),
    ("KTX/SRT", "⠭⠲⠸⠌"),            # 빗금 뒤도 로마자면 한 구간
])
def test_좁힌_자리(src, absent):
    assert absent not in _body(src)
