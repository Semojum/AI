"""요청 로그 — API 사용량 카운터·단계 컨텍스트 회귀 테스트."""
import app.utils.req_log as rl


class TestApiCounts:
    def test_초기화_후_0(self):
        rl.start_request()
        assert rl.api_counts() == {"hcxt": 0, "gpt4o": 0}

    def test_증가(self):
        rl.start_request()
        rl.inc_hcxt(); rl.inc_hcxt(); rl.inc_gpt4o()
        c = rl.api_counts()
        assert c["hcxt"] == 2 and c["gpt4o"] == 1

    def test_summary_포맷(self):
        rl.start_request()
        rl.inc_gpt4o()
        s = rl.api_summary()
        assert "HCXT 0회" in s and "GPT-4o 1회" in s and "$" in s  # 비용 근사 표기

    def test_gpt4o_0이면_비용표기없음(self):
        rl.start_request()
        rl.inc_hcxt()
        assert "$" not in rl.api_summary()


class TestStage:
    def test_stage_무예외_note(self):
        with rl.stage("테스트단계") as st:
            st.note = "5요소"
        assert st.note == "5요소"
