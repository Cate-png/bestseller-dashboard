# 베스트셀러 대시보드 (로컬 실행용)

Supabase에 이미 저장된 교보문고/예스24/알라딘 최신 TOP100 데이터를 읽어와
3개 서점을 나란히 비교하는 Next.js 대시보드입니다.

실행 방법은 대화에서 안내한 단계를 따라주세요. 요약하면:

1. `npm install`
2. `.env.local.example`을 복사해 `.env.local`로 만들고 SUPABASE_URL / SUPABASE_SERVICE_KEY 입력
3. `npm run dev`
4. 브라우저에서 http://localhost:3000 접속

수집 스크립트(test_save_*.py)는 이 프로젝트와 별개로, 기존 폴더에서 그대로 사용합니다.
