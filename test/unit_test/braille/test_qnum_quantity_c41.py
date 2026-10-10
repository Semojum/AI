"""원장 C-41 부록3 — 수량 표기는 문항 번호가 아니다(문항 번호 마침표 `_QNUM_RE` 오발동).

규정 제44항 "숫자 뒤에 이어 나오는 한글의 띄어쓰기는 묵자를 따른다" 예문 `5 개`·`8 상자`,
제69항 [붙임 1·2] 예문 `1 μm는`·`5 %와`. 기대값은 규정 원문 BRF(백틱 = 빈칸)에서 옮겼다.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[3]))

from app.ai.braille.translator import translate_body  # noqa: E402
from app.utils.braille_ascii import ascii_to_unicode  # noqa: E402


def _b(text: str) -> str:
    return "\n".join(translate_body(text)[0])


def test_제44항_숫자_빈칸_단위명사는_묵자대로():
    assert _b("5 개") == ascii_to_unicode("#e`@r", backtick="space")      # ⠼⠑⠀⠈⠗
    assert _b("8 상자") == ascii_to_unicode("#h`l7.", backtick="space")   # ⠼⠓⠀⠇⠶⠨


def test_제69항_단위기호_앞_숫자에_마침표를_안_붙인다():
    # 규정 `#e`0p`v…` = ⠼⠑⠀⠴⠏⠀⠧ — 번호 마침표 ⠲ 가 없다.
    assert _b("5 %와 6 %의 차이는 1 %p다.").startswith("⠼⠑⠀⠴⠏⠀⠧")
    assert not _b("1 μm는 1,000분의 1 mm이다.").startswith("⠼⠁⠲")


def test_단위명사와_글자가_같은_문항_번호는_그대로():
    # 명나라 단원 소제목(gold 온점, 주자 val 3곳) — 단위 명사 목록으로 넓게 끄면 이게 깨진다.
    assert _b("4 명의 건국과 동아시아 질서의 재편").startswith("⠼⠙⠲")
    assert _b("2 다음은 어느 학생의 필기 내용이다.").startswith("⠼⠃⠲")


def test_비교_기호가_띄어_따라오면_식이다():
    # EBS-E26-009 gold ans p0032 · p0025 그대로 — 종전엔 `0.` 으로 나갔다.
    assert _b("0 < A < π에서 sin A > 0") == "⠼⠚⠔⠔⠠⠁⠔⠔⠨⠏⠀⠀⠝⠠⠎⠀⠀⠖⠎⠠⠁⠢⠢⠼⠚"
    assert _b("0 ≤ x ≤ a에서 함수") == "⠼⠚⠖⠖⠭⠖⠖⠁⠀⠀⠝⠠⠎⠀⠚⠢⠠⠍"


def test_붙어_오는_화살괄호는_문항_번호_그대로():
    # 여섯째 가드가 일부러 남긴 자리(gold 마침표) — 비교 가드가 먹지 않는다.
    assert _b("5 <보기>의 내용").startswith("⠼⠑⠲⠀")


def test_영어_줄_번호는_묵자대로_마침표를_안_붙인다():
    # #1197 — 영어 교재의 낱말 · 문항 번호. gold HS-REF-T26-013 body p0147 그대로.
    assert _b("1 through 3.") == "⠼⠁⠀⠐⠹⠀⠼⠉⠲"
    assert _b("1 hello  <!밑줄>").startswith("⠼⠁⠀")        # 태그 이름(`밑줄`)의 한글은 안 센다
    assert _b("1\nhello world").startswith("⠼⠁\n")         # 번호가 제 줄에 홀로 와도


def test_한글이_든_줄의_번호는_그대로():
    assert _b("3 DNA의 구조를 보자").startswith("⠼⠉⠲")
