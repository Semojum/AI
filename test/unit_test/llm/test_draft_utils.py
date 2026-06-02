"""draft_utils — 점역사주 태그 포장 + 방식-라벨 제거(프리필 방식 채택 후)."""
from app.ai.llm.draft_utils import ensure_tn_prefix, parse_labeled_drafts


class TestEnsureTnPrefix:
    def test_방식라벨_제거(self):
        # 모델이 본문 앞에 붙이는 방식 이름은 점자에 안 찍히게 제거
        assert ensure_tn_prefix("상황 중심: 원 안에 삼각형") == "<!점역자주>원 안에 삼각형<!/점역자주>"
        assert ensure_tn_prefix("[점역사주] 위치 중심: 칠판 앞") == "<!점역자주>칠판 앞<!/점역자주>"
        assert ensure_tn_prefix("요약 중심: 수업 장면").endswith("수업 장면<!/점역자주>")
        assert "대사 중심" not in ensure_tn_prefix("대사 중심: 선생님 안녕")

    def test_유형라벨_보존(self):
        # 그림:/만화: 등 유형 라벨은 방식 라벨이 아니므로 보존
        assert "그림: 교실" in ensure_tn_prefix("그림: 교실 수업")
        assert "만화: 선생님" in ensure_tn_prefix("만화: 선생님 등장")

    def test_빈입력(self):
        assert ensure_tn_prefix("") == ""
        assert ensure_tn_prefix("요약:") == ""   # 라벨만 있으면 빈 결과


class TestParseLabeledDrafts:
    def test_프리필_3안_파싱_라벨제거(self):
        raw = ("[방식1] [점역사주] 상황 중심: 원 안에 삼각형\n"
               "[방식2] [점역사주] 위치 중심: 삼각형은 원 안에\n"
               "[방식3] [점역사주] 요약: 원과 삼각형")
        methods = [("narrative", "상황 중심"), ("narrative", "위치 중심"), ("narrative", "요약")]
        ds = parse_labeled_drafts(raw, methods)
        assert len(ds) == 3
        assert ds[0].text == "<!점역자주>원 안에 삼각형<!/점역자주>"
        assert ds[2].text == "<!점역자주>원과 삼각형<!/점역자주>"
        assert len({d.text for d in ds}) == 3   # 세 초안 서로 다름
