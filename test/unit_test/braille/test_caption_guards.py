"""없는 그림의 설명을 내보내지 않는 가드 (노션 Review, 2026-08-23).

그림이 없는 자리가 시각 요소로 잡히면 캡셔너가 지면의 글자를 읽어 설명으로 낸다.
실측(1_a4.pdf 문제 본문 영역을 그대로 크롭)한 문자열을 케이스로 쓴다.
"""
import tempfile
from pathlib import Path

import pytest

# `captioner` 는 외부 LLM SDK 를 문다. CI 의 test-fast 는 requirements.txt 만 깔아
# 그것이 없으므로 수집 단계에서 이 파일 하나 때문에 점역 게이트 전체가 죽는다
# (2026-08-24 PR #233 에서 같은 일이 test_table_tn_guard.py 로 났다).
# 없으면 이 파일만 건너뛴다 — test-full 이 그대로 돌려 준다.
try:
    from app.ai.captioning.captioner import (_is_blank_crop, _reject_read_text,
                                              _strip_ai_voice)
except Exception:  # noqa: BLE001 — 무엇이 없든 건너뛴다
    pytest.skip("test-fast 환경에는 캡셔닝 의존성이 없다 (test-full 이 돌린다)",
                allow_module_level=True)

# 실측으로 나온 '글자를 읽은' 캡션 둘
READ_TEXT_1 = ("그림: 본문: 28번 문제\n\n$\\overline{AB}=\\overline{CD}=4$, "
               "$\\overline{BC}=\\overline{BD}=2\\sqrt{5}$ 인 사면체 ABCD가 있다.")
READ_TEXT_2 = ("그림: 25. 수열 $\\{a_n\\}$이 모든 자연수 $n$에 대하여\n\n"
               "$\\sqrt{9n^{2}-5}+2n<a_n<5n+1$")

# 정상 캡션 — 수식이 들어 있어도 걸리면 안 된다(전수 측정: LaTeX 필터는 정상의 21.9%를 죽였다)
NORMAL = [
    "개념도: 1 ATP 구조 2 아데닌 3 리보스 4 고에너지 인산 결합 5 P~P~P 6 $+H_2O$ "
    "7 ATP → ADP: 에너지 방출",
    "그림: 뇌 단면 구조도. 대뇌: 단면 상단 대부분을 차지 소뇌: 뇌 뒤쪽 아래에 위치",
    "그래프: 선그래프, 세로축 막전위($mV$), 가로축 시간(초)",
    "만화: 한 사람의 일생을 시간 흐름에 따라 보여줌. 현재: 학생임 8년 후: 대학에서 그림을 그림",
    "도표: 사면체 ABCD와 점 H, G, 구 S를 나타낸 입체도형 그림",
]


@pytest.mark.parametrize("text", [READ_TEXT_1, READ_TEXT_2])
def test_글자를_읽은_캡션은_버린다(text):
    assert _reject_read_text(text) == ""


@pytest.mark.parametrize("text", NORMAL)
def test_정상_캡션은_안_걸린다(text):
    """제일 중요한 케이스다. 수식이 든 정상 캡션을 죽이면 가드가 손해가 된다."""
    assert _reject_read_text(text) == text


def test_빈_입력은_빈_문자열():
    assert _reject_read_text("") == ""
    assert _reject_read_text(None) == ""


def _png(fill):
    from PIL import Image
    f = Path(tempfile.mkdtemp()) / "c.png"
    Image.new("RGB", (80, 60), fill).save(f)
    return str(f)


def test_단색_크롭은_캡션을_안_단다():
    assert _is_blank_crop(_png("white")) is True


def test_내용_있는_크롭은_통과한다():
    from PIL import Image, ImageDraw
    f = Path(tempfile.mkdtemp()) / "c.png"
    im = Image.new("RGB", (80, 60), "white")
    ImageDraw.Draw(im).rectangle([10, 10, 70, 50], fill="black")
    im.save(f)
    assert _is_blank_crop(str(f)) is False


def test_못_읽으면_막지_않는다():
    """판단이 안 서면 캡션을 다는 쪽으로 기운다."""
    assert _is_blank_crop("/does/not/exist.png") is False


# ── 가드5 회귀 — AI 가 사람에게 말하듯 쓴 문구가 점자로 나가면 안 된다 (2026-09-07) ────
# 대표 지목 결함. 캡션 캐시 3,057건 전수에서 걸린 30건이 근거이고, 실경로
# (build_visual_drafts→translate_plain) 로 점자까지 나가는 것을 확인했다.
# 이 결함은 조용히 되살아난다 — 프롬프트를 손볼 때마다 모델이 변명 줄을 다시 붙인다.

# 앞줄이 변명, 뒷줄이 진짜 설명. **뒷줄은 살아야 한다.**
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
def test_AI_말투_줄만_걷고_설명은_남긴다(raw, kept):
    assert _strip_ai_voice(raw) == kept


def test_남는_게_없으면_빈_문자열_생략표기로_간다():
    """지어내지 않는다 — 빈 캡션은 기존 생략 표기 경로를 탄다."""
    assert _strip_ai_voice("그림: 읽을 수 없는 기호") == ""


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
    assert _strip_ai_voice(text) == text


def test_가드5_대사_없음_변명_줄을_걷는다():
    """#734 실측 — 만화 프롬프트가 대사를 요구하자 모델이 '대사가 없습니다' 한 줄을 냈다."""
    src = "만화: 한 사람의 인생을 다섯 시기로 나누어 보여 주고 있음.\n이 그림에는 말풍선 대사가 없습니다.\n현재: 교복 입고 가방 멘 학생이 서 있다."
    assert _strip_ai_voice(src) == "만화: 한 사람의 인생을 다섯 시기로 나누어 보여 주고 있음.\n현재: 교복 입고 가방 멘 학생이 서 있다."
    # 화자 줄은 그림 안의 말이라 남긴다. 존댓말이 아닌 관측 줄도 남긴다.
    assert _strip_ai_voice("을: 대사가 없습니다.") == "을: 대사가 없습니다."
    assert _strip_ai_voice("말풍선 안 내용이 그림에 없어 옮길 대사가 없음") == "말풍선 안 내용이 그림에 없어 옮길 대사가 없음"
