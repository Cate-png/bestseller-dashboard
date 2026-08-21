"""[일회성 진단 스크립트] 교보문고 베스트셀러 페이지의 실제 구조를 확인합니다.

목적 (Supabase에는 전혀 쓰지 않는 읽기 전용 진단):
1. "120개씩 보기" 같은 페이지 크기 옵션이 실제로 존재하는지, 있다면 클릭 시
   어떤 URL/네트워크 요청이 발생하는지 캡처
2. 목록 페이지의 도서 항목 DOM에 저자/출판사/ISBN13이 이미 포함돼 있는지 확인
   (있다면 상세 페이지 방문 없이 목록만으로 충분할 수 있음)

최적화 작업을 실제로 반영하기 전에, 추측이 아니라 실제 페이지를 열어서
확인하기 위한 용도입니다. 확인이 끝나면 이 파일과 관련 워크플로 스텝은
정리(삭제)할 예정입니다.
"""

import re
import sys

from playwright.sync_api import sync_playwright

LIST_URL = "https://store.kyobobook.co.kr/bestseller/total/weekly"


def main():
    requests_seen = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        )

        def on_request(req):
            if req.resource_type in ("xhr", "fetch", "document"):
                requests_seen.append((req.method, req.url))

        page.on("request", on_request)

        print(f"[1] 목록 페이지 로딩: {LIST_URL}")
        page.goto(LIST_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(1500)

        print("\n[2] 페이지 로딩 중 발생한 document/xhr/fetch 요청들:")
        for method, url in requests_seen:
            print(f"   {method} {url}")

        print("\n[3] '120개씩 보기' 등 페이지 크기 옵션 텍스트 검색")
        candidates = page.get_by_text(re.compile(r"(\d+)\s*개씩"))
        count = candidates.count()
        print(f"   '~개씩' 패턴 매칭 요소 수: {count}")
        for i in range(min(count, 10)):
            el = candidates.nth(i)
            try:
                text = el.inner_text().strip()
                tag = el.evaluate("e => e.tagName")
                outer = el.evaluate("e => e.outerHTML")[:300]
                print(f"   [{i}] tag={tag} text='{text}'")
                print(f"        outerHTML(앞 300자)={outer}")
            except Exception as e:
                print(f"   [{i}] 읽기 실패: {e}")

        # select 태그(드롭다운) 자체도 별도로 확인
        selects = page.locator("select")
        scount = selects.count()
        print(f"\n[3-1] 페이지 내 <select> 요소 수: {scount}")
        for i in range(min(scount, 10)):
            sel = selects.nth(i)
            try:
                outer = sel.evaluate("e => e.outerHTML")[:500]
                print(f"   select[{i}] outerHTML(앞 500자)={outer}")
            except Exception as e:
                print(f"   select[{i}] 읽기 실패: {e}")

        requests_seen.clear()
        if count > 0:
            print("\n[4] '~개씩' 옵션 클릭 시도")
            try:
                candidates.first.click(timeout=5000)
                page.wait_for_timeout(3000)
                print(f"   클릭 후 URL: {page.url}")
                print("   클릭 후 발생한 document/xhr/fetch 요청들:")
                for method, url in requests_seen:
                    print(f"      {method} {url}")
                # 클릭 후 목록에 실제로 몇 권이 렌더링됐는지도 확인
                img_count = page.locator(
                    "a[href*='product.kyobobook.co.kr/detail/'] img"
                ).count()
                print(f"   클릭 후 렌더링된 도서 이미지 수: {img_count}")
            except Exception as e:
                print(f"   클릭 실패/타임아웃: {e}")
        else:
            print("\n[4] 클릭할 '~개씩' 옵션을 찾지 못했습니다.")

        print("\n[5] 도서 목록 항목 1개의 DOM 구조 확인 (저자/출판사/ISBN 존재 여부)")
        img_selector = "a[href*='product.kyobobook.co.kr/detail/'] img"
        imgs = page.locator(img_selector)
        if imgs.count() > 0:
            first_img = imgs.first
            # 이미지에서 몇 단계 상위 컨테이너까지의 텍스트/HTML을 살펴봄
            container_html = first_img.evaluate(
                """
                (img) => {
                    let el = img.closest('a');
                    // a 태그 기준 조상 3단계까지 outerHTML을 반환
                    let node = el;
                    for (let i = 0; i < 3 && node.parentElement; i++) {
                        node = node.parentElement;
                    }
                    return node.outerHTML;
                }
                """
            )
            print(f"   조상 3단계 컨테이너 outerHTML 길이: {len(container_html)}")
            print(f"   앞 2000자:\n{container_html[:2000]}")

            # 13자리 숫자(ISBN13 패턴) 존재 여부
            isbn_matches = re.findall(r"\b\d{13}\b", container_html)
            print(f"\n   컨테이너 내 13자리 숫자(ISBN13 패턴) 발견: {isbn_matches[:5]}")
        else:
            print("   도서 이미지를 찾지 못했습니다.")

        browser.close()

    print("\n진단 완료.")


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"진단 스크립트 실행 중 오류: {e}")
        sys.exit(1)
