"""text_opt 레이아웃 태깅 — 후보 게이트·검증·내용보존 회귀 테스트.

LLM 호출 없는 순수 함수만 검증(게이트·검증·펜스제거). LLM 태깅 자체는 실모델 E2E로.
"""
from app.ai.llm.text_opt import (
    _TAG_CANDIDATE_RE,
    _content_sig,
    _strip_fence,
    _validate_tagging,
)


class TestCandidateGate:
    def test_평문은_후보_아님(self):
        assert not _TAG_CANDIDATE_RE.search("이 문장은 평범하다.")

    def test_네모빈칸_후보(self):
        assert _TAG_CANDIDATE_RE.search("③ □과 □은")

    def test_밑줄빈칸_후보(self):
        assert _TAG_CANDIDATE_RE.search("정답: ____")

    def test_보기상자_후보(self):
        assert _TAG_CANDIDATE_RE.search("<보기>\nㄱ. 가")
        assert _TAG_CANDIDATE_RE.search("[자료] 다음")


class TestValidateTagging:
    def test_내용보존_빈칸치환_통과(self):
        assert _validate_tagging("③ □과 □은", "③ <!빈칸_네모>과 <!빈칸_네모>은")

    def test_글상자_통과(self):
        assert _validate_tagging(
            "<보기>\nㄱ. 가", "<!테두리_위>보기<!/테두리_위>\nㄱ. 가\n<!테두리_아래><!/테두리_아래>")

    def test_평문_무변경_통과(self):
        assert _validate_tagging("평범한 문장", "평범한 문장")

    def test_내용변경_거부(self):
        # LLM이 단어를 바꾸거나 추가하면 검증 실패
        assert not _validate_tagging("정답: ____", "정답(주관식): <!빈칸_표>")

    def test_미지태그_거부(self):
        assert not _validate_tagging("가나", "<!마름모>가나<!/마름모>")

    def test_빈출력_거부(self):
        assert not _validate_tagging("③ □", "")


class TestStripFence:
    def test_코드펜스_제거(self):
        assert _strip_fence("```plaintext\n③ <!빈칸_네모>\n```") == "③ <!빈칸_네모>"

    def test_펜스없음_그대로(self):
        assert _strip_fence("정답: <!빈칸_표>") == "정답: <!빈칸_표>"


class TestContentSig:
    def test_빈칸문자_제거(self):
        assert _content_sig("③ □과") == _content_sig("③ <!빈칸_네모>과")

    def test_상자구획문자_제거(self):
        assert _content_sig("<보기>가나") == _content_sig("<!테두리_위>보기<!/테두리_위>가나")
