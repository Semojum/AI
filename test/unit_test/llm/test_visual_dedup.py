"""F23 · 그림 안 글자를 본문과 설명에 두 번 적지 않는다 (원장 C-78).

gold 는 그림 안 글자를 **본문에 한 번만** 적는다(자리 실측 본문 27 : 설명 1).
우리는 본문 요소로 한 번 + 설명에 또 한 번 = 두 번 적었다. 지우는 쪽은 **설명**이다.

규칙을 좁게 잡는다 — 넓히면 **본문에 있어야 할 224건까지 지운다**:
8자 이상 · 정규화 후 완전 포함 · 줄 단위 · 스위치 기본 끔.
"""
import pytest

from app.ai.llm.visual_drafts import _dup_of_body, _outline_text_indents


class TestDupOfBody:
    def test_기본은_꺼져_있다(self, monkeypatch):
        from app.ai.llm.base_opt import visual_dedup_enabled
        monkeypatch.delenv("VISUAL_DEDUP", raising=False)
        assert visual_dedup_enabled() is False
        monkeypatch.setenv("VISUAL_DEDUP", "1")
        assert visual_dedup_enabled() is True

    def test_8자_이상만_지운다(self):
        body = ["형질그림쌍꺼풀(대립형질)이나타난다"]
        assert _dup_of_body("쌍꺼풀(대립 형질)", body) is True      # 9자
        assert _dup_of_body("(가)", body) is False                 # 3자 — 안 지운다
        assert _dup_of_body("X 주사", body) is False                # 4자 — 안 지운다

    def test_본문에_없으면_안_지운다(self):
        """설명에만 있는 것(본문 전용 224건과 반대쪽)은 그대로 둔다."""
        assert _dup_of_body("친환경 농업 기술 안내", ["전혀 다른 본문 글자입니다"]) is False
        assert _dup_of_body("친환경 농업 기술 안내", None) is False
        assert _dup_of_body("친환경 농업 기술 안내", []) is False

    def test_정규화해서_본다(self):
        """공백·태그 차이는 무시한다 — 같은 말이면 지운다."""
        assert _dup_of_body("친환경  농업\n기술 안내", ["앞말 친환경농업기술안내 뒷말"]) is True
        assert _dup_of_body("<!강조>친환경 농업 기술 안내<!/강조>",
                            ["친환경농업기술안내"]) is True

    def test_부분만_겹치면_안_지운다(self):
        """줄 단위다 — 문장 중간을 잘라 'Ａ와 B를 잇는 화살표'가 깨지면 안 된다."""
        assert _dup_of_body("친환경 농업 기술 안내 그리고 더 긴 뒷말",
                            ["친환경농업기술안내"]) is False


class TestOutlineDraft:
    def _items(self):
        return [(0, "쌍꺼풀(대립 형질)"), (0, "본문에 없는 설명 항목입니다")]

    def test_중복_항목만_빠진다(self):
        body = ["형질그림쌍꺼풀(대립형질)이나타난다"]
        text, _ = _outline_text_indents("그림", "제목", "설명", self._items(), "", body)
        assert "쌍꺼풀" not in text, f"중복이 안 빠졌다: {text!r}"
        assert "본문에 없는 설명 항목입니다" in text, f"안 겹치는 항목까지 빠졌다: {text!r}"

    def test_본문_목록이_없으면_종전_그대로(self):
        text, _ = _outline_text_indents("그림", "제목", "설명", self._items(), "", None)
        assert "쌍꺼풀" in text and "본문에 없는 설명 항목입니다" in text

    def test_같은_문구가_그림_둘에_걸리면_둘_다_지운다(self):
        """pm 요청(2026-08-29): 이 동작을 테스트로 고정해 둔다.

        각 그림은 **자기 bbox 안 본문만** 본다. 같은 문구가 그림 둘 안에 걸쳐 있으면
        양쪽 설명에서 다 빠진다. 본문 요소는 그대로 남으므로 **글자가 사라지지는 않는다.**
        바꾸려면 이 테스트부터 고쳐라.
        """
        body = ["공통으로겹치는긴문구"]
        items = [(0, "공통으로 겹치는 긴 문구")]
        for _ in range(2):                       # 그림 둘이 같은 본문을 품은 상황
            text, _ind = _outline_text_indents("그림", "제", "설", items, "", body)
            assert "공통으로" not in text
