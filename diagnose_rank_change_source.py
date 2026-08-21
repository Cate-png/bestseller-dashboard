"""교보문고/알라딘 주간 베스트셀러 페이지 자체에 "이전 순위" 또는 "등락"
정보가 원래부터 존재하는지 확인하기 위한 읽기 전용 진단 스크립트.

배경: 현재 우리 rank_change는 우리가 직전에 저장해둔 스냅샷과 이번 수집을
직접 비교(prev_ranks[isbn13] - book["rank"])해서 계산합니다. 그런데 사용자가
다른 베스트셀러 대시보드(북위키)에서는 교보문고 주간 베스트셀러에 ▲/▼ 등락이
정상적으로 표시되는 것을 확인했다고 함 -> 교보/알라딘 사이트 자체가 원래
"이전 순위/등락" 데이터를 갖고 있는데 우리가 그걸 안 가져오고 있는 것인지,
아니면 사이트엔 그런 데이터가 없고 북위키도 자기들만의 스냅샷 비교로
계산하는 것인지 실제로 확인해야 함.

이 스크립트는 Supabase에 아무것도 저장하지 않습니다. 확인하는 것:
1. 교보 주간 베스트(store.kyobobook.co.kr/bestseller/total/weekly) HTML +
   네트워크 응답(XHR/fetch로 불러오는 JSON)에 "이전 순위"/"등락"/"rank
   변동" 관련 필드가 있는지
2. 알라딘 주간 베스트(wbest.aspx, 기본 BestType=Bestseller) HTML +
   네트워크 응답에 동일한 정보가 있는지
"""

import json
import re
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("오류: playwright 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

from bs4 import BeautifulSoup

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

RANK_KEYWORDS = [
    "beforerank", "prevrank", "previousrank", "rankgap", "rankdiff",
    "rankchange", "rank_change", "updown", "up_down", "이전순위", "이전 순위",
    "등락", "변동순위", "순위변동", "rankmove", "changerank",
]


def section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def scan_json_for_rank_keywords(obj, path, hits, max_hits=20):
    if len(hits) >= max_hits:
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            key_low = str(k).lower()
            if any(kw in key_low for kw in RANK_KEYWORDS):
                hits.append((f"{path}.{k}", v))
            scan_json_for_rank_keywords(v, f"{path}.{k}", hits, max_hits)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:5]):  # 리스트는 앞 5개만 샘플링
            scan_json_for_rank_keywords(v, f"{path}[{i}]", hits, max_hits)


def diagnose_kyobo_weekly(page):
    section("[교보문고] store.kyobobook.co.kr/bestseller/total/weekly - rank_change 원천 조사")

    captured = []  # (url, json_body)

    def on_response(response):
        try:
            url = response.url
            if "kyobobook.co.kr" not in url:
                return
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            body = response.json()
            captured.append((url, body))
        except Exception:
            pass

    page.on("response", on_response)
    page.goto(
        "https://store.kyobobook.co.kr/bestseller/total/weekly", timeout=30000
    )
    page.wait_for_load_state("networkidle", timeout=30000)
    page.wait_for_timeout(2000)
    html = page.content()
    page.remove_listener("response", on_response)

    print(f"캡처된 JSON 응답 개수: {len(captured)}")
    for url, body in captured:
        hits = []
        scan_json_for_rank_keywords(body, "root", hits)
        if hits:
            print(f"\n  [일치] {url}")
            for path, val in hits:
                val_str = json.dumps(val, ensure_ascii=False)[:200]
                print(f"    {path} = {val_str}")
        else:
            print(f"  [키워드 없음] {url}")

    # 키워드 매칭에만 의존하면 우리가 예상 못한 필드명(예: gap, diff, trend,
    # move, status 등 'rank'라는 단어가 안 들어간 이름)을 놓칠 수 있음.
    # 실제로 베스트셀러 목록을 채워주는 API로 보이는 응답(best-seller가
    # url에 포함된 것)은 첫 2개 항목의 JSON을 전체 그대로 출력해서 눈으로
    # 직접 모든 필드를 확인한다.
    for url, body in captured:
        if "best-seller" not in url:
            continue
        print(f"\n--- 베스트셀러 목록 API 원본 JSON 전체 확인: {url} ---")
        items = None
        if isinstance(body, dict):
            for key in ("data", "list", "items", "result", "content"):
                if key in body:
                    candidate = body[key]
                    if isinstance(candidate, list):
                        items = candidate
                        break
                    if isinstance(candidate, dict):
                        for inner_key in ("list", "items", "content"):
                            if inner_key in candidate and isinstance(candidate[inner_key], list):
                                items = candidate[inner_key]
                                break
                    if items:
                        break
        if items is None and isinstance(body, list):
            items = body
        if items is None:
            print("  (도서 목록으로 보이는 배열을 자동으로 못 찾음 - 최상위 구조를 그대로 출력)")
            print(f"  최상위 키: {list(body.keys()) if isinstance(body, dict) else type(body)}")
            print(json.dumps(body, ensure_ascii=False, indent=2)[:3000])
        else:
            print(f"  도서 목록 항목 수: {len(items)}")
            for item in items[:2]:
                print(json.dumps(item, ensure_ascii=False, indent=2))

    print("\n--- HTML 원문에서 등락/이전순위 관련 키워드 직접 검색 ---")
    html_low = html.lower()
    for kw in RANK_KEYWORDS:
        if kw in html_low:
            idx = html_low.find(kw)
            print(f"  '{kw}' 발견! 주변 200자: ...{html[max(0, idx-50):idx+150]}...")
    if not any(kw in html_low for kw in RANK_KEYWORDS):
        print("  HTML 원문에서 위 키워드들을 찾지 못함")

    # 화살표(▲▼) 유니코드 문자나 arrow 이미지가 목록 안에 있는지도 확인
    print("\n--- 화살표(▲▼) 문자 및 'arrow' 이미지 직접 검색 ---")
    for arrow in ["▲", "▼", "↑", "↓"]:
        count = html.count(arrow)
        if count:
            print(f"  '{arrow}' 문자가 HTML에 {count}번 등장")
    soup = BeautifulSoup(html, "html.parser")
    arrow_imgs = [
        img for img in soup.find_all("img")
        if "arrow" in (img.get("src", "") + img.get("alt", "")).lower()
    ]
    print(f"  src/alt에 'arrow' 포함된 img 태그: {len(arrow_imgs)}개")
    for img in arrow_imgs[:5]:
        print(f"    {img}")

    # 첫 번째 도서 항목 주변의 원본 HTML을 통째로 살펴봐서, 순위 숫자 옆에
    # 등락을 나타낼 만한 다른 요소가 있는지 눈으로 확인
    first_link = soup.select_one("a[href*='product.kyobobook.co.kr/detail/']")
    if first_link:
        # 카드 전체로 보이는 상위 컨테이너를 몇 단계 올라가서 출력
        container = first_link
        for _ in range(4):
            if container.parent:
                container = container.parent
        snippet = str(container)
        if len(snippet) > 2500:
            snippet = snippet[:2500] + " ...(생략)"
        print("\n--- 첫 번째 도서 항목 주변 컨테이너 HTML (순위/등락 표기 확인용) ---")
        print(snippet)


def diagnose_aladin_weekly(page):
    section("[알라딘] wbest.aspx (기본 주간 베스트) - rank_change 원천 조사")

    captured = []

    def on_response(response):
        try:
            url = response.url
            if "aladin.co.kr" not in url:
                return
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            body = response.json()
            captured.append((url, body))
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(
            "https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&BestType=Bestseller",
            timeout=30000,
        )
        page.wait_for_timeout(3000)
    except Exception as e:
        print(f"페이지 로딩 실패: {e}")
        page.remove_listener("response", on_response)
        return
    html = page.content()
    page.remove_listener("response", on_response)

    print(f"캡처된 JSON 응답 개수: {len(captured)}")
    for url, body in captured:
        hits = []
        scan_json_for_rank_keywords(body, "root", hits)
        if hits:
            print(f"\n  [일치] {url}")
            for path, val in hits:
                val_str = json.dumps(val, ensure_ascii=False)[:200]
                print(f"    {path} = {val_str}")
        else:
            print(f"  [키워드 없음] {url}")

    print("\n--- HTML 원문에서 등락/이전순위 관련 키워드 직접 검색 ---")
    html_low = html.lower()
    for kw in RANK_KEYWORDS:
        if kw in html_low:
            idx = html_low.find(kw)
            print(f"  '{kw}' 발견! 주변 200자: ...{html[max(0, idx-50):idx+150]}...")
    if not any(kw in html_low for kw in RANK_KEYWORDS):
        print("  HTML 원문에서 위 키워드들을 찾지 못함")

    print("\n--- 화살표(▲▼) 문자 및 'arrow' 이미지 직접 검색 ---")
    for arrow in ["▲", "▼", "↑", "↓"]:
        count = html.count(arrow)
        if count:
            print(f"  '{arrow}' 문자가 HTML에 {count}번 등장")
    soup = BeautifulSoup(html, "html.parser")
    arrow_imgs = [
        img for img in soup.find_all("img")
        if "arrow" in (img.get("src", "") + img.get("alt", "")).lower()
    ]
    print(f"  src/alt에 'arrow' 포함된 img 태그: {len(arrow_imgs)}개")
    for img in arrow_imgs[:5]:
        print(f"    {img}")

    box = soup.select_one("div.ss_book_box")
    if box:
        snippet = str(box)
        if len(snippet) > 2500:
            snippet = snippet[:2500] + " ...(생략)"
        print("\n--- 첫 번째 div.ss_book_box 전체 HTML (순위/등락 표기 확인용) ---")
        print(snippet)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul")

        for name, fn in (
            ("교보문고", diagnose_kyobo_weekly),
            ("알라딘", diagnose_aladin_weekly),
        ):
            try:
                fn(page)
            except Exception as e:
                print(f"\n[{name}] 진단 중 예외 발생: {e}")

        browser.close()

    print("\n" + "=" * 80)
    print("진단 완료. 이 스크립트는 Supabase에 아무것도 저장하지 않습니다.")
    print("=" * 80)


if __name__ == "__main__":
    main()
