"""대문자 연속 뒤 소문자 — 통일영어점자 대문자 단어표 ⠠⠠ + 대문자 종료표 ⠠⠄ (#934).

기대값은 2027 gold 실물이다(생산 코드로 만들지 않았다).
  · dev-2027 EBS-E26-001 body p0116 유전자형 `ABd` · val-2027 EBS-E26-005 body p0078 `SDGs`
원소 기호로 끊기는 낱말(`HCl`)은 「과학 점자」 제1항대로 원소마다 ⠠ 다(역점역 왕복 시험이 지킨다).
"""
import pytest

from app.ai.braille import eng_braille


@pytest.mark.parametrize("word,gold", [
    ("ABd", "⠠⠠⠁⠃⠠⠄⠙"),
    ("SDGs", "⠠⠠⠎⠙⠛⠠⠄⠎"),
    ("AbD", "⠠⠁⠃⠠⠙"),          # 홑 대문자는 ⠠ 하나
    ("mV", "⠍⠠⠧"),
    ("HCl", "⠠⠓⠠⠉⠇"),         # 원소 기호 이음은 종전대로
])
def test_대문자_연속_뒤_소문자는_종료표로_닫는다(word, gold):
    assert eng_braille.translate(word) == gold
