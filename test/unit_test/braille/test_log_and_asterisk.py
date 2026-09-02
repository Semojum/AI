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
