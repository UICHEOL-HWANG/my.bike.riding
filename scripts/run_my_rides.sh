#!/bin/bash
# launchd에서 부르는 래퍼. 이용내역을 받아 Supabase에 적재한다.
#
# launchd는 PATH가 빈약해서 uv를 절대경로로 부른다.
#
# 실패가 조용히 방치되는 게 최악이다. 이 작업은 한 주에 한 번 돌아서
# 사람이 로그를 챙겨보지 않는다. 그래서 실패하면 알림을 띄운다.

set -uo pipefail

PROJECT="/Users/uicheol_hwang/my.bike.riding"
UV="/Users/uicheol_hwang/.local/bin/uv"
LOG_DIR="$HOME/Library/Logs/ttareungi"
LOG="$LOG_DIR/my_rides.log"

mkdir -p "$LOG_DIR"
cd "$PROJECT" || exit 1

{
  echo "───────────────────────────────────────────"
  echo "$(date '+%Y-%m-%d %H:%M:%S') 시작"
} >> "$LOG"

"$UV" run python scripts/fetch_my_rides.py >> "$LOG" 2>&1
status=$?

echo "$(date '+%Y-%m-%d %H:%M:%S') 종료 (exit=$status)" >> "$LOG"

if [ $status -ne 0 ]; then
  tail_msg=$(tail -3 "$LOG" | tr '\n' ' ' | cut -c1-180)
  osascript -e "display notification \"$tail_msg\" with title \"따릉이 이용내역 수집 실패\" subtitle \"exit=$status\"" 2>/dev/null
fi

# 로그가 무한정 자라지 않게 최근 2000줄만 남긴다.
if [ "$(wc -l < "$LOG")" -gt 2000 ]; then
  tail -2000 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi

exit $status
