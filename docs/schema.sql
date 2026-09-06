-- Supabase에 이 순서로 실행한다.

-- 재고 스냅샷. 이 프로젝트의 본체다.
-- 실시간 API는 호출 시점만 주고 과거 조회가 없어서, 여기 없는 시각은
-- 영구히 복원 불가다.
create table if not exists station_snapshot (
  id            bigserial primary key,
  captured_at   timestamptz not null,   -- 10분 격자로 내린 값
  fetched_at    timestamptz not null,   -- 실제 응답 수신 시각
  station_id    text        not null,
  parking_cnt   int,
  rack_total    int,
  shared        int,                    -- API 원본명. 실제 의미는 거치율(%)
  created_at    timestamptz default now(),
  unique (station_id, captured_at)
);
create index if not exists station_snapshot_by_station
  on station_snapshot (station_id, captured_at desc);

-- 대여소 마스터. 스냅샷과 함께 갱신된다.
create table if not exists station (
  station_id  text primary key,
  name        text,
  lat         double precision,
  lon         double precision,
  updated_at  timestamptz
);

-- 본인 이용내역. 학습의 정답 레이블이 된다 —
-- 평소와 다른 대여소에서 빌린 날이 곧 "주 대여소 재고 실패"다.
create table if not exists my_ride (
  rent_hist_seq   text primary key,   -- 대여일시는 같은 분에 2건이 가능해 키로 못 쓴다
  bike_no         text,
  rented_at       text not null,      -- 'YYYY-MM-DD HH:MM' 원문 그대로
  rent_station    text not null,      -- '1741. 제일강산수산입구' 형태
  returned_at     text,
  return_station  text,
  distance_km     double precision,   -- 숨은 칸이라 라벨 없음. 위치로 추정
  created_at      timestamptz default now()
);
create index if not exists my_ride_by_time on my_ride (rented_at);

-- 상세 페이지(moveUseHistoryDetailView.do)에서 얻는 값.
-- carbon_kg는 거리 x 0.232의 순수 파생값이라 정보량이 없다. 원본 보존용.
-- calories는 대체로 거리 x 34지만 속도에 따라 어긋나는 건이 있다.
-- duration_min은 사이트가 계산한 값이라 분 단위 타임스탬프 차이보다 정확하다.
alter table my_ride
  add column if not exists duration_min int,
  add column if not exists calories      double precision,
  add column if not exists carbon_kg     double precision,
  add column if not exists extra_fee     int;
