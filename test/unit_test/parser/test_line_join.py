"""줄바꿈 조각 잇기(C005) — 이어야 할 것만 잇는가.

시연 문서 실측(2026-08-26)에서 나온 얼굴을 그대로 쓴다. 지면 폭 1000 기준 0~1000
정규화 bbox 이고, 줄 높이 11 · 본문 단은 x 196~832 이다.
"""
import pytest

from app.ai.parser.mineru_runner import _ITEM_HEAD_RE, _SENT_END_RE, _join_wrapped_lines

LINE = 11.0
LEFT, RIGHT = 196.0, 832.0


class _FakePage:
    """텍스트 레이어가 없는 지면 — _line_seam 이 개행으로 물러선다."""

    class _Rect:
        width = height = 1000.0

    rect = _Rect()

    def get_textbox(self, rect):        # noqa: ARG002 - 레이어 없음을 흉내낸다
        return ""


def _line(y, text, x0=LEFT, x1=RIGHT, etype="text"):
    return {"element_id": f"e{y}", "reading_order": int(y), "type": etype,
            "heading_level": 0, "content": text,
            "bbox": [x0, y, x1, y + LINE]}


def _join(els, page=None):
    return _join_wrapped_lines(els, page or _FakePage())


def test_wrapped_sentence_is_joined():
    """문장이 끝나지 않았고 줄이 단 끝까지 찼으면 잇는다."""
    els = [_line(100, "첫째, 후각은 대뇌의 감각 피질과 직접 연결되어 있습니"),
           _line(115, "다. 시각, 청각 등의 다른 감각의 경우 정보가 들어오면"),
           _line(130, "시상이라고 하는 대뇌 기관에서 정보를 통합한 뒤")]
    out = _join(els)
    assert len(out) == 1
    assert out[0]["content"].count("\n") == 2          # 레이어가 없으면 개행으로 잇는다
    assert "있습니" in out[0]["content"] and "통합한 뒤" in out[0]["content"]


def test_sentence_end_is_not_joined():
    """문장부호로 끝난 줄은 다음 줄과 잇지 않는다."""
    els = [_line(100, "가 발표할 주제는 바로 이 ‘냄새와 후각’입니다."),
           _line(115, "냄새를 맡는 감각인 후각은 액체 또는 공기 중에 떠다니는")]
    assert len(_join(els)) == 2


def test_verse_lines_are_not_joined():
    """시행은 할 말이 끝나는 데서 끊겨 단 끝이 들쭉날쭉하다 — 이으면 안 된다."""
    els = [_line(100, "아늑한 이 항구인들 손쉽게야 버릴 거냐", x1=RIGHT - 90),
           _line(115, "안개같이 물 어린 눈에도 비치나니", x1=RIGHT - 150),
           _line(130, "돌아다보는 구름에는 바람이 희살짓는다", x1=RIGHT - 60),
           _line(145, "앞 대일 언덕인들 마련이나 있을 거냐", x1=RIGHT - 120)]
    assert len(_join(els)) == 4


@pytest.mark.parametrize("head", ["⑵  특징: 사회 계층화 현상은", "3. 다이아몬드형",
                                  "• 매체 자료의 타당성 확인", "(5) 페르시아 전쟁",
                                  "\\- 전체 연재 기사와의 연계성", "<!상자><!/상자>"])
def test_new_item_is_not_joined(head):
    """뒤 조각이 새 항목을 열면 잇지 않는다."""
    els = [_line(100, "에 비교적 구조화되고 지속적인 서열이 존재하는 현상"), _line(115, head)]
    assert len(_join(els)) == 2


def test_short_label_is_not_joined():
    """'EBS'·'방사관' 같은 서너 글자 라벨은 단이 아니다."""
    els = [_line(100, "EBS", x1=LEFT + 3 * LINE), _line(115, "194", x1=LEFT + 3 * LINE)]
    assert len(_join(els)) == 2


def test_only_text_type_is_joined():
    """표·목록·시각자료는 줄바꿈이 내용이라 손대지 않는다."""
    els = [_line(100, "ㄴ. 구성원의 지위와 역할이 뚜렷하고 조직화되어", etype="list_item"),
           _line(115, "있는가?", etype="list_item")]
    assert len(_join(els)) == 2


def test_seam_uses_layer_space_when_available():
    """공백 글리프를 쓰는 지면이면 원본 줄 끝 공백대로 붙이거나 띄운다."""

    class _Layer(_FakePage):
        def __init__(self, tail):
            self.tail = tail

        def get_textbox(self, rect):    # noqa: ARG002
            return self.tail

    head, nxt = "대뇌 기관에서 정보를 통합한 뒤", "감각 피질로 전달되는"
    pair = [_line(100, head), _line(115, nxt)]
    spaced = _join([dict(e) for e in pair], _Layer(head + " "))
    glued = _join([dict(e) for e in pair], _Layer(head))
    assert spaced[0]["content"] == f"{head} {nxt}"
    assert glued[0]["content"] == f"{head}{nxt}"


def test_seam_falls_back_when_layer_has_no_word_spaces():
    """어절을 커닝으로만 띄우는 지면은 끝 공백이 없어도 아무 뜻이 없다 — 개행으로 물러선다.

    실측: '폐포, 혈액, 조직 세포에서' 가 레이어에서는 '폐포, 혈액, 조직세포에서' 로 나온다
    (쉼표 뒤 공백만 진짜고 어절 사이는 커닝). 이걸 붙임으로 읽어 낱말을 붙여 버렸다.
    """

    class _Kerned(_FakePage):
        def get_textbox(self, rect):    # noqa: ARG002
            return "폐포, 혈액, 조직세포에서"

    els = [_line(100, "폐포, 혈액, 조직 세포에서"), _line(115, "산소 분압의 크기는 크다")]
    out = _join(els, _Kerned())
    assert out[0]["content"] == "폐포, 혈액, 조직 세포에서\n산소 분압의 크기는 크다"


def test_seam_survives_a_chain():
    """세 줄을 이을 때 두 번째 이음매도 **자기 줄**로 판정한다(누적 글로 보면 어긋난다)."""

    class _PerLine(_FakePage):
        def __init__(self, lines):
            self.lines = lines
            self.n = 0

        def get_textbox(self, rect):    # noqa: ARG002
            out = self.lines[self.n]
            self.n += 1
            return out

    els = [_line(100, "중요한 해마를 포"), _line(115, "함하고 있습니다 그 다음"), _line(130, "이야기를 이어 간다")]
    out = _join(els, _PerLine(["중요한 해마를 포", "함하고 있습니다 그 다음 "]))
    assert out[0]["content"] == "중요한 해마를 포함하고 있습니다 그 다음 이야기를 이어 간다"


def test_sentence_end_regex_ignores_bare_syllables():
    """'…있습니'·'…후각은 다'는 문장 끝이 아니다 — 낱말 한가운데가 잘린 자리다."""
    assert not _SENT_END_RE.search("연결되어 있습니")
    assert not _SENT_END_RE.search("후각은 다")
    assert _SENT_END_RE.search("때문입니다.")
    # '다.'는 한글 글머리(가./나./다.)와 같은 얼굴이지만 글머리로 보면 안 된다.
    assert not _ITEM_HEAD_RE.match("다. 시각, 청각 등의")
