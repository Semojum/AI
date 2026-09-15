#!/usr/bin/env bash
# develop 에 새로 들어온 커밋에서 이슈 번호를 뽑아 닫는다.
#
# 워크플로 안에 인라인으로 두면 **돌려 볼 수가 없다.** 파일로 두면 `DRY_RUN=1` 로
# 실제 이력에 대고 돌려 확인할 수 있다(2026-09-15, 추가 4번 "실제로 동작하는지 확인해라").
#
#   RANGE    검사할 커밋 범위(기본: BEFORE..AFTER, 없으면 마지막 1개)
#   DRY_RUN  1 이면 닫지 않고 "닫을 번호" 만 찍는다
set -uo pipefail

: "${GITHUB_REPOSITORY:?GITHUB_REPOSITORY 필요}"
DRY_RUN="${DRY_RUN:-0}"

if [ -n "${RANGE:-}" ]; then
  range="$RANGE"
elif git cat-file -e "${BEFORE:-}^{commit}" 2>/dev/null; then
  range="${BEFORE}..${AFTER}"
else
  range="${AFTER}~1..${AFTER}"
fi

msgs=$(git log --format='%s%n%b' "$range" 2>/dev/null || git log -1 --format='%s%n%b')

# ① 커밋에서 — 제목의 [#N] 과 본문의 닫기 낱말 뒤 #N. 제목 끝의 (#N) 은 PR 이라 뺀다.
pick() {
  grep -oiE '(\[#[0-9]+\]|(closes|fixes|resolves|refs)[[:space:]]*#[0-9]+)' \
    | grep -oE '[0-9]+'
}
nums=$(printf '%s\n' "$msgs" | pick | sort -un)

# ② PR 본문에서 — squash 가 PR 본문을 커밋 메시지에 안 실어 줄 때가 있다.
#    실측(2026-09-15): develop 최근 12커밋 중 셋(#859·#866·#867)이 본문에만 `Closes #N` 이
#    있어 커밋만 보는 종전 판정으로는 **하나도 안 닫혔다**(#857·#852·#864 를 사람이 손으로 닫음).
#    squash 커밋 제목 **끝**의 `(#N)` 이 그 PR 번호다.
prs=$(printf '%s\n' "$msgs" | grep -oE '\(#[0-9]+\)[[:space:]]*$' | grep -oE '[0-9]+' | sort -un)
for p in $prs; do
  pr=$(gh api "repos/${GITHUB_REPOSITORY}/pulls/${p}" --jq '.title, .body' 2>/dev/null) || {
    echo "PR 본문 못 읽음: #${p} (건너뜀)"; continue; }
  more=$(printf '%s\n' "$pr" | pick)
  [ -n "$more" ] && nums=$(printf '%s\n%s\n' "$nums" "$more" | grep -E '^[0-9]+$' | sort -un)
done

[ -z "$nums" ] && { echo "닫을 이슈 없음"; exit 0; }

for n in $nums; do
  # `gh --jq` 로 한 번에 읽는다 — `jq` 바이너리를 따로 요구하지 않는다(로컬에서도 돌아야 한다).
  info=$(gh api "repos/${GITHUB_REPOSITORY}/issues/${n}" \
           --jq '[(.pull_request.url // ""), .state] | @tsv' 2>/dev/null) || {
    echo "건너뜀: #${n} (그런 번호 없음)"; continue; }
  # ★ PR 과 이슈는 번호 대역을 같이 쓴다. PR 이면 손대지 않는다.
  if [ -n "$(printf '%s' "$info" | cut -f1)" ]; then
    echo "건너뜀: #${n} (이슈가 아니라 PR)"; continue
  fi
  state=$(printf '%s' "$info" | cut -f2)
  if [ "$state" != open ]; then
    echo "건너뜀: #${n} (이미 ${state})"; continue
  fi
  if [ "$DRY_RUN" = 1 ]; then
    echo "닫을 것(dry-run): #${n}"; continue
  fi
  echo "닫는다: #${n}"
  gh issue close "$n" --repo "${GITHUB_REPOSITORY}" \
    --comment "develop 에 머지됐다 (${AFTER:-$range})." || echo "  실패 #${n} — 건너뜀"
done
