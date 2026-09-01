"""점자 조판 공용 상수.

여러 braille 모듈(translator·layout·text/table/image/… braille)에서 중복 정의하던
32칸·26줄을 한 곳으로 모은다. (NLD 1장1절3: 가로 32칸·세로 26줄 기본 규격.)
"""

COLS = 32  # 한 줄 칸 수
ROWS = 26  # 한 페이지 줄 수 (NLD 1장1절3: 세로 26줄)

# 2026-09-01 — DOUBLE_SIDED 를 뺐다(결정 F).
#   어느 면에 페이지행을 넣나는 braille-assist `page_row_on`(odd|every|even|none)이 정본이고,
#   조판이 FE·BE로 넘어간 뒤 AI 쪽 판정은 저장·디버그용 미리보기에만 남았다.
#   두 벌로 두면 언젠가 갈린다.


# ── 감쌈 붙임표 자리표시자 (translator._paren_repl → inline_math·translator 공유) ──
# 도서 관행 감쌈 "(가)→-가-"의 붙임표는 원문 하이픈이 아니라 조판 기호다.
# 요소 단위로 먼저 붙여 두면 줄 단위 경로의 음수 부호 규칙(_NEG_NUM_RE)이 그 하이픈을
# 뺄셈표로 재해석한다("(2010 수능)"→⠔…). 그래서 감쌈분만 유니코드 비문자로 표시해
# 음수 판정 구간을 통과시키고, 판정이 끝난 자리에서 원래 하이픈으로 되돌린다.
# 비문자(U+FDD0/1)는 실문서에 나올 수 없고 sanitize_for_braille의 PUA·제어문자
# 범위에도 걸리지 않는다. 자리표시자는 하이픈의 대역이므로 inline_math의 수식 구간
# 원자 집합에도 하이픈과 같이 넣는다 — 넣지 않으면 수식 구간이 표식에서 쪼개져
# 라우팅이 달라진다(수학2 실측 173요소).
WRAP_HYPHEN_OPEN = "\ufdd0"
WRAP_HYPHEN_CLOSE = "\ufdd1"
