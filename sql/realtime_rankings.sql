-- 실시간 베스트셀러 전용 테이블. 기존 rankings/collection_runs(주간/분야별)
-- 테이블은 전혀 건드리지 않고, 완전히 별도의 테이블 2개를 새로 만듭니다.
-- Supabase SQL Editor에서 이 파일 내용을 그대로 한 번 실행해주세요.
-- (service_role 키는 기본적으로 RLS를 우회하므로, 기존 테이블들과 마찬가지로
-- 별도 RLS 정책 없이도 test_save_*_realtime.py 수집 스크립트가 바로 쓸 수
-- 있습니다.)

create table if not exists realtime_collection_runs (
  id bigint generated always as identity primary key,
  bookstore text not null,
  status text not null check (status in ('success', 'failed')),
  error_message text,
  item_count integer not null default 0,
  run_at timestamptz not null default now()
);

create table if not exists realtime_rankings (
  id bigint generated always as identity primary key,
  run_id bigint not null references realtime_collection_runs (id),
  collected_at timestamptz not null,
  bookstore text not null,
  rank integer not null,
  title text not null,
  author text,
  publisher text,
  isbn13 text,
  url text,
  match_status text not null,
  rank_change integer,
  created_at timestamptz not null default now()
);

create index if not exists idx_realtime_rankings_bookstore_collected_at
  on realtime_rankings (bookstore, collected_at desc);

create index if not exists idx_realtime_rankings_isbn13
  on realtime_rankings (isbn13);
