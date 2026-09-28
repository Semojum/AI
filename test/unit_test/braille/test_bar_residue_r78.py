"""원장 R-78 — 세로선 `|`. 규정 제71항 ⠸⠳ · 주자 2027 gold 도 ⠸⠳ · 지금은 **채택 보류**(빈칸으로 나간다).

고치는 순간 아래 xfail 이 XPASS 로 깨진다 — 그때 원장 R-78 의 상태도 같이 고친다.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402


def _body(text: str) -> str:
    return "\n".join(translate_body(text)[0])


@pytest.mark.xfail(strict=True, reason="원장 R-78 채택 보류 — 치환을 빼면 꼬리말·제목의 가구 구분자까지 ⠸⠳ 가 돼 전수 A/B 가 나빠졌다")
def test_구분자_세로선은_규정형():
    # 2027 언어와 매체 기사 머리 — gold `⠐⠂⠼⠉⠚⠀⠸⠳⠀⠠⠍⠨⠻`.
    assert "⠐⠂⠼⠉⠚⠀⠸⠳⠀⠠⠍⠨⠻" in _body("최초 입력 2026. 5. 25. 14:30 | 수정 2026. 5. 26.")


def test_평문_절댓값은_수식_경로가_가져간다():
    # 「수학 점자」 제21항 `|x|` = ⠳⠭⠳. R-78 규칙과 안 겹치는 근거다.
    assert "⠳⠁⠳" in _body("① 두 함수의 최댓값은 |a|, 최솟값은 -|a|이다.")
