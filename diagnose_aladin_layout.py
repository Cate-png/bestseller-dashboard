"""[일회성 진단 스크립트] 알라딘 베스트셀러 페이지의 실제 구조를 확인합니다.

목적 (Supabase에는 전혀 쓰지 않는 읽기 전용 진단):
1. cnt 파라미터를 키우면 한 번의 요청으로 50권 이상을 받아올 수 있는지
   (현재 코드는 page=1/page=2 두 번 요청해서 50+50=100권을 모음)
2. 목록 페이지의 도서 항목(div.ss_book_box) DOM에 저자/출판사/ISBN13이 이미
   포함돼 있는지 확인 (있다면 상세 페이지 방문 없이 목록만으로 충분할 수 있음)

test_save_aladin.py와 동일하게 Playwright(Chromium)로 접근합니다 (requests는
GitHub Actions에서 403으로 차단된 전례가 있음).
"""

import re
import sys

from playwright.sync_api import sync_playwright

LIST_URL = "https://www.aladin.co.kr/shop/common/wbest.aspx"
HEADERS_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


def fetch(page, params: dict) -> str:
    query = "&".join(f"{k}={v}" for k, v in params.items())
    url = f"{LIST_URL}?{query}"
    print(f"   요청: {url}")
    page.goto(url, timeout=30000)
    page.wait_for_timeout(1000)
    return page.content(), page.url


def count_and_sample(html: str, label: str):
    boxes_count = html.count('class="ss_book_box"') + html.count("class='ss_book_box'")
    print(f"   [{label}] 'ss_book_box' 등장 횟수(대략적인 카운트): {boxes_count}")
    return boxes_count


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=HEADERS_UA)

        print("[1] 기본 목록 페이지 (page 파라미터 없음, 기존 코드의 1페이지 요청과 동일)")
        html1, url1 = fetch(
            page, {"BestType": "Bestseller", "BranchType": "1", "CID": "0"}
        )
        count_and_sample(html1, "기본(1페이지)")

        print("\n[2] cnt=1000 & page=1 을 함께 줬을 때 (한 번에 더 많이 받아올 수 있는지 테스트)")
        html2, url2 = fetch(
            page,
            {
                "BestType": "Bestseller",
                "BranchType": "1",
                "CID": "0",
                "page": "1",
                "cnt": "1000",
                "SortOrder": "1",
            },
        )
        count_and_sample(html2, "cnt=1000&page=1")

        print("\n[3] cnt=1000 만 주고 page는 생략했을 때")
        html3, url3 = fetch(
            page,
            {
                "BestType": "Bestseller",
                "BranchType": "1",
                "CID": "0",
                "cnt": "1000",
                "SortOrder": "1",
            },
        )
        count_and_sample(html3, "cnt=1000, page 없음")

        print("\n[4] 기존 코드가 실제로 쓰는 2페이지 요청 (page=2&cnt=1000&SortOrder=1)")
        html4, url4 = fetch(
            page,
            {
                "BestType": "Bestseller",
                "BranchType": "1",
                "CID": "0",
                "page": "2",
                "cnt": "1000",
                "SortOrder": "1",
            },
        )
        count_and_sample(html4, "기존 코드의 2페이지 요청")

        print("\n[5] 목록 항목(div.ss_book_box) 1개의 전체 HTML 구조 확인")
        box = page.locator("div.ss_book_box").first
        if box.count == 0 or not page.locator("div.ss_book_box").count():
            print("   ss_book_box를 찾지 못했습니다 (마지막으로 로드된 페이지 기준).")
        else:
            outer = box.evaluate("e => e.outerHTML")
            print(f"   outerHTML 길이: {len(outer)}")
            print(f"   전체 내용:\n{outer}")

            isbn_matches = re.findall(r"\b\d{13}\b", outer)
            print(f"\n   13자리 숫자(ISBN13 패턴) 발견: {isbn_matches[:5]}")

            # 링크 텍스트/href 목록도 별도로 출력 (저자/출판사 링크가 있는지)
            links = box.locator("a")
            lcount = links.count()
            print(f"\n   내부 <a> 태그 수: {lcount}")
            for i in range(min(lcount, 15)):
                a = links.nth(i)
                try:
                    href = a.get_attribute("href") or ""
                    text = a.inner_text().strip()
                    print(f"      [{i}] text='{text}' href='{href[:120]}'")
                except Exception as e:
                    print(f"      [{i}] 읽기 실패: {e}")

        browser.close()

    print("\n진단 완료.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"진단 스크립트 실행 중 오류: {e}")
        sys.exit(1)
