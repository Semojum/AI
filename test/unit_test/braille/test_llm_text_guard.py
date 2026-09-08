"""관문 G1·G3 — LLM 문장이 요소 필드·점역기로 가는 길의 한 자리 (재구조화 2단계, 2026-09-08).

종전에는 이 사슬이 **캡셔너 미스 경로 한 곳**에만 있었다. 캐시 히트·그림 회수·고급 점역
갈래 B·시각 초안 폴백·표 점역자주는 관문 없이 요소 필드로 직행했고, 그래서 같은 결함을
자리마다 따로 기웠다. 여기 있는 검사가 지키는 것은 둘이다.

  ① **관문은 거르는 자리지 다시 쓰는 자리가 아니다.** 통과한 줄은 한 글자도 안 바뀐다.
     (`_finish` 를 그대로 노출한 `kind="caption"` 만 예외 — 그건 종전 캡션 경로 동작이다)
  ② `LLM_TEXT_GUARD=0` 이면 **정말 꺼진다.** "껐다고 믿었는데 안 꺼진" 사고가 두 번 있다.

`test_caption_guards.py` 에서 옮겨 온 것 — AI 말투 줄 걷기(가드5) 케이스 전부.
그 파일에 남은 것 — `_reject_read_text`·`_is_blank_crop`(둘 다 캡션 전용).
"""
from __future__ import annotations

import pytest

from app.ai import gates


def _guard():
    """captioner 는 openai SDK 를 문다 — test-fast 에는 없다(test-full 이 돌린다)."""
    return pytest.importorskip("app.ai.captioning.captioner").guard_llm_text


# ── ① 관문이 줄 형식을 안 바꾼다 ──────────────────────────────────────────
# 정상 글은 **바이트 그대로** 돌아와야 한다. 관문이 손을 대기 시작하면 그 자리가 새 결함의
# 출처가 된다 — 실제로 `_ensure_type_word` 는 줄머리에 `그림: ` 을 붙이는 **재작성**이라
# 본문(`body`)·표주(`table_tn`)에 걸면 안 된다. kind 별 사슬이 갈리는 근거가 이것이다.
INTACT = [
    "표. 지역별 인구, 3행 4열",
    "원 안에 삼각형 세 개가 겹쳐 있다",
    "1. 첫째 항목\n2. 둘째 항목\n3. 셋째 항목",
    "왼쪽: 20 · 오른쪽: 35\n\n가운데 빈 줄도 그대로 둔다",
    "갑: 이 문제는 어떻게 푸나요?\n을: 넓이를 먼저 구합니다.",
]


@pytest.mark.parametrize("text", INTACT)
@pytest.mark.parametrize("kind", ["body", "table_tn", "visual_draft", "figure"])
def test_통과한_글은_한_글자도_안_바뀐다(kind, text):
    assert _guard()(text, kind) == text


def test_글_앞뒤_공백만_접는다():
    """유일하게 관문이 손대는 형식. 줄 안은 안 건드린다(가드5 종전 동작 그대로)."""
    assert _guard()("  첫 줄  \n\n  둘째 줄  ", "visual_draft") == "첫 줄  \n\n  둘째 줄"


def test_걷어낸_뒤_남는_줄은_그대로다():
    """줄을 통째로 버리기만 한다 — 남는 줄을 다시 쓰지 않는다."""
    src = ("만화: 말풍선 대사를 읽을 수 없습니다.\n"
           "만화: 학생 셋이 탁자에 앉아 있다\n"
           "학생 A: 우리 같이 하자")
    out = _guard()(src, "visual_draft")
    kept = out.split("\n")
    assert kept == ["만화: 학생 셋이 탁자에 앉아 있다", "학생 A: 우리 같이 하자"]
    for line in kept:
        assert line in src.split("\n")          # 남은 줄은 원문 줄과 동일


def test_본문은_AI_말투_판정을_안_받는다():
    """`body` 는 고급 점역이 읽어 온 **본문 글자**다. 존댓말은 원본에 정상으로 있다."""
    src = "이 실험의 결과는 다음과 같습니다.\n온도가 오르면 반응 속도가 빨라집니다."
    assert _guard()(src, "body") == src


# ── ② 되돌리는 길 ────────────────────────────────────────────────────────
def test_LLM_TEXT_GUARD_0_이면_한_글자도_안_건드린다(monkeypatch):
    src = "만화: 말풍선 대사를 읽을 수 없습니다.\n만화: 학생이 걷는다"
    monkeypatch.delenv("LLM_TEXT_GUARD", raising=False)
    assert _guard()(src, "visual_draft") != src          # 켜져 있으면 걷는다
    monkeypatch.setenv("LLM_TEXT_GUARD", "0")
    assert _guard()(src, "visual_draft") == src          # 끄면 그대로 나간다
    assert gates.guard_on() is False                     # 호출 시 읽는다


def test_손잡이를_내리면_캡션은_develop_과_같다(monkeypatch):
    """되돌리는 길은 **이 PR 이 더한 것만** 되돌린다.

    캡션 사슬은 이 PR 이 만든 게 아니라 옮긴 것이다. 손잡이를 내렸을 때 그것까지 꺼지면
    develop 보다 더 새는 상태가 된다 — 손잡이가 사고를 키우는 자리가 된다.
    """
    cap = pytest.importorskip("app.ai.captioning.captioner")
    src = "원 안에 삼각형이 있다"                        # 유형 제시어 없는 원문
    monkeypatch.setenv("LLM_TEXT_GUARD", "0")
    assert cap.guard_llm_text(src, "caption") == cap._finish(src, "image") == "그림: " + src


# ── 옮겨 온 것: 가드5 AI 말투 (구 test_caption_guards.py) ────────────────
# 대표 지목 결함. 캡션 캐시 3,057건 전수에서 걸린 30건이 근거이고, 실경로로 점자까지
# 나가는 것을 확인했다. 이 결함은 조용히 되살아난다 — 프롬프트를 손볼 때마다 모델이
# 변명 줄을 다시 붙인다. 이제 캡션뿐 아니라 초안·회수·표주도 같은 관문을 지난다.
AI_VOICE_PAIRS = [
    ("만화: 말풍선 대사가 그림에 표시되어 있으나 내용을 읽을 수 없습니다.\n\n"
     "만화: 안내원이 '우하량' 표지판 앞에서 학생 무리에게 설명하는 장면",
     "만화: 안내원이 '우하량' 표지판 앞에서 학생 무리에게 설명하는 장면"),
    ("그림: 이미지가 흐릿하여 세부 확인이 어렵습니다. 보이는 대로 적습니다.\n\n"
     "사진: 돌담 위에 새 한 마리가 앉아 있음",
     "사진: 돌담 위에 새 한 마리가 앉아 있음"),
    ("만화: 말풍선 대사가 그림에 보이지 않아 옮길 수 없습니다.\n\n"
     "만화: 연단에 선 남자가 청중 앞에서 발표함",
     "만화: 연단에 선 남자가 청중 앞에서 발표함"),
    ("그림: 이미지에 이름표나 번호가 보이지 않아 정확한 대상을 확정하기 어렵습니다.\n\n"
     "그림: 원기둥 모양 물체와 그 위에 놓인 작은 인형",
     "그림: 원기둥 모양 물체와 그 위에 놓인 작은 인형"),
    # 못읽음 자리표시를 대사인 척 채운 줄 — 정보 0인데 점자 셀만 먹는다(실측 대사 5줄 사례)
    ("만화: 학생 A, B, C가 탁자에 앉아 무언가를 적고 있다\n"
     "학생 A: 읽을 수 없는 기호\n학생 B: 읽을 수 없는 기호\n학생 C: 읽을 수 없는 기호",
     "만화: 학생 A, B, C가 탁자에 앉아 무언가를 적고 있다"),
]


@pytest.mark.parametrize("raw,kept", AI_VOICE_PAIRS)
@pytest.mark.parametrize("kind", ["visual_draft", "figure", "table_tn"])
def test_AI_말투_줄만_걷고_설명은_남긴다(kind, raw, kept):
    assert _guard()(raw, kind) == kept


def test_남는_게_없으면_빈_문자열_생략표기로_간다():
    """지어내지 않는다 — 빈 문자열은 기존 생략 표기 + R11 경로를 탄다."""
    assert _guard()("그림: 읽을 수 없는 기호", "visual_draft") == ""


# ★ 손해 쪽이 더 중요하다. 전수 측정에서 오차단 2건을 잡아 넣은 케이스가 아래 둘이다.
AI_VOICE_KEEP = [
    # 교과서 챗봇 화면 전사 — 'AI:' 는 그림 **안의 화자**다
    "AI: (가)은/는 중국을 통일하고 중앙 집권적 제국을 세운 인물입니다. "
    "그의 주요 업적을 정리하면 다음과 같습니다.",
    # 만화 속 대사. 못 읽은 자리가 있어도 문장이 남아 있으면 원본이다
    "을: (읽을 수 없음)…해서는 안 됩니다.",
    # 존댓말 종결 자체는 신호가 아니다 — gold 점역자 주 1,386구간에도 7건(0.51%) 있다
    "갑: 과학 기술로 인한 윤리 문제는 미래 세대까지 위협할 수 있습니다.",
    "안내 문구: 개별 도서관 누리집에서 상호 대차 운영 방식을 확인하세요.",
    # '읽을 수 없는'이 **설명 안에 박힌** 것은 진짜 묘사다
    "각 이름 위에 읽을 수 없는 크기의 글",
    "아래: 가로로 뻗은 축삭 돌기, 아래쪽에 지점 표시(이름표는 읽을 수 없음)",
    "문 위 방패 문양, 그 아래 네모 안에 읽을 수 없는 글자",
    "책 표지 제목은 대부분 읽을 수 없는 글자임",
]


@pytest.mark.parametrize("text", AI_VOICE_KEEP)
def test_정상_설명과_그림속_대사는_안_걸린다(text):
    assert _guard()(text, "visual_draft") == text


def test_가드5_대사_없음_변명_줄을_걷는다():
    """#734 실측 — 만화 프롬프트가 대사를 요구하자 모델이 '대사가 없습니다' 한 줄을 냈다."""
    g = _guard()
    src = ("만화: 한 사람의 인생을 다섯 시기로 나누어 보여 주고 있음.\n"
           "이 그림에는 말풍선 대사가 없습니다.\n"
           "현재: 교복 입고 가방 멘 학생이 서 있다.")
    assert g(src, "visual_draft") == ("만화: 한 사람의 인생을 다섯 시기로 나누어 보여 주고 있음.\n"
                                      "현재: 교복 입고 가방 멘 학생이 서 있다.")
    # 화자 줄은 그림 안의 말이라 남긴다. 존댓말이 아닌 관측 줄도 남긴다.
    assert g("을: 대사가 없습니다.", "visual_draft") == "을: 대사가 없습니다."
    assert (g("말풍선 안 내용이 그림에 없어 옮길 대사가 없음", "visual_draft")
            == "말풍선 안 내용이 그림에 없어 옮길 대사가 없음")


# ── 거부문 표는 **검증된 단위에서만** ──────────────────────────────────────
# 실측(2026-09-08, 캡션 캐시 1,961건): 요소 content 용 표를 캡션 한 덩이에 걸면 5건이
# 걸리고 **5건 전부 오검출**이다(`오른쪽 사람 말풍선: 내용 없음` 따위 — 캡션에서 그것은
# 변명이 아니라 관측이다). 그래서 `body`·`figure` 에서만 쓴다.
REFUSAL = "The image contains no discernible text or characters."


def test_본문_거부문은_비운다():
    assert _guard()(REFUSAL, "body") == ""


def test_캡션_안의_없음_관측은_안_버린다():
    """`글자 없음` 은 캡션에서 관측이다. 요소 content 에서는 변명이다 — 단위가 다르다."""
    src = "그림: 원 안에 프로펠러 모양 4개\n없음: 이름표·글자 없음"
    assert _guard()(src, "caption", image_type="image") == src


# ── ③ G3 형식 토큰 — 점역기 입구 (무거운 의존 없음: test-fast 에서도 돈다) ──
def test_G3_형식_토큰만_걷고_본문은_그대로다():
    assert gates.strip_format_tokens("설명 ⟦재료⟧ 끝") == "설명  끝"
    assert gates.strip_format_tokens("괄호 ⟨1234⟩ 는 안 건드린다") == "괄호 ⟨1234⟩ 는 안 건드린다"
    assert gates.strip_format_tokens("토큰 없는 글") == "토큰 없는 글"


def test_G3_는_점역기_가장_안쪽_진입점을_지난다():
    """`translate_with_breaks` 일곱 갈래와 표 칸 직접 호출까지 한 자리로 덮는다."""
    from app.ai.braille.translator import translate_tagged_text
    assert "⟦" not in translate_tagged_text("설명 ⟦재료⟧ 끝")


def test_G4_는_세기만_한다():
    from collections import Counter
    assert gates.count_foreign_cells(["⠫⠉⠊ ⠁", "⠁⠃"]) == Counter()
    assert gates.count_foreign_cells(["⠫<!강조>"]) == Counter({"<": 1, "!": 1, "강": 1,
                                                                "조": 1, ">": 1})
