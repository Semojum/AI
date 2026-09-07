"""단독 ⠸ 는 log 가 아니다 · 겸용 점형 ⠐⠔ 는 별표로 편다.

**⠸** — 규정 제46항은 로그를 두 칸으로 적는다(밑이 숫자 `⠸⠠` · 문자·괄호 `⠸⠰`).
홑 ⠸ 를 log 로 두니 지시부호 자리마다 터져 코퍼스 전수 105,453자가 샜다.

**⠐⠔** — 규정 제60항은 별표(*)와 참고표(※)를 **같은 점형**으로 적는다(구별할 때만
※=⠸⠔). 겸용이라 실측 우세 쪽으로 편다 — 재추출 묵자 1,361쪽에 `*` 630 : `※` 105.
"""
from app.utils.braille_back import decode


def test_두_칸_로그는_읽는다():
    assert decode("⠸⠠⠑⠼⠃").startswith("log_")
    assert decode("⠸⠰⠁⠝").startswith("log_")


def test_홑_지시부호는_log_가_아니다():
    assert "log" not in decode("⠸")


def test_네모_문자가_log_로_안_샌다():
    assert decode("⠸⠦⠼⠁⠴⠇") == "▯1▯"


def test_겸용_점형은_별표로():
    assert decode("⠐⠔") == "*"


def test_밑이_숫자면_내려적기를_숫자로_되돌린다():
    """제46항 1호 — 밑은 수표 없이 내려 적는다(규정 예시 `_,5#b` = log₅2).

    종전에는 내려 적기가 셀 그대로 새어 `log_;6`(log₂6) · `log_=5`(log₃5) 가 나가
    밑을 구분할 수 없었다. 두 자리 밑이 한 자리보다 먼저 걸려야 한다.
    """
    assert decode("⠸⠠⠢⠼⠃") == "log_{5}2"      # 규정 예시
    assert decode("⠸⠠⠆⠼⠋") == "log_{2}6"      # 종전 `log_;6`
    assert decode("⠸⠠⠂⠴⠼⠁⠚") == "log_{10}10"  # 두 자리 밑
    assert decode("⠸⠠⠑⠼⠃").startswith("log_")  # 내려 적기가 아니면 종전대로


def test_밑이_문자면_한_칸이_밑이다():
    """제46항 2호 — `⠸⠰` 뒤 한 칸이 밑이다(규정 예시 `_;AN` = log_a n).

    두 칸만 잡으면 밑 글자가 따로 풀려 한글 약자로 샜다(`⠸⠰⠁⠝` -> `log_그런데`).
    """
    assert decode("⠸⠰⠁⠝").startswith("log_{a}")
    assert decode("⠸⠰⠑⠭").startswith("ln")        # `_;Ex` = ln x — 덮지 않는다
    assert decode("⠸⠰⠷⠼⠃⠘⠼⠃⠾") == "log_(2^2)"    # 괄호 밑은 종전대로
