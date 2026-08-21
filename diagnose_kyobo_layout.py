"""[일회성 진단 스크립트 v2] 교보문고 베스트셀러 내부 API 및 목록 DOM 재확인.

1차 진단에서 목록 페이지가 실제로는
https://store.kyobobook.co.kr/api/gw/best/best-seller/total?page=1&per=20&period=002&bsslBksClstCode=A
라는 내부 JSON API를 호출해서 데이터를 그리는 것을 확인했습니다. 이번에는:
1. 이 API를 per=20/100/120으로 직접 호출해서 실제로 더 많은 항목을 한 번에
   받을 수 있는지, 응답 JSON에 author/publisher/isbn13이 이미 들어있는지 확인
2. 목록 페이지 도서 항목 컨테이너 전체 HTML에서 pbcmCode(출판사 링크) /
   eg:brandName(저자) 패턴이 존재하는지 확인 (상세페이지 스킵 가능 여부 판단용)
"""

import json
import re
import sys

from playwright.sync_api import sync_playwright

LIST_URL = "https://store.kyobobook.co.kr/bestseller/total/weekly"
API_URL = "https://store.kyobobook.co.kr/api/gw/best/best-seller/total"


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            )
        )

        print("[0] 먼저 목록 페이지를 한 번 열어서 정상 세션/쿠키를 확보")
        page.goto(LIST_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)

        for per in (20, 100, 120, 200):
            print(f"\n[1] 내부 API 직접 호출: per={per}")
            try:
                resp = page.request.get(
                    API_URL,
                    params={
                        "page": "1",
                        "per": str(per),
                        "period": "002",
                        "bsslBksClstCode": "A",
                    },
                )
                print(f"   status={resp.status}")
                if resp.ok:
                    data = resp.json()
                    # 실제 아이템 배열 위치를 찾기 위해 최상위 구조를 먼저 출력
                    print(f"   최상위 키: {list(data.keys()) if isinstance(data, dict) else type(data)}")
                    text = json.dumps(data, ensure_ascii=False)
                    print(f"   응답 전체 길이: {len(text)}자")
                    # 흔히 쓰이는 위치 후보들을 시도
                    items = None
                    if isinstance(data, dict):
                        d = data.get("data", data)
                        if isinstance(d, dict):
                            for key in ("bestSeller", "list", "items", "productList", "result"):
                                if key in d:
                                    items = d[key]
                                    print(f"   아이템 배열 후보 키: data.{key}")
                                    break
                        elif isinstance(d, list):
                            items = d
                    if items is not None and isinstance(items, list):
                        print(f"   아이템 개수: {len(items)}")
                        if items:
                            print(f"   첫 아이템 키: {list(items[0].keys())}")
                            print(f"   첫 아이템 샘플: {json.dumps(items[0], ensure_ascii=False)[:800]}")
                    else:
                        print(f"   아이템 배열을 자동으로 못 찾음. 응답 앞 1500자: {text[:1500]}")
                else:
                    print(f"   응답 실패, 본문 앞 500자: {resp.text()[:500]}")
            except Exception as e:
                print(f"   요청 실패: {e}")

        print("\n[2] 목록 페이지 도서 항목 컨테이너에서 pbcmCode / eg:brandName 패턴 검색")
        img_selector = "a[href*='product.kyobobook.co.kr/detail/'] img"
        imgs = page.locator(img_selector)
        if imgs.count() > 0:
            first_img = imgs.first
            container_html = first_img.evaluate(
                """
                (img) => {
                    let el = img.closest('a');
                    let node = el;
                    for (let i = 0; i < 4 && node.parentElement; i++) {
                        node = node.parentElement;
                    }
                    return node.outerHTML;
                }
                """
            )
            print(f"   컨테이너 HTML 전체 길이: {len(container_html)}")
            has_pbcm = "pbcmCode=" in container_html
            has_brand = "eg:brandName" in container_html
            print(f"   'pbcmCode=' (출판사 링크 패턴) 포함 여부: {has_pbcm}")
            print(f"   'eg:brandName' (저자 메타 패턴) 포함 여부: {has_brand}")

            # 실제 출판사/저자로 추정되는 텍스트 조각을 대략적으로 훑어보기 위해
            # <a> 태그 전체를 나열
            links = first_img.evaluate(
                """
                (img) => {
                    let el = img.closest('a');
                    let node = el;
                    for (let i = 0; i < 4 && node.parentElement; i++) {
                        node = node.parentElement;
                    }
                    return Array.from(node.querySelectorAll('a')).map(a => ({
                        text: a.innerText.trim().slice(0, 40),
                        href: a.getAttribute('href')
                    }));
                }
                """
            )
            print(f"   컨테이너 내부 <a> 태그 수: {len(links)}")
            for l in links[:30]:
                print(f"      text='{l['text']}' href='{l['href']}'")
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
