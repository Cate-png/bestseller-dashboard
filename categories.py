"""분야별(카테고리) TOP10 베스트셀러 수집에서 공통으로 사용하는 설정과 헬퍼.

기존 종합 TOP100 수집 스크립트(test_save_kyobo.py / test_save_yes24.py /
test_save_aladin.py)는 이 파일을 전혀 사용하지 않으므로, 이 파일을 고쳐도
종합 TOP100 수집에는 영향이 없습니다. 이 파일은 test_save_*_category.py
3개 스크립트가 공통으로 import해서 씁니다.

각 분야별 카테고리 식별자 출처:
- kyobo_domestic_code: store.kyobobook.co.kr/bestseller/online/weekly/domestic/{code}
  01=소설, 03=시/에세이, 05=인문, 09=건강, 13=경제/경영, 15=자기계발,
  17=정치/사회, 19=역사/문화, 21=종교, 23=예술/대중문화, 29=과학,
  32=여행, 33=컴퓨터/IT, 47=만화
  (교보문고 사이트 store.kyobobook.co.kr/bestseller/online/weekly/domestic/01
  응답에 포함된 국내도서 분류 목록 JSON에서 실제로 확인한 코드입니다.
  교보문고는 "사회과학"이라는 이름 대신 "정치/사회", "기술/IT" 대신
  "컴퓨터/IT"라는 이름을 쓰지만 같은 대분류를 가리킵니다.)
- yes24_category_id: apis.yes24.com API의 categoryId 파라미터.
  기존 코드가 종합을 categoryId="001"로 쓰고 있고, 예스24 웹사이트의
  categoryNumber=001 역시 "국내도서 종합"을 가리키는 것으로 확인되어,
  이 비공개 API가 웹사이트와 동일한 categoryNumber 체계를 쓴다고 보고
  대응시킨 값입니다. *예스24 공식 API 문서로 직접 검증한 값이 아니라
  정황 증거로 추정한 값이므로, 최초 실행 시 결과(도서 제목)가 해당
  분야와 다르게 나오면 이 값을 조정해야 합니다.* 신규 8개 분야는
  www.yes24.com/24/Category/Display/001001019 페이지의 국내도서 분류
  메뉴에서 categoryNumber와 분류명을 대조해 확인했습니다(사회과학="사회
  정치", 과학="자연과학", 기술/IT="IT 모바일", 건강="건강 취미").
- aladin_cid: aladin.co.kr wbrowse.aspx / wbest.aspx의 CID 파라미터.
  알라딘 사이트 wbest.aspx 페이지의 "국내도서" 분류 메뉴(head_book_layer)
  에서 실제로 확인된 CID입니다. 기술/IT는 알라딘에 별도 "기술/공학"
  대분류가 없어 "컴퓨터/모바일"(CID=351)로 대응시켰습니다. 건강은
  CID=55890(국내도서 "건강/취미")을 쓰고, CID=56388(전자책 "건강/취미")과
  혼동하지 않도록 주의해야 합니다.
"""

TOP_N = 10

CATEGORIES = [
    {
        "category": "인문",
        "kyobo_domestic_code": "05",
        "yes24_category_id": "001001019",
        "aladin_cid": "656",
    },
    {
        "category": "경제경영",
        "kyobo_domestic_code": "13",
        "yes24_category_id": "001001025",
        "aladin_cid": "170",
    },
    {
        "category": "자기계발",
        "kyobo_domestic_code": "15",
        "yes24_category_id": "001001026",
        "aladin_cid": "336",
    },
    {
        "category": "소설",
        "kyobo_domestic_code": "01",
        "yes24_category_id": "001001046",
        "aladin_cid": "1",
    },
    {
        "category": "에세이/시",
        "kyobo_domestic_code": "03",
        "yes24_category_id": "001001047",
        "aladin_cid": "55889",
    },
    {
        "category": "사회과학",
        "kyobo_domestic_code": "17",
        "yes24_category_id": "001001022",
        "aladin_cid": "798",
    },
    {
        "category": "역사",
        "kyobo_domestic_code": "19",
        "yes24_category_id": "001001010",
        "aladin_cid": "74",
    },
    {
        "category": "예술",
        "kyobo_domestic_code": "23",
        "yes24_category_id": "001001007",
        "aladin_cid": "517",
    },
    {
        "category": "과학",
        "kyobo_domestic_code": "29",
        "yes24_category_id": "001001002",
        "aladin_cid": "987",
    },
    {
        "category": "만화",
        "kyobo_domestic_code": "47",
        "yes24_category_id": "001001008",
        "aladin_cid": "2551",
    },
    {
        "category": "여행",
        "kyobo_domestic_code": "32",
        "yes24_category_id": "001001009",
        "aladin_cid": "1196",
    },
    {
        "category": "건강",
        "kyobo_domestic_code": "09",
        "yes24_category_id": "001001011",
        "aladin_cid": "55890",
    },
    {
        "category": "기술/IT",
        "kyobo_domestic_code": "33",
        "yes24_category_id": "001001003",
        "aladin_cid": "351",
    },
    {
        "category": "종교",
        "kyobo_domestic_code": "21",
        "yes24_category_id": "001001021",
        "aladin_cid": "1237",
    },
]


def get_previous_category_ranks(client, bookstore, category):
    """해당 서점 + 분야의 가장 최근 수집 스냅샷에서 isbn13 -> rank 매핑을 가져옵니다.

    종합 TOP100 스크립트의 get_previous_ranks()와 달리 collection_runs이 아니라
    rankings 테이블을 직접 조회합니다. 분야별 수집은 종합 수집과 별도의
    run(collection_runs 행)으로 기록되므로, "해당 서점의 가장 최근 run"이
    아니라 "해당 서점 + 해당 분야의 가장 최근 스냅샷"을 정확히 찾아야
    등락(rank_change) 계산이 엉키지 않습니다.
    """
    latest = (
        client.table("rankings")
        .select("collected_at")
        .eq("bookstore", bookstore)
        .eq("category", category)
        .order("collected_at", desc=True)
        .limit(1)
        .execute()
    )
    if not latest.data:
        return {}

    latest_collected_at = latest.data[0]["collected_at"]
    prev_rankings = (
        client.table("rankings")
        .select("isbn13, rank")
        .eq("bookstore", bookstore)
        .eq("category", category)
        .eq("collected_at", latest_collected_at)
        .execute()
    )
    return {row["isbn13"]: row["rank"] for row in prev_rankings.data if row["isbn13"]}
