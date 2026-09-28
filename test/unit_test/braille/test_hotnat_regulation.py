"""#909 — 홑낫표 「 」는 규정형 ⠐⠦ … ⠴⠂ 로 적는다(「한국 점자 규정」 제49항 문장 부호표).

book 모드가 「…」 를 ‘…’(작은따옴표 ⠠⠦ … ⠴⠄)로 바꿔 냈다. 주자 2027 gold 는 규정형이다
(묵자 「 가 있는 81쪽: 묵자 「 166 · gold ⠐⠦ 208). 구판 gold 는 ‘ ’ 였다 — 판본이 갈린 자리.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def test_규정_예문_축배의_노래():
    # 재추출 2267행 — 규정 원문 BRF 의 백틱은 빈칸이다.
    assert _body("이 곡은 베르디가 작곡한 「축배의 노래」이다.") == \
        ascii_to_unicode('o`@xz`^n"[io$`.a@xj3`"8;ma^rw`cu"r01oi4', backtick="space")


def test_2027_gold_작품_제목():
    # dv2027 EBS-E26-004 body p0196 gold 셀 그대로.
    assert "⠐⠦⠵⠚⠠⠍⠺⠀⠈⠕⠏⠒⠴⠂⠮" in _body("「은하수의 기원」을 보면")


def test_사전_뜻풀이_번호():
    # dv2027 EBS-E26-004 body p0018 gold `⠤⠐⠦⠼⠁⠴⠂⠴⠄` — 작은따옴표 안의 「1」.
    assert "⠐⠦⠼⠁⠴⠂⠴⠄" in _body("③ ‘재다³-「1」’은")
