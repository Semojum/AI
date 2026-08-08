"""
GPT-4o로 크롭 이미지를 한국어 텍스트로 묘사.
image/cartoon/chart 각각 다른 프롬프트 사용.
"""
import re
import base64
import hashlib
import os
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI
from app.core.config import config

load_dotenv()

_client: OpenAI | None = None

# 프롬프트는 「점자 자료 제작 지침」 6.1.4 시각 자료 설명을 근거로 한다.
#   (1) 간결한 문장 — 가능한 적은 수의 단어로
#   (2) 핵심 내용 전달 — 핵심에 초점
#   (3) 명료한 표현 — 한 번 읽고 이해되도록
#   (4) 단계적 접근 — 전체 윤곽 → 부분
#   (6) 개조식 표현 — 과정·흐름은 위계 있는 개조식
#   (7) 진술적 설명 — 사실을 문장으로 진술(대부분의 시각 자료)
#   (8) 독자 특성 — 주제에 적합한 단어
# 6.3.4(2): 점역자 주표 안에 '시각 자료 유형: 추가 설명문' 형식.
# ★ 색상·분위기 같은 시각적 인상은 규정이 요구하지 않는다(핵심 내용 아님).
#   마크다운·머리말 금지 — 점자로 옮길 평문이어야 한다.
# ★ 규정 정답과 대조해 보니(kpi_regulation.py, 2026-07-17) 우리 캡션은 R 22% / P 11% —
#   내용은 담는데 2~4배 길다. 원인 두 가지가 규정 원문에 그대로 있다:
#     (1) "간결한 **어구**나 문장" — 완전한 문장을 강요할 필요가 없다.
#     (6) "과정 흐름에 대한 설명은 위계가 있는 **개조식 항목**으로" — 산문으로 풀면 안 된다.
#   그리고 (2) "핵심 내용"은 **무엇을 뜻하는지**다. 규정 정답은 "현재: 학교에 다니고 있다"인데
#   우리는 "교복을 입고 책가방을 멘 학생이 서 있음"이라 적었다 — 외형은 핵심이 아니다.
_COMMON = (
    "당신은 시각장애 학생용 점자 교과서를 만드는 점역사입니다.\n"
    "「점자 자료 제작 지침」 6.1.4에 따라 설명하세요.\n"
    "- 이 자료가 **무엇을 뜻하는지**를 쓰세요. 무엇이 보이는지가 아닙니다 (규정 2).\n"
    "  옷차림·자세·표정·위치·색은 그 뜻에 필요할 때만 씁니다. 대개는 필요 없습니다.\n"
    "  예: '학교에 다니고 있다'(O) / '교복을 입고 책가방을 멘 학생이 서 있다'(X)\n"
    "- 가능한 적은 수의 단어로. 완전한 문장이 아니라 어구여도 됩니다 (규정 1).\n"
    "- 과정·흐름은 산문으로 풀지 말고 개조식으로. 화살표 →를 쓰세요 (규정 6).\n"
    "- 한 번 읽고 이해되도록 명료하게 (규정 3).\n"
    "- 전체 윤곽을 한 줄로 먼저, 그 다음 부분을 나누어 (규정 4).\n"
    "- 자료 **안의 이름표·수치**는 그대로 옮기세요. 지어내지 마세요.\n"
    # ── 아래 넷은 「점자 도서 제작 지침」 3장 2절 정답 24건을 실측해 뽑은 규칙이다
    #    (2026-08-08 QA 16번, tools/…/step16_gold_spans.py). 괄호 안이 정답에서의 빈도.
    "- **짧게.** 정답 설명은 한글 28자(중앙값)입니다. 두 문장을 넘기지 마세요.\n"
    "- **색·음영을 쓰지 마세요**(정답 24건 중 1건, 그것도 대사 안의 '세 가지 색' 인용).\n"
    "  진한/연한/짙은 음영, 흰색 테두리, 범례 색 대응 — 전부 쓰지 않습니다.\n"
    "- **도형·장식을 쓰지 마세요**(정답 0건). 아이콘·배지·말풍선 모양·둥근 테두리·타원.\n"
    "- **화면 위치를 쓰지 마세요**(정답 0건). 왼쪽/오른쪽/상단/하단/가운데/나란히.\n"
    "  위치가 곧 내용인 그림(자리 배치도 등)에서만 예외입니다.\n"
    "- **'~를 나타낸 그림이다', '보인다', '그려져 있다' 같은 말을 쓰지 마세요**(정답 0건).\n"
    "  유형은 맨 앞 제시어가 이미 밝힙니다.\n"
    # QA 10번(2026-08-08): 캡션이 수식을 `y = x² + 3`처럼 유니코드로 적어 왔다. 수식 OCR
    # 경로(MinerU/FormulaNet)는 LaTeX을 내므로 같은 쪽 안에서 표기가 두 갈래가 되고,
    # 점역기는 LaTeX을 전제로 첨자·수표를 붙인다. 표기를 한쪽으로 모은다.
    # ※ 이 지시는 확률적이라 보증이 아니다 — 결정적 방어는 inline_math의 유니코드 첨자
    #   정규화(kor_math_rules.unicode_scripts_to_latex)가 맡는다.
    "- 수식은 반드시 LaTeX으로, `$…$` 안에 적으세요. 예: $y=x^{2}+3$ · $\\frac{1}{2}$\n"
    "  x²·½·×·÷·√ 같은 유니코드 수학 기호를 쓰지 마세요.\n"
    "- 마크다운(#, **, 목록 기호)·머리말·인사말 없이 평문만 출력하세요.\n"
)

_PROMPTS = {
    # 정답 실측(지침 3장 2절): 그림·사진 설명 11건 중
    #   · 대상이 하나면 **이름만**(명사구) — 예3-26 '퍼킨스 점자 타자기', 예3-90 '고추장찌개',
    #     예3-18 '파르테논 신전'. 부분 묘사(상단/자판/하단)는 한 건도 없다.
    #   · 대상이 여럿이면 **이름표를 쉼표로 나열** — 예3-19 '손잡이형 확대경, 서랍식 확대경, …',
    #     예3-20 '1) 수소원자의 구조, 2) 탄소원자의 구조'. 각 항목을 풀어쓰지 않는다.
    "image": _COMMON + (
        "이 그림의 내용을 사실 위주로 진술하세요 (규정 7).\n"
        "- 그린 대상이 **하나**면 그 이름만 적으세요. 문장으로 늘리지 마세요.\n"
        "  예) '사진: 퍼킨스 점자 타자기'(O) / '사진: 손잡이 달린 몸체에 자판이 배열된…'(X)\n"
        "- 대상이 **여럿**이면 각 이름표를 쉼표로 이어 나열만 하세요. 항목마다 설명을 붙이지 마세요.\n"
        "- 부분(상단·자판·하단 …)으로 쪼개 묘사하지 마세요.\n"
        "- 그림 밖 본문 글까지 옮기지 마세요. 그림 **안의** 이름표만 옮깁니다.\n"
        # 예3-27: 번호가 붙은 자리 찾기 그림 — 정답은 번호마다 한 줄, 위치어가 곧 내용이다
        #         ('① 계단 옆에 작은 분수가 있다.').
        # 예3-24: 시간 단계 그림 — 정답은 '현재: 학교에 다니고 있다.'처럼 '항목: 서술' 한 줄씩.
        # 두 경우를 한 줄로 압축하면(쉼표 나열·화살표 사슬) 정답이 담은 내용이 사라진다.
        "- 그림에 **번호(①②③)나 단계·시기 이름**이 붙어 있으면 그 수만큼 **줄을 나눠**\n"
        "  '① 무엇이 어디에 있다' 또는 '단계 이름: 무엇을 한다' 한 줄씩 적으세요.\n"
        "  이때는 위치어(옆·앞·위·아래)를 써도 됩니다 — 위치가 곧 내용입니다.\n"
        "  쉼표로 이어 붙이거나 화살표 사슬(A → B → C)로 압축하지 마세요."
    ),
    # ★ 만화는 「제작 지침」 §5.3에 **정해진 표기 형식**이 있다(2026-08-07 QA 12·13번).
    #   §5.3     만화의 기본 형식은 '5.2 대본'을 따른다.
    #   §5.3.3(1) 장면 번호는 '장면 1' 형식으로 5칸에 점역자 주표.
    #   §5.3.3(2)(3) 인물의 대화는 인물별로 줄을 바꿔 3칸에, 인물명과 대사는 쌍점(:)으로 구분.
    #   §5.3.3(5) 인물명을 알 수 없으면 특징으로 부른다(남학생1·모자 쓴 부인). 주표 안 씀.
    #   §5.3.3(6)(7) 행동·표정 설명은 필요할 때만, 대사 자리에 점역자 주표로.
    #   §5.3.2    한 장면이고 대화가 없을 때만 장면 설정을 설명한다.
    #   BBPG 3장 9)(1)② 컷과 컷 사이에는 빈 줄을 두지 않는다.
    #   종전 프롬프트는 "장면과 등장인물을 설명하고 … 인용"이라 산문 줄거리를 먼저 쓰고
    #   대사를 빠뜨렸다(실측: job_260807160446 p1 만화 = 대사 0줄, 상황 1줄).
    #   ★ 2026-08-08 실측으로 되돌린 것: 새 대본 프롬프트로 바꾸자 **대사 재현율이
    #   98.1% → 88.5%로 떨어졌다**(만화 45장, 말풍선 정답 52줄을 opus-5로 따로 뽑아 채점).
    #   형식은 규정에 맞게 갔는데 내용을 흘렸다 — 지시가 길어지자 "빠짐없이 인용"이 묻혔다.
    #   그래서 **구 프롬프트의 그 한 문장을 맨 앞으로** 되돌린다. 대본 형식은 그대로 둔다
    #   (지어낸 대사 47→7줄·군더더기 상황설명 87→29줄은 새 프롬프트가 얻은 것이라 지킨다).
    "cartoon": _COMMON + (
        "말풍선 대사는 **하나도 빠짐없이 원문 그대로** 인용하세요. 이것이 가장 중요합니다.\n"
        "그 대사를 「제작 지침」 §5.3 만화 표기 형식으로 옮기세요. 줄거리 요약이 아니라 **대본**입니다.\n"
        "출력 형식(이 형식만, 다른 머리말·총평·해설 금지):\n"
        "만화: (만화 전체를 한 줄로 나타내는 짧은 제목)\n"
        "장면 1\n"
        "인물명: 대사\n"
        "인물명: 대사\n"
        "장면 2\n"
        "인물명: 대사\n"
        "\n"
        "지켜야 할 것:\n"
        "- **말풍선·생각풍선 대사는 하나도 빠뜨리지 말고 원문 그대로** 옮기세요. 요약·의역 금지 (§5.3.3(2)).\n"
        "- 인물명과 대사는 쌍점(:)으로 구분하고, 인물마다 줄을 바꾸세요 (§5.3.3(3)).\n"
        "- 인물 이름이 만화에 없으면 특징으로 부르세요 — 남학생1·여학생2·모자 쓴 부인 (§5.3.3(5)).\n"
        "  같은 인물은 장면이 바뀌어도 같은 이름으로 부르세요 (§5.3.3(4)).\n"
        "- 칸이 하나면 '장면' 줄을 쓰지 말고 대사만 적으세요.\n"
        "- **대사가 있으면 상황 설명을 쓰지 마세요.** 대사만으로 내용이 통합니다. 대사가 전혀 없는\n"
        "  칸에서만 그 칸 자리에 '(상황) 무엇이 일어나는지'를 한 줄 적으세요 (§5.3.2).\n"
        "- 표정·행동은 대사만으로 뜻이 안 통할 때만 '(상황) …' 한 줄로 (§5.3.3(6)).\n"
        "- **줄 사이에 빈 줄을 넣지 마세요** (BBPG 3장 9)(1)②).\n"
        "- 마지막에 전체 줄거리·흐름·요약을 다시 붙이지 마세요. 제목 줄이 그 몫입니다."
    ),
    # 도표(모식도·구조도·개념도·흐름도·조직도·계통도·지도) — 수치를 찍지 않는 도식.
    # 지침 §6.1.4(6) "과정 흐름은 위계 있는 개조식", (2) 핵심 내용.
    # 정답 실측: 화살표 →는 24건 중 2건뿐이고 **둘 다 과정 도식**이다(예3-22 운영도,
    # 예3-51 순서도). 조직도(예3-46)는 화살표 0개 — 위계 번호 '1. / 1) / ①'로만 적는다.
    # 연표(예3-47)는 사건을 시간순으로 나열할 뿐 화살표를 쓰지 않는다.
    "diagram": _COMMON + (
        "이 도식이 **무엇을 나타내는지**를 한 줄로 먼저 밝히고(모식도·구조도·개념도·흐름도·"
        "조직도·계통도·지도 중 무엇인지 그 말을 쓰세요), 그 다음 구성 요소를 옮기세요.\n"
        "- 도식 안의 이름표·글자는 그대로 옮기세요. 하나도 빠뜨리지 마세요.\n"
        "- **조직도·계통도·구조도는 화살표를 쓰지 말고 위계 번호로** 적으세요 —\n"
        "  큰 항목 '1.', 그 아래 '1)', 그 아래 '①'. 층이 깊어질 때마다 한 단계 내립니다.\n"
        "- **화살표 →는 순서도·흐름도처럼 순서가 뜻인 도식에만** 쓰세요.\n"
        "- 연표는 '시기: 사건' 한 줄씩, 화살표 없이 시간순으로 적으세요.\n"
        "- 위아래·안팎 같은 배치는 그것이 뜻을 가질 때만 적으세요.\n"
        "- 없는 수치를 지어내지 마세요. 도식에 수치가 없으면 수치를 쓰지 않습니다."
    ),
    # 정답 실측: 그래프 예시 6건(예3-32~3-36·3-45)은 **제목 + '항목: 값' 나열이 전부**다.
    # 추세·해석 문장(계속 증가, ~보다 높음)은 0건 — 그건 본문이 할 말이다.
    "chart": _COMMON + (
        "이 차트의 종류·제목·축 이름을 먼저 밝히고, 데이터 값을 정확히 옮기세요. "
        "수치는 하나도 빠뜨리거나 바꾸지 마세요.\n"
        "- **추세·비교·해석 문장을 붙이지 마세요**(정답 그래프 6건 중 0건). "
        "'계속 증가', '~보다 높음', '전 항목 중 …' 같은 줄을 쓰지 않습니다. 수치만 옮깁니다.\n"
        # 도서지침 예3-32(비율)·3-34(막대) 실측 형식: 데이터는 '항목: 값' 한 줄씩.
        "데이터는 지침 형식대로 '항목: 값' 을 한 줄에 하나씩 적으세요. "
        "예)\n양반: 26.29%\n상민: 59.78%\n"
        "쉼표로 이어 붙이지 마세요. 그룹(연도 등)이 나뉘면 그룹명을 한 줄로 먼저 적으세요."
    ),
}



def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=config.openai_api_key or None)
    return _client


# 백엔드 전환 — 모델 비교 실험용. 기본은 기존 GPT-4o 경로 그대로.
#   CAPTION_BACKEND=anthropic CAPTION_MODEL=claude-sonnet-5
def _caption_anthropic(b64: str, mime: str, prompt: str) -> str:
    import anthropic
    from app.core.limits import estimate_tokens, llm_limiter
    from app.utils.req_log import inc_gpt4o
    # 계정 분당 상한(요청·토큰). 동시 연결은 이미 caption_slot이 조인다.
    # b64는 원본의 4/3배라 실제 바이트로 환산해 넘긴다.
    llm_limiter().acquire_sync(estimate_tokens(prompt, len(b64) * 3 // 4), 500)
    inc_gpt4o()                       # 호출 수 집계는 공용
    client = anthropic.Anthropic(api_key=config.anthropic_api_key or None, timeout=60.0, max_retries=1)  # 행 방지(2026-07-19 스톨 실측)
    # ★ thinking을 꺼야 한다(2026-08-08 QA 16번 실측). claude-sonnet-5는 `thinking`을 안 주면
    #   **적응형 사고가 기본**이고, max_tokens는 사고+본문 합계 상한이라 복잡한 그림에서
    #   500토큰을 사고가 다 먹고 캡션이 **빈 문자열**로 돌아온다
    #   (예3-50 순서도: stop_reason=max_tokens, thinking_tokens=499, text 블록 0개).
    #   규정 정답 22건 중 3건(14%)이 이 경로로 빈 캡션이었다. 캡셔닝은 묘사 과제라
    #   사고가 품질을 올리지 않는다 — 끄는 쪽이 정확하고 싸다.
    resp = client.messages.create(
        model=os.getenv("CAPTION_MODEL", "claude-sonnet-5"),
        max_tokens=500,
        thinking={"type": "disabled"},
        messages=[{
            "role": "user",
            "content": [
                {"type": "image",
                 "source": {"type": "base64", "media_type": mime, "data": b64}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    _record_usage(resp)
    return "".join(b.text for b in resp.content if b.type == "text").strip()


_USAGE = {"calls": 0, "in": 0, "out": 0}


def _record_usage(resp) -> None:
    u = getattr(resp, "usage", None)
    if not u:
        return
    _USAGE["calls"] += 1
    _USAGE["in"] += getattr(u, "input_tokens", 0) or 0
    _USAGE["out"] += getattr(u, "output_tokens", 0) or 0


def usage_report() -> dict:
    """이번 프로세스의 캡셔닝 API 사용량(호출·토큰). 비용 보고용."""
    return dict(_USAGE)


# 유형 제시어(§6.3.4(1)): 캡션 첫머리를 자료 유형으로 시작한다. LLM 프롬프트가 아니라
# rule-based로 붙인다 — 분류기가 유형을 이미 알고, 규정 틀 검증(kpi_regulation.py)에서
# LLM이 제시어를 자주 빼먹는 게 최대 실패 항목이었다(2026-07-17, 틀 통과 8/18의 주원인).
_TYPE_WORD = {"image": "그림", "cartoon": "만화", "chart": "그래프", "chart_graph": "그래프",
              "diagram": "도표"}
_TYPE_WORDS_ALL = ("그림", "사진", "그래프", "삽화", "만화", "지도", "표", "도표")


_TYPE_COLON_RES = None  # lazy — 유형 제시어+쌍점 패턴


def _has_type_colon(s: str) -> bool:
    """유형 제시어(그림·그래프 등)+쌍점으로 시작하는가 — 지침 §6.3.4 '유형, 쌍점, 내용'."""
    global _TYPE_COLON_RES
    if _TYPE_COLON_RES is None:
        _TYPE_COLON_RES = re.compile(
            r"^(?:" + "|".join(map(re.escape, _TYPE_WORDS_ALL)) + r")\s*[:：]")
    return bool(_TYPE_COLON_RES.match(s))


# 제목줄 패턴: 유형+번호("그림 2-1." "표 1.") — 제시어가 아니라 자료 제목이다(지침 예3-20).
_TITLE_LINE_RE = re.compile(
    r"^(?:" + "|".join(map(re.escape, _TYPE_WORDS_ALL)) + r")\s*\d+(?:[.\-]\d+)*\.?\s")


def _ensure_type_word(text: str, image_type: str) -> str:
    """지침 §6.3.4: 설명 본문은 '유형 제시어 + 쌍점'으로 시작해야 한다.

    ⚠ 단순 startswith(유형) 판정은 제목줄("그림 2-1. …")을 제시어로 오판해 본문
    제시어를 생략시켰다(지침 예3-20 프레임 검사 실측, 2026-07-19). 쌍점까지 요구하고,
    제목줄이면 제목은 유지한 채 다음 본문 앞에 제시어를 삽입한다.
    """
    t = (text or "").strip()
    if not t:
        return t
    if _has_type_colon(t):
        return t
    tw = _TYPE_WORD.get(image_type, "그림")
    if _TITLE_LINE_RE.match(t):
        nl = t.find("\n")
        if nl > 0:
            title, body = t[:nl].rstrip(), t[nl + 1:].strip()
            if body and not _has_type_colon(body):
                return f"{title}\n{tw}: {body}"
            return t
        return t  # 제목 한 줄뿐 — 본문 없음, 그대로
    return f"{tw}: {t}"


def _cache_file(raw: bytes, image_type: str, prompt: str) -> Path | None:
    """★ A/B 판정용 캡션 캐시(2026-08-08). `CAPTION_CACHE_DIR`를 줄 때만 동작한다.

    캡셔닝 LLM은 같은 그림에 매번 다른 캡션을 준다(실측 12/12 상이). 그런데
    `claude-sonnet-5`는 `temperature`를 거부하므로(400) 파라미터로 결정성을 살 수 없다.
    한편 MinerU가 잘라내는 크롭 이미지는 실행 간 **바이트 동일**하다(실측 285장/94쪽
    전량 일치). 그래서 이미지 내용 해시로 캡션을 재사용하면 반복 실행이 결정적이 된다.
    같은 라운드를 두 번 돌려 비교할 때 캡션을 고정하고 점역 변경만 보게 하는 장치다.
    운영 기본값은 꺼짐(환경변수 없음) — 운영 동작은 바뀌지 않는다.
    """
    d = os.getenv("CAPTION_CACHE_DIR")
    if not d:
        return None
    key = hashlib.sha256(
        b"|".join([raw, image_type.encode(),
                   os.getenv("CAPTION_BACKEND", "anthropic").encode(),
                   os.getenv("CAPTION_MODEL", "claude-sonnet-5").encode(),
                   prompt.encode()])
    ).hexdigest()
    p = Path(d)
    p.mkdir(parents=True, exist_ok=True)
    return p / f"{key}.txt"


def caption(image_path: str, image_type: str = "image") -> str:
    """
    image_type: 'image' | 'cartoon' | 'chart'
    Returns Korean description string.
    """
    prompt = _PROMPTS.get(image_type, _PROMPTS["image"])

    with open(image_path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode()

    cache = _cache_file(raw, image_type, prompt)
    if cache is not None and cache.exists():
        return cache.read_text(encoding="utf-8")

    ext = Path(image_path).suffix.lstrip(".").lower()
    mime = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"

    if os.getenv("CAPTION_BACKEND", "anthropic") == "anthropic":
        text = _ensure_type_word(_caption_anthropic(b64, mime, prompt), image_type)
        if cache is not None:
            cache.write_text(text, encoding="utf-8")
        return text

    from app.utils.req_log import inc_gpt4o
    inc_gpt4o()
    resp = _get_client().chat.completions.create(
        model="gpt-4o",
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}},
                    {"type": "text", "text": prompt},
                ],
            }
        ],
        max_tokens=500,
        temperature=0.3,
    )
    text = _ensure_type_word(resp.choices[0].message.content.strip(), image_type)
    if cache is not None:
        cache.write_text(text, encoding="utf-8")
    return text
