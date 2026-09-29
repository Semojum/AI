"""「한글 점자」 제74항 — 컴퓨터 점자(URL·이메일)는 통일영어점자로. 기대값은 재추출 2960~2965행."""
from app.ai.braille.translator import translate_body


def test_URL():
    # `0https3_/_/www4kor1n4go4kr4oi4` — 쌍점 ⠒ · 빗금 ⠸⠌ · 점 ⠲ · `go` 는 단어 약자 없이
    out = translate_body("국립국어원의 누리집 주소는 https://www.korean.go.kr이다.")[0][0]
    assert out.endswith("⠴⠓⠞⠞⠏⠎⠒⠸⠌⠸⠌⠺⠺⠺⠲⠅⠕⠗⠂⠝⠲⠛⠕⠲⠅⠗⠲⠕⠊⠲")


def test_이메일():
    # `0gre5p>k` + `#gaej@akorea4kr4oi4`(줄 이음 표시 ⠐ 는 조판 몫) — `@` 뒤에 로마자표를 다시 열지 않는다
    out = translate_body("그의 이메일 주소는 greenpark7150@korea.kr이다.")[0][0]
    assert out.endswith("⠴⠛⠗⠑⠢⠏⠜⠅⠼⠛⠁⠑⠚⠈⠁⠅⠕⠗⠑⠁⠲⠅⠗⠲⠕⠊⠲")
