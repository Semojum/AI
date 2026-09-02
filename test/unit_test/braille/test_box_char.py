"""네모 문자 — 규정 제64항 "네모 문자는 _8 0l으로 묶어 나타낸다"(⠸⠦ … ⠴⠇).

정방향은 `translator._TAGS.BOX_CHAR` 가 이 쌍을 낸다. 역방향에 짝이 없어 ⠸ 가 수학표의
log 로 새고 ⠴ 가 로마자표로 읽혀 `log"1l` 이 됐다.
"""
from app.utils.braille_back import decode


def test_네모_문자():
    assert decode("⠸⠦⠼⠁⠴⠇") == "▯1▯"


def test_네모_빈칸():
    # 규정 제73항. 가운데가 공백 셀이라 토큰 분리가 여닫이를 갈라 놓는다 — 줄 단위로 잡는다.
    assert decode("⠸⠦⠀⠴⠇") == "▯▯"


def test_문장_안의_네모_빈칸():
    assert decode("⠈⠕⠸⠦⠀⠴⠇⠺") == "기▯▯의"


def test_제목_앞의_네모_문자():
    assert decode("⠸⠦⠼⠁⠴⠇⠀⠠⠗⠶⠑⠯⠺⠀⠓⠪⠁⠠⠻") == "▯1▯ 생물의 특성"
