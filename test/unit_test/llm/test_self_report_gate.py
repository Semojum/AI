"""모델이 자기 작업을 보고한 줄이 요소 글자가 되던 구멍 (#772).

`_EXTRACTION_REFUSAL_RES` 는 "못 읽었다" 만 잡는다. **일을 했다고 보고하는 문장**은 그 표에
없어 `body`·`table_tn`·`visual_draft`·`figure` **넷 다** 그대로 통과했다(2026-09-15 실측,
문장 다섯 × kind 넷 = 20건 전수 통과).

패턴은 근거 없이 넓히지 않았다 — `temp/par/d3` 1,131쪽의 **시각 요소를 뺀** 경계 요소
25,458개 전수에서 **오검출 0건**인 것만 골랐다(기각한 것: "제시된 자료"18건 ·
평서형 "확인할 수 없다" 5건 · "보내주시기 바랍니다" 9건). 캡션 캐시 3,242개에서도
통째로 비는 것 0 · 줄만 걷힌 것 6(전부 사과 머리말).
"""
from __future__ import annotations

import pytest

from app.ai import gates
from app.ai.captioning.captioner import guard_llm_text

# 이슈 본문·검침 코멘트가 든 실물 문장
_REPORTS = [
    "원본을 살펴보면 오인식이 있어 교정합니다.",
    "수식 표기를 규정에 맞게 교정했습니다.",
    "위 내용을 다음과 같이 정리했습니다.",
    "그림에 실제로 보이는 정보가 매우 적어, 확인되는 사실만 적겠습니다.",
    "이미지에 텍스트나 그림 정보가 보이지 않습니다.",
    "그림에 없는 임의 추측 없이, 보이는 요소만 정리합니다.",
    "자녀가 영희 한 명만 표시되어 있는지는 그림만으로 확정할 수 없습니다.",
]

# 교과서 글. 존댓말이지만 **인용문**이라 건드리면 안 된다(전수 실측에서 오검출 0).
_BOOK = [
    "우리는 자유인의 의무를 수행하고 있고, 우리는 자유인의 특권을 가져야 합니다.",
    "제시된 자료는 1830년 영국 하원에서 한 노동자가 증언한 내용이다.",
    "① 표제어와 관련어의 관계를 확인할 수 없다는 점에서 혼란을 야기할 수 있다.",
    "교황께서 이들을 막아낼 원군을 보내 주시길 간절히 바랍니다.",
    "옛 제도들을 검토하여 서양식으로 바꾸어야 합니다.",
    "임의 교배가 불가능하므로 특정 형질의 유전 결과를 확인하기 어렵다.",
]


class TestPredicate:
    @pytest.mark.parametrize("line", _REPORTS)
    def test_자기_보고문을_잡는다(self, line: str) -> None:
        assert gates.is_self_report(line) is True

    @pytest.mark.parametrize("line", _BOOK)
    def test_교과서_글은_안_잡는다(self, line: str) -> None:
        assert gates.is_self_report(line) is False


class TestStrip:
    def test_보고문_줄만_걷고_본문은_지킨다(self) -> None:
        """★ 통째로 비우면 뒤에 붙은 진짜 내용까지 잃는다 — 이슈가 든 바로 그 꼴."""
        src = "원본을 살펴보면 오인식이 있어 교정합니다.\n밀물과 썰물이 생기는 까닭"
        assert gates.strip_self_report(src) == "밀물과 썰물이 생기는 까닭"

    def test_남는_게_없으면_빈다(self) -> None:
        assert gates.strip_self_report("수식 표기를 규정에 맞게 교정했습니다.") == ""

    def test_걸릴_게_없으면_원본_그대로다(self) -> None:
        src = "밀물과 썰물이 생기는 까닭\n달과 태양의 인력 때문이다."
        assert gates.strip_self_report(src) is src or gates.strip_self_report(src) == src

    def test_빈_입력도_안_터진다(self) -> None:
        assert gates.strip_self_report("") == ""
        assert gates.strip_self_report(None) == ""


class TestGateWiring:
    """★ kind 넷 다 새고 있었다. 하나만 막으면 나머지 셋으로 나간다."""

    @pytest.mark.parametrize("kind", ["body", "table_tn", "visual_draft", "figure"])
    def test_모든_kind_에서_걷힌다(self, kind: str) -> None:
        got = guard_llm_text("원본을 살펴보면 오인식이 있어 교정합니다.\n밀물과 썰물이 생기는 까닭",
                             kind)
        assert got.strip() == "밀물과 썰물이 생기는 까닭"

    @pytest.mark.parametrize("kind", ["body", "table_tn", "visual_draft", "figure"])
    def test_교과서_인용문은_모든_kind_에서_살아남는다(self, kind: str) -> None:
        src = "우리는 자유인의 의무를 수행하고 있고, 우리는 자유인의 특권을 가져야 합니다."
        assert guard_llm_text(src, kind).strip() == src

    def test_캡션_사슬에서도_사과_머리말만_걷는다(self) -> None:
        """캡션 캐시 3,242개 실측: 통째로 비는 것 0 · 줄만 걷힌 것 6(전부 이 꼴)."""
        src = ("만화: 말풍선 대사가 그림에 보이지 않아 옮길 수 없습니다.\n\n"
               "만화: 학생 A, 학생 B가 탁자에 둘러앉아 이야기함")
        got = guard_llm_text(src, "caption", image_type="만화")
        assert "옮길 수 없습니다" not in got
        assert "학생 A" in got
