"""mode b 글상자 경계 + 자간 벌린 표지 검출 회귀 (#732 B·D).

제목 점형(C)은 `test/unit_test/braille/test_box_label_and_title.py` 몫이다 —
여기 두면 `test-fast`(가벼운 의존성만 깐다)가 `app.core.pipeline` import 에서 깨진다.

B 자간 벌린 표지(`<보 기>`)가 태깅 후보 정규식에 안 걸려 **LLM 호출조차 안 나갔다**
  (실물 실행 로그 `외부LLM 0회`). 테두리가 한 칸도 안 나갔다.
  「점자 도서 제작 지침」[예 1-11](재추출 423~429행)이 바로 그 꼴을 글상자 제목으로 싣는다.
D mode b 가 줄 하나를 요소 하나로 쪼개서, 태깅 LLM 이 표지 줄만 보고 그 줄만 감쌌다 —
  위·아래 테두리가 붙어 나오고 본문이 상자 밖으로 떨어진다. #724 에서 표가 깨진 자리와 같다.
"""
from app.ai.llm.text_opt import _TAG_CANDIDATE_RE
from app.core.pipeline import _mode_b_segments


class TestB표지검출:
    def test_자간_벌린_표지도_태깅_후보다(self):
        assert _TAG_CANDIDATE_RE.search("<보기>")
        assert _TAG_CANDIDATE_RE.search("<보 기>"), "자간 조판 표지가 LLM 호출조차 못 받는다"
        assert _TAG_CANDIDATE_RE.search("[자 료 1]")

    def test_표지가_아닌_꺽쇠는_후보가_아니다(self):
        assert not _TAG_CANDIDATE_RE.search("x < 10 이고 y > 3 이다")


class TestD상자경계:
    def test_표지_줄과_본문이_한_요소로_묶인다(self):
        src = "<보기>\n첫 줄이다.\n둘째 줄이다.\n\n5. <보기>의 ㄱ은?"
        segs = _mode_b_segments(src)
        assert segs[0] == (1, "text", "<보기>\n첫 줄이다.\n둘째 줄이다."), (
            "표지 줄이 제 요소로 떨어지면 태깅 LLM 이 그 줄만 감싸 상자가 빈다")
        assert segs[1] == (5, "text", "5. <보기>의 ㄱ은?")

    def test_표지_뒤에_조사가_붙으면_참조라_안_묶는다(self):
        src = "<보기>의 ㄱ에 대한 설명은?\n① 첫째다."
        assert [s[0] for s in _mode_b_segments(src)] == [1, 2]

    def test_표지_뒤가_빈_줄이면_안_묶는다(self):
        assert [s[2] for s in _mode_b_segments("<보기>\n\n딴 문단이다.")] == [
            "<보기>", "딴 문단이다."]

    def test_빈_줄_없는_원고가_통째로_한_요소가_되지_않는다(self):
        src = "<보기>\n" + "\n".join(f"{i}번째 줄이다." for i in range(60))
        segs = _mode_b_segments(src)
        assert segs[0][2].count("\n") + 1 == 31, "표지 + 30줄에서 끊겨야 한다"
        assert len(segs) == 31
