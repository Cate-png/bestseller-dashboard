"""알라딘 "지금 베스트"(NowBest) 페이지의 페이지네이션 범위를 실측 확인하는
읽기 전용 진단 스크립트. Supabase에는 아무것도 쓰지 않습니다.

배경: test_save_aladin_realtime.py가 page=1(BestType=NowBest, 파라미터 추가
없음)만 요청하고 TARGET_COUNT=50으로 잘라서, 실제로는 50건 미만(비도서/
오디오북 필터링 후 46건)만 저장되고 있었습니다. 종합 주간 수집기
(test_save_aladin.py)는 이미 동일한 wbest.aspx에 대해 page=1과
page=2&cnt=1000&SortOrder=1 두 번 요청해서 TOP100을 채우고 있으므로, NowBest도
같은 파라미터 패턴이 통하는지, 몇 페이지까지 실제 데이터가 있는지를 이
스크립트로 확인합니다.

실행 결과(2026-08-22, GitHub Actions):
- page=1(파라미터 없음): 50건
- page=2&cnt=1000&SortOrder=1: 49건 (합계 99건)
- page=3&cnt=1000&SortOrder=1: 0건
- page=4&cnt=1000&SortOrder=1: 0건
즉 알라딘 "지금 베스트"는 실제로 최대 99건까지만 존재하고(100건이 아님),
3페이지 이상은 빈 응답입니다. 사용자가 언급한 "1~25/26~50/51~75/76~100"
4구간 표기는 알라딘 공식 베스트셀러(주간 등) 화면의 사용자용 표기이고,
이 내부 페이지네이션 파라미터(page=N&cnt=1000&SortOrder=1) 자체는 실측상
페이지당 25건이 아니라 페이지당 최대 50건 단위로 응답합니다.
"""

import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("오류: playwright 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

try:
    from bs4 import BeautifulSoup
except ImportError:
    print("오류: beautifulsoup4 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

from test_save_aladin import HEADERS, CONTEXT_KWARGS, goto_with_retry

LIST_URL = "https://www.aladin.co.kr/shop/common/wbest.aspx"


def fetch_nowbest_page(page, page_num):
    params = {"BranchType": "1", "BestType": "NowBest"}
    if page_num > 1:
        params["page"] = str(page_num)
        params["cnt"] = "1000"
        params["SortOrder"] = "1"
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{LIST_URL}?{query}"
    html = goto_with_retry(page, url)
    soup = BeautifulSoup(html, "html.parser")
    boxes = soup.select("div.ss_book_box")
    first = boxes[0].select_one("a.bo3").get_text(strip=True) if boxes else None
    last = boxes[-1].select_one("a.bo3").get_text(strip=True) if boxes else None
    return url, len(boxes), first, last


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS["User-Agent"], **CONTEXT_KWARGS)

        total = 0
        for page_num in range(1, 6):
            url, count, first, last = fetch_nowbest_page(page, page_num)
            total += count
            print(f"page={page_num}: {count}건 (누적 {total}건) url={url}")
            print(f"   첫 항목='{first}' / 마지막 항목='{last}'")
            if count == 0:
                print(f"   -> page={page_num}부터 빈 응답. 여기서 중단합니다.")
                break

        browser.close()


if __name__ == "__main__":
    main()
