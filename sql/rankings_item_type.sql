-- 비도서(오디오북/음반/굿즈 등) 포함 정책 변경을 위한 스키마 변경.
-- 지금까지 실시간(교보/알라딘/예스24) + 예스24 일간 수집 스크립트는
-- 비도서로 판단한 상품을 DB에 저장하지 않고 그냥 건너뛰었습니다. 이제는
-- 비도서도 순위권에 그대로 표시하되, 화면에서 시각적으로만 구분하기
-- 위해 상품 유형을 저장할 컬럼이 필요합니다.
--
-- 값: 'book'(도서, 기본값 아님 - NULL과 구분 없이 취급되도록 프론트에서
--      "item_type이 없거나 'book'이면 일반 도서"로 처리) / 'audiobook' /
--      'magazine' / 'non_book'(그 외 굿즈 등, 서점별로 더 세분화할 근거가
--      없는 경우).
--
-- 기존 store_category 컬럼(분야 분류)과는 완전히 별개 개념입니다 - 이
-- 컬럼은 "이 상품이 책인지 아닌지"만 나타내고, 분야 분류 로직은 전혀
-- 건드리지 않습니다.
--
-- rankings(종합/일간/분야별 공용)와 realtime_rankings 둘 다 필요합니다 -
-- 비도서 제외 로직이 실시간(3사) + 예스24 일간(rankings 테이블 사용)에
-- 걸쳐 있기 때문입니다.
--
-- 반드시 이 SQL을 Supabase에서 먼저 실행한 뒤에 관련 코드를 배포해야
-- 합니다(컬럼이 없는 상태로 INSERT에 item_type을 보내면 실패합니다).

alter table rankings add column if not exists item_type text;
alter table realtime_rankings add column if not exists item_type text;
