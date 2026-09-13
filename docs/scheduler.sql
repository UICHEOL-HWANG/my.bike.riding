-- 따릉이 재고 수집 스케줄러 (pg_cron + pg_net)
--
-- GitHub Actions cron으로 갔다가 되돌아왔다. 실측 결과 */10 예약이
-- 6시간 30분 동안 단 1회만 발화했다(약 3%). 격자 설계는 "지연"은 흡수해도
-- "누락"은 못 막는다. 스케줄이 Postgres 안에 있으면 이 문제가 사라지고,
-- public 저장소의 60일 무활동 자동 비활성화 문제도 함께 사라진다.
--
-- pg_net은 비동기다. 요청을 던지는 작업과 응답을 처리하는 작업을 나눈다.

create or replace function ttareungi_request() returns int
language plpgsql security definer set search_path = public, vault, net as $fn$
declare
  v_key text; v_cap timestamptz; v_id bigint; v_start int; v_n int := 0;
begin
  select decrypted_secret into v_key
    from vault.decrypted_secrets where name = 'seoul_api_key';
  if v_key is null or v_key = '' then
    raise exception 'vault에 seoul_api_key가 없다';
  end if;

  -- 10분 격자로 내림. transform.py와 같은 규칙이라야 두 경로가 같은
  -- captured_at을 만들고 unique(station_id, captured_at)이 중복을 막는다.
  v_cap := date_trunc('hour', now())
           + (floor(extract(minute from now()) / 10) * interval '10 minutes');

  -- 대여소 약 2,700개. 4페이지는 여유분이다. 넘치면 조용히 잘려나가므로
  -- 넉넉히 던진다. 빈 페이지는 INFO-200으로 돌아온다.
  for v_start in 1..3001 by 1000 loop
    select net.http_get(
             'http://openapi.seoul.go.kr:8088/' || v_key || '/json/bikeList/'
             || v_start || '/' || (v_start + 999) || '/',
             timeout_milliseconds := 25000) into v_id;
    insert into collector_request(request_id, captured_at, page_start)
      values (v_id, v_cap, v_start);
    v_n := v_n + 1;
  end loop;
  return v_n;
end
$fn$;

create or replace function ttareungi_ingest() returns int
language plpgsql security definer set search_path = public, vault, net as $fn$
declare
  r record; v_json jsonb; v_code text; v_rows int; v_total int := 0;
  v_rows_json jsonb; v_key text; v_retry_id bigint;
begin
  for r in
    select cr.request_id, cr.captured_at, cr.source, cr.page_start, cr.attempt,
           resp.status_code, resp.content, resp.created
      from collector_request cr
      join net._http_response resp on resp.id = cr.request_id
     where cr.processed_at is null order by cr.captured_at
  loop
    -- 본문이 비어 오면 API 응답이 아니라 전송 실패다. 이걸 'API 에러'로
    -- 뭉뚱그리면 진짜 에러와 구분이 안 된다.
    if r.content is null or btrim(r.content) = '' then
      -- 한 페이지가 비어 오면 그 페이지에 있던 대여소만 통째로 빠진다.
      -- 실시간은 정시가 아닌 격자(:10, :20 …)도 만들어서 bikeListHist로
      -- 복구할 수 없다 — 그 자리에서 다시 던지는 게 유일한 기회다.
      --
      -- 같은 10분 창 안에서만, 한 번만 재시도한다. 창을 넘기면 다른 시각의
      -- 재고를 이 격자에 넣는 셈이 되고, 무한 재시도는 장애를 키운다.
      -- 재시도를 2회까지 허용한다. 1회로는 부족했다 — 2026-09-10 01:10과
      -- 01:20이 재시도분마저 비어서 2/14로 남았다.
      --
      -- 간격은 자연히 벌어진다. 재시도 요청은 다음 ingest(매분)에서
      -- 처리되므로 시도 사이가 약 1분이고, 10분 창 안에 넉넉히 들어간다.
      if r.source = 'realtime'
         and r.attempt < 2
         and r.page_start is not null
         and now() < r.captured_at + interval '10 minutes'
      then
        select decrypted_secret into v_key
          from vault.decrypted_secrets where name = 'seoul_api_key';
        if v_key is not null and v_key <> '' then
          select net.http_get(
                   'http://openapi.seoul.go.kr:8088/' || v_key || '/json/bikeList/'
                   || r.page_start || '/' || (r.page_start + 999) || '/',
                   timeout_milliseconds := 25000) into v_retry_id;
          insert into collector_request(request_id, captured_at, source,
                                        page_start, retry_of, attempt)
            values (v_retry_id, r.captured_at, r.source, r.page_start,
                    r.request_id, r.attempt + 1);
          update collector_request set processed_at = now(),
                 note = format('빈 응답 (status=%s) → 재시도 %s (%s회차)',
                               coalesce(r.status_code::text, '없음'),
                               v_retry_id, r.attempt + 1)
           where request_id = r.request_id;
          continue;
        end if;
      end if;

      update collector_request set processed_at = now(),
             note = format('빈 응답 (status=%s)%s',
                           coalesce(r.status_code::text, '없음'),
                           case when r.attempt > 0
                                then format(' (%s회차 재시도분, 포기)', r.attempt)
                                else '' end)
       where request_id = r.request_id;
      continue;
    end if;

    -- 인증 실패 등은 JSON이 아니라 XML로 온다. 여기서 죽으면 이후 요청까지
    -- 영영 처리되지 않으므로 반드시 삼키고 기록만 남긴다.
    begin
      v_json := r.content::jsonb;
    exception when others then
      update collector_request set processed_at = now(),
             note = 'JSON 아님: ' || left(coalesce(r.content,''), 120)
       where request_id = r.request_id;
      continue;
    end;

    -- 데이터가 없는 페이지는 RESULT를 rentBikeStatus 안이 아니라 최상위에
    -- 담아 온다. 두 자리를 모두 봐야 한다 — api.py와 같은 판정.
    -- 코드가 세 자리 중 어디에든 올 수 있다. 정상 응답은 rentBikeStatus
    -- 안에, 데이터 없는 페이지는 최상위에 바로 CODE를 담아 온다.
    v_code := coalesce(v_json -> 'rentBikeStatus' -> 'RESULT' ->> 'CODE',
                       v_json -> 'getStationListHist' -> 'RESULT' ->> 'CODE',
                       v_json -> 'RESULT' ->> 'CODE',
                       v_json ->> 'CODE');

    -- 실시간과 백필이 봉투 이름만 다르고 필드는 같다. 한 함수로 처리한다.
    v_rows_json := coalesce(v_json -> 'rentBikeStatus' -> 'row',
                            v_json -> 'getStationListHist' -> 'row');

    -- 대여소 수가 페이지 경계에 딱 걸리면 마지막 페이지가 INFO-200으로
    -- 온다. 실패가 아니라 빈 페이지다 — 파이썬 경로와 같은 판정.
    if v_code = 'INFO-200' then
      update collector_request set processed_at = now(), note = '빈 페이지'
       where request_id = r.request_id;
      continue;
    elsif v_code is distinct from 'INFO-000' then
      update collector_request set processed_at = now(),
             note = format('API %s: %s', coalesce(v_code, '(코드없음)'),
                     coalesce(v_json -> 'rentBikeStatus' -> 'RESULT' ->> 'MESSAGE',
                              v_json -> 'RESULT' ->> 'MESSAGE',
                              v_json ->> 'MESSAGE',
                              left(r.content, 100)))
       where request_id = r.request_id;
      continue;
    end if;

    insert into station_snapshot
      (captured_at, fetched_at, station_id, parking_cnt, rack_total, shared, source)
    -- 백필은 방금 받아왔어도 그 시각의 기록이다. fetched_at에 수신 시각을
    -- 넣으면 수신 지연 통계가 오염되므로 captured_at과 같게 둔다.
    select r.captured_at,
           case when r.source = 'hist' then r.captured_at else r.created end,
           e ->> 'stationId',
           case when e ->> 'parkingBikeTotCnt' ~ '^-?\d+$'
                then (e ->> 'parkingBikeTotCnt')::int end,
           case when e ->> 'rackTotCnt' ~ '^-?\d+$'
                then (e ->> 'rackTotCnt')::int end,
           case when e ->> 'shared' ~ '^-?\d+$'
                then (e ->> 'shared')::int end,
           r.source
      from jsonb_array_elements(v_rows_json) as e
     where e ->> 'stationId' in (select station_id from collector_station)
    on conflict (station_id, captured_at) do nothing;
    get diagnostics v_rows = row_count;

    -- 이름·좌표는 같은 응답에 실려온다. 실패해도 다음 실행에서 다시 채울 수
    -- 있으므로 스냅샷과 달리 덮어쓴다.
    insert into station (station_id, name, lat, lon, updated_at)
    select e ->> 'stationId', e ->> 'stationName',
           case when e ->> 'stationLatitude'  ~ '^-?\d+(\.\d+)?$'
                then (e ->> 'stationLatitude')::double precision end,
           case when e ->> 'stationLongitude' ~ '^-?\d+(\.\d+)?$'
                then (e ->> 'stationLongitude')::double precision end,
           r.created
      from jsonb_array_elements(v_rows_json) as e
     where e ->> 'stationId' in (select station_id from collector_station)
    on conflict (station_id) do update
       set name = excluded.name, lat = excluded.lat,
           lon = excluded.lon, updated_at = excluded.updated_at;

    update collector_request set processed_at = now(),
           note = format('%s행 적재', v_rows) where request_id = r.request_id;
    v_total := v_total + v_rows;
  end loop;
  return v_total;
end
$fn$;

-- 백필: 결측 시각만 골라 bikeListHist로 메운다 ------------------------
--
-- 7일 창은 하루가 지날 때마다 하루씩 사라진다. 수집이 몇 시간 끊겨도
-- 다음 실행에서 정시 지점이 자동으로 메워진다. 설계 문서가 걱정했던
-- "실패가 조용히 방치되는" 상황에 대한 안전망이다.
--
-- 시간 단위라 10분 격자는 복원하지 못한다. 정시만 메운다.
create or replace function ttareungi_backfill(p_hours int default 48,
                                              p_max_hours int default 12)
returns int
language plpgsql security definer set search_path = public, vault, net as $fn$
declare
  v_key text; v_id bigint; v_start int; v_n int := 0; v_hour timestamptz;
begin
  select decrypted_secret into v_key
    from vault.decrypted_secrets where name = 'seoul_api_key';
  if v_key is null or v_key = '' then
    raise exception 'vault에 seoul_api_key가 없다';
  end if;

  -- 이미 채운 시각은 건너뛴다. 48시간을 매번 다시 받으면 낭비다.
  --
  -- "시각이 존재하는가"가 아니라 "대여소가 다 왔는가"로 판정한다. 4페이지
  -- 중 하나만 실패하면 일부 대여소만 들어오는데, 시각 존재로만 보면 그
  -- 반쪽 데이터가 영영 재시도되지 않고 조용히 남는다.
  for v_hour in
    select t from (
      -- 최근 2시간은 뺀다. 실시간 수집이 아직 채우는 중인 시각을 결측으로
      -- 보면 매번 불필요한 요청이 나가고, bikeListHist에도 현재 시각
      -- 기록이 아직 없을 수 있다.
      select generate_series(
               date_trunc('hour', now()) - make_interval(hours => p_hours),
               date_trunc('hour', now()) - interval '2 hours',
               interval '1 hour') as t) g
     where (select count(*) from station_snapshot s where s.captured_at = g.t)
           < (select count(*) from collector_station)
     order by t
     limit p_max_hours
  loop
    -- stationDt는 KST다. 실측 대조로 확인했다 — UTC로 넘기면 9시간
    -- 어긋난 데이터가 들어간다.
    for v_start in 1..3001 by 1000 loop
      select net.http_get(
               'http://openapi.seoul.go.kr:8088/' || v_key || '/json/bikeListHist/'
               || v_start || '/' || (v_start + 999) || '/'
               || to_char(v_hour at time zone 'Asia/Seoul', 'YYYYMMDDHH24'),
               timeout_milliseconds := 25000) into v_id;
      insert into collector_request(request_id, captured_at, source, page_start)
        values (v_id, v_hour, 'hist', v_start);
    end loop;
    v_n := v_n + 1;
  end loop;
  return v_n;
end
$fn$;
