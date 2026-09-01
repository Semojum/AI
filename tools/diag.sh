#!/usr/bin/env bash
# 서버·로컬 판 한 줄 진단. 출력을 통째로 복사해 붙일 수 있게 40줄 안으로 낸다.
#
#   bash ~/AI/tools/diag.sh          서버에서
#   bash code/AI/tools/diag.sh       로컬에서
#
# 왜 (2026-08-26 대표 승인)
#   서버 상태를 몰라 하루에 네 번 헛짚었다. 대표가 명령을 네 번 붙여넣으셔야 했고,
#   마지막에 로그를 주셔서야 원인(캡션 캐시)이 잡혔다. 로컬과 서버 출력을 나란히 놓으면
#   차이가 한눈에 보여야 한다 — 그게 이 스크립트의 존재 이유다.
#     로컬  캐시 비어 있음 → 매번 새로 만듦 → "잘 나온다"
#     서버  캐시 있음      → 옛 캡션을 돌려줌 → "안 바뀐다"
#
# ★ 비밀은 찍지 않는다. 키 값·토큰은 **있음/없음**만. 경로의 계정명은 ~ 로 가린다.
set -uo pipefail
cd "$(dirname "$0")/.." 2>/dev/null || exit 1
ROOT="$(pwd)"
HIDE="s|/home/[^/ ]*|~|g; s|/Users/[^/ ]*|~|g"          # 경로 속 계정명 가리개
WINDOW_MIN=60
CUT="$(date -d "-${WINDOW_MIN} minutes" '+%Y-%m-%d %H:%M:%S' 2>/dev/null || echo '')"

echo "== 세모점 AI 진단 · $(date '+%Y-%m-%d %H:%M:%S %Z') =="

# 1. 코드 판
if git -C "$ROOT" rev-parse --git-dir >/dev/null 2>&1; then
  echo "코드   $(git -C "$ROOT" rev-parse --abbrev-ref HEAD) $(git -C "$ROOT" rev-parse --short HEAD) \
($(git -C "$ROOT" log -1 --format=%cd --date=format:'%m-%d %H:%M'))\
$(git -C "$ROOT" diff --quiet 2>/dev/null || echo ' ⚠수정본있음')"
else
  echo "코드   git 저장소가 아니다"
fi

# 2. 서버 프로세스 — 명령줄은 안 찍는다(경로가 들어간다). 개수와 시작 시각만.
PIDS="$(pgrep -f 'app\.core\.main' 2>/dev/null | tr '\n' ' ')"
if [ -n "${PIDS// /}" ]; then
  for p in $PIDS; do
    echo "서버   pid $p 시작 $(ps -o lstart= -p "$p" 2>/dev/null | sed 's/^ *//')"
  done
else
  echo "서버   실행 중인 app.core.main 없음"
fi

# 3. .env — 있고 없고만
ENVF="$ROOT/.env"
if [ -f "$ENVF" ]; then
  keyed() { grep -qE "^[[:space:]]*$1[[:space:]]*=[[:space:]]*[^[:space:]#]" "$ENVF" && echo 있음 || echo "없음 ⚠"; }
  val()   { v=$(grep -E "^[[:space:]]*$1[[:space:]]*=" "$ENVF" | tail -1 | cut -d= -f2- | tr -d '"'"'"' ' | head -c 40); echo "${v:-(기본값)}"; }
  echo "키     ANTHROPIC_API_KEY $(keyed ANTHROPIC_API_KEY) · OPENAI_API_KEY $(keyed OPENAI_API_KEY)"
  echo "캡션   backend=$(val CAPTION_BACKEND) model=$(val CAPTION_MODEL) 캐시경로설정=$([ -n "$(val CAPTION_CACHE_DIR)" ] && echo 있음 || echo 없음)"
else
  echo "키     .env 없음 ⚠"
fi

# 4. 캡션 캐시 — 여기가 로컬·서버가 갈리는 자리다
CACHE="${CAPTION_CACHE_DIR:-$ROOT/storage/caption_cache}"
if [ -d "$CACHE" ]; then
  N=$(find "$CACHE" -type f 2>/dev/null | wc -l)
  echo "캐시   항목 $N · 크기 $(du -sh "$CACHE" 2>/dev/null | cut -f1)"
  if [ "$N" -gt 0 ]; then
    OLD=$(find "$CACHE" -type f -printf '%T@ %TY-%Tm-%Td %TH:%TM\n' 2>/dev/null | sort -n | head -1 | cut -d' ' -f2-)
    NEW=$(find "$CACHE" -type f -printf '%T@ %TY-%Tm-%Td %TH:%TM\n' 2>/dev/null | sort -n | tail -1 | cut -d' ' -f2-)
    FRESH=$(find "$CACHE" -type f -mmin "-$WINDOW_MIN" 2>/dev/null | wc -l)
    echo "       가장 오래된 $OLD · 최신 $NEW · 최근 ${WINDOW_MIN}분 새로 생긴 것 $FRESH"
  fi
else
  echo "캐시   폴더 없음 (캡션을 매번 새로 만든다)"
fi

# 5. 최근 한 시간 — 로그에서 센다
LOG="$ROOT/storage/logs/semojum.log"
if [ -f "$LOG" ] && [ -n "$CUT" ]; then
  recent() { awk -v c="$CUT" -v pat="$1" 'substr($0,1,19) >= c && $0 ~ pat' "$LOG" | wc -l; }
  CAP=$(recent "캡셔닝")
  NEWCACHE=${FRESH:-0}
  HIT="—"
  [ "$CAP" -gt 0 ] && HIT="$(( (CAP - NEWCACHE) * 100 / CAP ))% (근사)"
  echo "최근${WINDOW_MIN}분 캡셔닝 $CAP건 · 새 캐시 $NEWCACHE건 · 적중률 $HIT"
  echo "       MinerU 추출실패 $(recent 'MinerU 추출 실패')건 · 텍스트레이어 폴백 $(recent '폴백으로')건 \
· ERROR $(recent '[[]ERROR[]]')건"
else
  echo "최근${WINDOW_MIN}분 로그 파일 없음: storage/logs/semojum.log"
fi

# 6. 마지막 오류 5줄 — 경로의 계정명은 가린다
echo "-- 마지막 오류 5줄 --"
if [ -f "$LOG" ]; then
  grep -E "\[(ERROR|CRITICAL)\]" "$LOG" 2>/dev/null | tail -5 | cut -c1-150 | sed "$HIDE" || true
  grep -qE "\[(ERROR|CRITICAL)\]" "$LOG" 2>/dev/null || echo "(없음)"
else
  echo "(로그 파일 없음)"
fi

# 7. journalctl 이 없는 환경 고지 — 오늘 CloudShell 에서 이것만 보고 헛짚었다
command -v journalctl >/dev/null 2>&1 \
  || echo "※ 이 환경에는 journalctl 이 없다(CloudShell 등). 위 수치는 전부 파일 로그에서 뽑았다."
