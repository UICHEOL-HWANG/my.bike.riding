# 따릉이 수집기 최소 버전 — 설계

작성일: 2026-09-04
범위: 인계서([../../../ttareungi-handoff.md](../../../ttareungi-handoff.md)) 작업 순서 1~2번 (수집기 최소 버전 + 스케줄·실패 알림)

## 1. 목적

서울시 공공자전거 실시간 대여정보 API(OA-15493)를 주기적으로 호출해, 관심 대여소의 재고 스냅샷을 Supabase에 적재한다. 실시간 API는 호출 시점의 스냅샷만 주고 과거 조회 수단이 없으므로, 학습 데이터는 이 수집기가 도는 시점부터만 생긴다. 그래서 이것이 프로젝트의 1순위다.

모델링·분석·대시보드는 이 문서의 범위가 아니다.

## 2. 결정 사항

| 항목 | 결정 | 근거 |
|---|---|---|
| 런타임 | Python | 이후 분석·모델링과 같은 언어 |
| 스케줄 | GitHub Actions cron | VM 없음 방침. 지연은 격자 설계로 흡수 |
| 저장소 | `UICHEOL-HWANG/my.bike.riding` (public, `main`) | public이라 Actions 실행 시간이 무료. private면 10분 간격이 무료 한도를 초과한다 |
| 수집 간격 | 10분 | 5분은 Actions 지연으로 결측이 늘고 저장량 2배. 재고 해상도는 10분으로 충분 |
| 대여소 선정 | `stations.yml`에 ID 직접 나열 | 이용 대여소가 고정. 목록에 대안 대여소도 포함 |
| 구조 | 얇은 모듈 4개 | 파싱·필터·시각 계산을 순수 함수로 분리해 네트워크 없이 테스트 |
| 저장 | Supabase, `station_snapshot` upsert | 인계서 방침 |

### 관심 대여소에 대안 대여소를 포함하는 이유

정답지는 "주 대여소에 자전거가 없어 다른 대여소로 걸어간 날"이다. 그날 그 대안 대여소에는 있었는지를 보지 못하면 예측 결과가 행동으로 이어지지 않는다. 따라서 주 대여소 + 평소 걸어가는 대안 대여소를 함께 수집한다.

## 3. 구조

```
collector/
  config.py       # 환경변수 + stations.yml 로드
  api.py          # API 호출, 1000건 페이징, 에러코드 판정
  transform.py    # 응답 → 행 변환 (필터, captured_at 부여)   ← 순수 함수
  store.py        # Supabase upsert
  __main__.py     # 엮기 (python -m collector)
stations.yml
sql/0001_init.sql
tests/
.github/workflows/collect.yml
```

`transform.py`가 이 설계의 중심이다. 네트워크와 DB를 모르는 순수 함수만 두어 테스트 대상을 여기로 모은다.

## 4. 데이터 흐름

1. Actions cron이 10분마다 `python -m collector` 실행
2. `api.fetch_all()` — `1~1000`, `1001~2000`, … 을 `list_total_count`에 도달할 때까지 호출. 실시간 API에는 대여소 ID 필터 파라미터가 없어 전량을 받는다 (대여소 약 3천 개 → 실행당 3~4회 호출)
3. `transform` — 관심 ID 집합으로 필터, `captured_at` 부여, 행 변환
4. `store` — `station_snapshot`에 upsert. 응답에 이름·좌표가 함께 오므로 `station` 마스터도 upsert (덮어쓰고 `updated_at` 갱신)

### 응답 필드

`stationId`, `stationName`, `parkingBikeTotCnt`, `rackTotCnt`, `shared`, `stationLatitude`, `stationLongitude`를 쓴다. 숫자가 문자열로 오는 경우가 있어 변환 시 캐스팅한다. **구현 1단계에서 실제 호출로 필드명과 타입을 확인하고, 그 응답을 테스트 픽스처로 저장한다.**

## 5. captured_at을 10분 격자로 내림한다

이 설계에서 가장 중요한 결정이다.

실행 시각을 그대로 넣으면 Actions 지연 탓에 매 실행이 서로 다른 타임스탬프를 갖는다. 그러면 `unique(station_id, captured_at)`이 아무것도 막지 못해 재실행이나 중복 트리거가 그대로 중복 행이 된다. 또 나중에 `lag(1시간 전 / 24시간 전 / 지난주 같은 시각)` 피처를 만들 때 맞물리는 행이 없어 조인이 지저분해진다.

그래서 수집 시각을 10분 격자로 내려서 `captured_at`에 넣는다 (`10:09:59` → `10:00:00`). 실제 응답 시각은 `fetched_at`에 따로 보존한다.

지연이 10분을 넘겨 격자를 건너뛰면 그 칸은 비운다. **메우지 않는다** — 관측하지 않은 값을 채우면 리크가 된다.

## 6. 스키마

인계서 초안에 `fetched_at` 한 컬럼을 더한다. 스냅샷 1행 = 대여소 × 시점이라는 의도는 그대로다.

```sql
create table station_snapshot (
  id            bigserial primary key,
  captured_at   timestamptz not null,   -- 10분 격자로 내린 값
  fetched_at    timestamptz not null,   -- 실제 응답 수신 시각
  station_id    text        not null,
  parking_cnt   int,
  rack_total    int,
  shared        int,
  created_at    timestamptz default now(),
  unique (station_id, captured_at)
);
create index on station_snapshot (station_id, captured_at desc);

create table station (
  station_id  text primary key,
  name        text,
  lat         double precision,
  lon         double precision,
  updated_at  timestamptz
);
```

`my_ride`는 인계서 초안 그대로 두되 이번 범위에서는 만들지 않는다.

### 저장량

관심 대여소 15개 기준 하루 2,160행, 한 달 약 6.5만 행. Supabase 무료 구간에서 여유롭다.

## 7. 에러 처리

서울시 API는 실패해도 **HTTP 200에 본문으로 에러코드를 실어 보낸다.** 상태 코드만 보면 인증키 오류를 정상으로 착각한다.

- `RESULT.CODE`가 `INFO-000`이 아니면 실패로 처리
- 타임아웃 10초, 3회 재시도 (1s → 2s → 4s)
- **부분 성공은 적재하되 종료 코드는 실패로 낸다.** 받은 데이터는 남기는 게 낫고, 실패는 보여야 한다
- **적재 행이 0이면 실패로 간주한다.** 관심 대여소가 응답에 하나도 없다는 것은 설정 오류이거나 응답 형식 변경인데, 그냥 두면 성공한 얼굴로 빈 데이터를 쌓는다

## 8. 조용한 멈춤 방어와 그 한계

1층: job 실패 시 GitHub 기본 알림 메일.

2층이 문제다. **워크플로 자체가 안 돌면 실패할 job도 없어 알림이 오지 않는다.** GitHub은 공개 저장소에서 활동이 60일간 없으면 스케줄 워크플로를 자동 비활성화한다. 이 저장소는 public이므로 **이 조건이 실제로 적용된다.** 수집기는 커밋할 일이 없는 코드라 정확히 여기에 걸린다.

같은 저장소에 점검 워크플로를 추가해도 함께 비활성화되므로 소용이 없다. 감시는 저장소 밖에 있어야 한다. 이번 범위에서는:

- `station_snapshot`의 최신 `captured_at`을 노출하는 뷰를 만든다
- 이후 대시보드 맨 위에 "마지막 수집: N분 전"을 띄운다. 매일 아침 타기 전에 보게 되므로 사람이 감시자가 된다
- 외부 헬스체크 연동은 다음 과제로 남긴다

완전한 방어가 아니라는 점을 명시해 둔다.

## 9. 테스트

먼저 실제 API를 1회 호출해 응답을 픽스처로 저장하고, 이후 테스트는 네트워크 없이 돌린다.

- **transform** — 관심 ID만 남는지 / 격자 경계 (`10:00:00`, `10:09:59`, `10:10:00`) / 숫자가 문자열로 오는 경우 / 필드 결측 / 응답에 중복 `station_id`
- **api** — 페이징 종료 조건 (총 2,847건이면 3회 호출 후 멈춤) / 에러코드 감지 / 재시도
- **store** — DB 없이 payload 모양과 충돌 처리 지정 검증

실제 Supabase 적재는 로컬 1회 수동 실행으로 눈으로 확인한다.

## 10. 시크릿·설정

GitHub Secrets에 `SEOUL_API_KEY`, `SUPABASE_URL`, `SUPABASE_SERVICE_KEY`. 로컬은 `.env`(gitignore). service key를 쓰는 이유는 RLS를 우회해 적재해야 하기 때문이다. `stations.yml`은 비밀이 아니므로 커밋해 변경 이력을 남긴다.

## 11. 범위 밖

원본 JSON 아카이브(인계서 작업 3번 — 끼울 자리만 비워둔다), 날씨 조인, 공공 파일데이터, 대시보드, 백필, `my_ride` 적재.

## 12. 구현 전 필요한 입력

- **관심 대여소 ID 목록** — 주 대여소 + 평소 걸어가는 대안 대여소
- **GitHub 원격 저장소 주소** — 현재 로컬 디렉터리는 git 저장소가 아니다
