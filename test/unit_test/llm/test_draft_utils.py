import pytest
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


class TestWrapStyleSwitch:
    """시각 초안 포장 A/B — 주표(tn, 기본) vs 글상자(box). 원장 C-02 축.

    평가 실측(LLM-켬 12쪽): 우리 주표 9개 중 3개(33%)를 gold는 같은 내용의 **본문**으로
    낸다. 내용은 필요한데 포장만 다르다. 규칙 경로(`visual_drafts`)와 **같은 스위치**를
    읽어야 한 번의 A/B로 두 경로를 함께 본다 — 이 테스트가 그 정합을 묶는다.
    """

    @pytest.fixture(autouse=True)
    def _restore(self):
        """⚠ reload는 모듈 전역을 바꾼다 — 끝나면 기본값으로 되돌려야 다른 테스트가 안 샌다."""
        yield
        import importlib, os
        os.environ.pop("VISUAL_WRAP_STYLE", None)
        from app.ai.llm import draft_utils, visual_drafts
        importlib.reload(draft_utils); importlib.reload(visual_drafts)

    @staticmethod
    def _reload(monkeypatch, style: str):
        import importlib
        from app.ai.llm import draft_utils, visual_drafts
        monkeypatch.setenv("VISUAL_WRAP_STYLE", style)
        return importlib.reload(draft_utils), importlib.reload(visual_drafts)

    def test_기본은_주표(self, monkeypatch) -> None:
        d, v = self._reload(monkeypatch, "tn")
        assert d.ensure_tn_prefix("그래프: 설명").startswith("<!점역자주>")
        assert v._tn("그래프: 설명").startswith("<!점역자주>")

    def test_box면_두_경로_모두_글상자(self, monkeypatch) -> None:
        d, v = self._reload(monkeypatch, "box")
        for out in (d.ensure_tn_prefix("그래프: 설명"), v._tn("그래프: 설명")):
            assert out.startswith("<!테두리_위>") and out.endswith("<!/테두리_아래>")
            assert "점역자주" not in out

    def test_전환해도_내용은_보존된다(self, monkeypatch) -> None:
        d, _ = self._reload(monkeypatch, "box")
        assert "카드 1: 기능론" in d.ensure_tn_prefix("카드 1: 기능론")
