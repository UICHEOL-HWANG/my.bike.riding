#!/bin/bash
# 따릉이 계정 자격증명을 로컬 .env와 GitHub secrets 양쪽에 넣는다.
#
# 두 곳을 따로 관리하면 반드시 어긋난다 — 비밀번호를 바꾸고 한쪽만
# 갱신하면 다음 일요일에 조용히 실패한다. 한 번에 맞춘다.
#
# 값은 화면에 찍지 않고 셸 히스토리에도 남기지 않는다.
#
#   ./scripts/set_bikeseoul_secrets.sh

set -uo pipefail
cd "$(dirname "$0")/.." || exit 1

command -v gh >/dev/null || { echo "gh CLI가 없다."; exit 1; }
gh auth status >/dev/null 2>&1 || { echo "gh 로그인이 필요하다: gh auth login"; exit 1; }

printf '따릉이 아이디: '
read -r BS_ID
printf '따릉이 비밀번호: '
read -rs BS_PW
echo

[ -z "$BS_ID" ] && { echo "아이디가 비었다."; exit 1; }
[ -z "$BS_PW" ] && { echo "비밀번호가 비었다."; exit 1; }

# 1) 로컬 .env — 나머지 키는 건드리지 않는다
touch .env
grep -v '^BIKESEOUL_ID=' .env | grep -v '^BIKESEOUL_PW=' > .env.tmp
{ printf 'BIKESEOUL_ID=%s\n' "$BS_ID"; printf 'BIKESEOUL_PW=%s\n' "$BS_PW"; } >> .env.tmp
mv .env.tmp .env
chmod 600 .env
echo "  .env 갱신됨"

# 2) GitHub secrets — stdin으로 넘긴다. 인자로 주면 ps에 보인다.
printf '%s' "$BS_ID" | gh secret set BIKESEOUL_ID || exit 1
printf '%s' "$BS_PW" | gh secret set BIKESEOUL_PW || exit 1
echo "  GitHub secrets 갱신됨"

unset BS_ID BS_PW

echo
echo "=== 현재 secrets ==="
gh secret list
echo
echo "=== 로컬 .env 키 ==="
grep -o '^[A-Z_]*' .env | sed 's/^/  /'
echo
echo "다음: gh workflow run rides   (수동 실행으로 확인)"
