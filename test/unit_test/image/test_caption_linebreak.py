"""캡션의 열거 항목은 줄을 나눈다 (2026-08-12 대표 지시).

캡셔너가 "1. …이다 2. …이다"처럼 한 줄에 쭉 이어 쓰면 점역사 편집창에서 눈으로 번호를
찾아 끊어 읽어야 한다. 그리고 `visual_drafts`의 개조식(2안)은 **줄 단위로** 항목을
만들기 때문에, 한 줄로 뭉친 캡션은 개조식이 되어도 항목이 하나뿐이다.
"""
from __future__ import annotations

import pytest

from app.ai.captioning.captioner import _split_enumerations as split


class TestSplit:
    @pytest.mark.parametrize("src,want", [
        ("그림: 1. 광개토대왕릉비의 모습이다 2. 장수왕비의 모습이다",
         "그림: 1. 광개토대왕릉비의 모습이다\n2. 장수왕비의 모습이다"),
        ("그래프: ① 증가 구간 ② 감소 구간 ③ 정체 구간",
         "그래프: ① 증가 구간\n② 감소 구간\n③ 정체 구간"),
        ("그림: 지도에 표시된 도시 - 서울 - 부산 - 대구",
         "그림: 지도에 표시된 도시\n- 서울\n- 부산\n- 대구"),
    ])
    def test_항목마다_줄바꿈(self, src: str, want: str) -> None:
        assert split(src) == want

    def test_소수점은_안_쪼갠다(self) -> None:
        """'12.0도'의 마침표를 항목 번호로 오인하면 수치가 두 동강 난다."""
        t = "평균 기온은 12.0도이고 최고 기온은 14.7도이다"
        assert split(t) == t

    def test_짧은_줄은_그대로(self) -> None:
        assert split("그림: 사진") == "그림: 사진"

    def test_이미_나뉜_줄은_그대로(self) -> None:
        t = "그래프: 연도별 인구\n2020년 5,200만 명\n2021년 5,180만 명"
        assert split(t) == t

    def test_빈_입력(self) -> None:
        assert split("") == ""


def test_개조식이_실제로_항목이_된다() -> None:
    """줄이 나뉘어야 개조식 2안이 항목을 갖는다 — 이 배선이 이 수정의 목적이다."""
    from app.ai.llm.visual_drafts import _parse_sections

    cap = split("그림: 1. 광개토대왕릉비의 모습이다 2. 장수왕비의 모습이다")
    sec = _parse_sections("[개조식]\n" + cap)
    assert len(sec["개조식"]) >= 2, sec["개조식"]
