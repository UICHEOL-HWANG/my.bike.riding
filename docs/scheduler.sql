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
    insert into collector_request(request_id, captured_at) values (v_id, v_cap);
    v_n := v_n + 1;
  end loop;
  return v_n;
end
$fn$;

create or replace function ttareungi_ingest() returns int
language plpgsql security definer set search_path = public, net as $fn$
declare
  r record; v_json jsonb; v_code text; v_rows int; v_total int := 0;
begin
  for r in
    select cr.request_id, cr.captured_at, resp.status_code, resp.content, resp.created
      from collector_request cr
      join net._http_response resp on resp.id = cr.request_id
     where cr.processed_at is null order by cr.captured_at
  loop
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
                       v_json -> 'RESULT' ->> 'CODE',
                       v_json ->> 'CODE');

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
      (captured_at, fetched_at, station_id, parking_cnt, rack_total, shared)
    select r.captured_at, r.created, e ->> 'stationId',
           case when e ->> 'parkingBikeTotCnt' ~ '^-?\d+$'
                then (e ->> 'parkingBikeTotCnt')::int end,
           case when e ->> 'rackTotCnt' ~ '^-?\d+$'
                then (e ->> 'rackTotCnt')::int end,
           case when e ->> 'shared' ~ '^-?\d+$'
                then (e ->> 'shared')::int end
      from jsonb_array_elements(v_json -> 'rentBikeStatus' -> 'row') as e
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
      from jsonb_array_elements(v_json -> 'rentBikeStatus' -> 'row') as e
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
