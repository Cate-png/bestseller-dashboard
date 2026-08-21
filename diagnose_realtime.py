"""실시간 베스트셀러 3사 페이지의 실제 구조를 확인하기 위한 진단 전용 스크립트.

Supabase에 아무것도 저장하지 않습니다 (읽기 전용 정찰). 로컬 샌드박스에서는
교보/예스24/알라딘 사이트에 접속 자체가 막혀 있어(egress 차단) 직접 확인할
방법이 없기 때문에, GitHub Actions에서 1회 실행해서 로그로 아래를 확인하는
용도입니다:

1. 교보문고 실시간(store.kyobobook.co.kr/bestseller/realtime)이 실제로
   도서/전자책/기프트/교보only 상품을 섞어서 보여주는지, 그리고 기존
   종합/분야별 스크래퍼가 쓰는 selector(a[href*='product.kyobobook.co.kr/detail/']
   img)가 이 페이지에서도 도서만 걸러내는지, 국내도서만 보는 필터 탭이
   있는지.
2. 예스24 실시간(yes24.com/Product/Category/RealTimeBestSeller?categoryNumber=001)
   페이지가 어떤 마크업 구조인지 (기존에 쓰던 apis.yes24.com API와는 별개
   페이지라 처음 보는 구조).
3. 알라딘 "지금 베스트"(wbest.aspx?BranchType=1&BestType=NowBest)가 기존
   주간 베스트와 동일한 div.ss_book_box / a.bo3 구조를 그대로 쓰는지.

이 스크립트는 실제 수집기(test_save_*_realtime.py)를 만들기 전 확인 용도라
Supabase 테이블(realtime_rankings 포함) 존재 여부와 무관하게 실행됩니다.
"""

import re
import sys
from collections import Counter

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


def section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def diagnose_kyobo(page):
    section("[교보문고] store.kyobobook.co.kr/bestseller/realtime")
    url = "https://store.kyobobook.co.kr/bestseller/realtime"
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"페이지 로딩 실패: {e}")
        return

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    print(f"페이지 타이틀: {soup.title.get_text(strip=True) if soup.title else '(없음)'}")

    # 1) 탭/필터로 보이는 링크(전체/국내도서/eBook/기프트 등) 텍스트+href 수집
    print("\n--- 탭/필터로 보이는 링크 후보 (텍스트에 '전체/도서/eBook/전자책/기프트/교보only' 포함) ---")
    tab_keywords = ["전체", "국내도서", "도서", "eBook", "전자책", "기프트", "교보only", "교보Only"]
    found_tabs = []
    for a in soup.find_all("a"):
        text = a.get_text(strip=True)
        if text and any(k in text for k in tab_keywords) and len(text) < 20:
            href = a.get("href", "")
            found_tabs.append((text, href))
    seen = set()
    for text, href in found_tabs:
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)
        print(f"  '{text}' -> {href}")
    if not found_tabs:
        print("  (탭으로 보이는 링크를 찾지 못함)")

    # 2) 페이지 내 모든 링크의 도메인/경로 패턴 집계 (어떤 상품 유형 링크가 섞여있는지)
    print("\n--- 페이지 내 링크 href 패턴 집계 (상위 15개 패턴) ---")
    pattern_counter = Counter()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        m = re.match(r"(https?://[^/]+)?(/[^/?]+)?", href)
        domain = m.group(1) or "(상대경로)"
        path_prefix = m.group(2) or "/"
        pattern_counter[f"{domain}{path_prefix}"] += 1
    for pattern, count in pattern_counter.most_common(15):
        print(f"  {count:>4}건  {pattern}")

    # 3) 기존 종합/분야별 스크래퍼가 쓰는 selector로 실제 몇 건이 잡히는지
    print("\n--- 기존 selector(a[href*='product.kyobobook.co.kr/detail/'] img) 매칭 결과 ---")
    imgs = page.locator("a[href*='product.kyobobook.co.kr/detail/'] img")
    count = imgs.count()
    print(f"매칭된 항목 수: {count}")
    for i in range(min(count, 15)):
        img = imgs.nth(i)
        title = img.get_attribute("alt")
        href = img.evaluate(
            "(img) => img.closest('a') ? img.closest('a').getAttribute('href') : null"
        )
        print(f"  [{i + 1}] {title}  ({href})")

    # 4) 페이지 전체에서 alt 속성이 있는 모든 img(선택자 제한 없이) 개수와,
    #    위 selector 매칭 개수를 비교 -> 차이가 크면 도서 외 상품이 섞여
    #    있는데 selector가 우연히도 도서만 골라내고 있다는 뜻일 수 있음
    all_imgs_with_alt = page.locator("img[alt]")
    print(
        f"\n페이지 전체 img[alt] 개수: {all_imgs_with_alt.count()}  "
        f"(vs 위 selector 매칭 {count}건) -> 차이가 크면 이 페이지에 도서 외"
        f" 콘텐츠(배너 등)도 많다는 뜻이므로 정확한 도서 판별은 href 도메인"
        f" 기준으로 해야 함"
    )


def diagnose_yes24(page):
    section("[예스24] yes24.com/Product/Category/RealTimeBestSeller?categoryNumber=001")
    url = "https://www.yes24.com/Product/Category/RealTimeBestSeller?categoryNumber=001"
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"페이지 로딩 실패: {e}")
        return

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")
    print(f"페이지 타이틀: {soup.title.get_text(strip=True) if soup.title else '(없음)'}")

    # 상품 상세로 보이는 링크(Goods/숫자 패턴) 수집
    print("\n--- 'Goods/' 패턴을 포함하는 링크 (상품 상세로 추정) 상위 20개 ---")
    goods_links = []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "Goods/" in href or "goods/" in href:
            text = a.get_text(strip=True)
            if text:
                goods_links.append((text, href))
    seen = set()
    shown = 0
    for text, href in goods_links:
        key = (text, href)
        if key in seen:
            continue
        seen.add(key)
        print(f"  '{text}'  ({href})")
        shown += 1
        if shown >= 20:
            break
    if not goods_links:
        print("  (Goods/ 패턴 링크를 찾지 못함 - JS 렌더링 이후 구조 재확인 필요)")

    # 흔히 쓰이는 랭킹/리스트 컨테이너 class 이름 후보들을 넓게 스캔
    print("\n--- class 이름에 'goods'/'item'/'rank'/'best' 포함하는 요소 개수 (상위 15개) ---")
    class_counter = Counter()
    for tag in soup.find_all(class_=True):
        for cls in tag.get("class", []):
            low = cls.lower()
            if any(k in low for k in ["goods", "item", "rank", "best", "list"]):
                class_counter[f"{tag.name}.{cls}"] += 1
    for cls, count in class_counter.most_common(15):
        print(f"  {count:>4}건  {cls}")


def diagnose_aladin(page):
    section("[알라딘] wbest.aspx?BranchType=1&BestType=NowBest (지금 베스트)")
    url = "https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&BestType=NowBest"
    try:
        page.goto(url, timeout=30000)
        page.wait_for_timeout(2000)
        html = page.content()
    except Exception as e:
        print(f"페이지 로딩 실패: {e}")
        return

    soup = BeautifulSoup(html, "html.parser")
    print(f"페이지 타이틀: {soup.title.get_text(strip=True) if soup.title else '(없음)'}")

    boxes = soup.select("div.ss_book_box")
    print(f"\n기존 selector(div.ss_book_box) 매칭 개수: {len(boxes)}")
    for i, box in enumerate(boxes[:15]):
        title_tag = box.select_one("a.bo3")
        title = title_tag.get_text(strip=True) if title_tag else "(제목 파싱 실패)"
        print(f"  [{i + 1}] {title}")

    if not boxes:
        print(
            "경고: div.ss_book_box가 하나도 안 잡힘 -> NowBest 페이지가 주간 베스트와"
            " 다른 마크업을 쓰거나, 리다이렉트/에러 페이지일 가능성. 페이지 제목과"
            " 아래 원본 HTML 일부를 참고."
        )
        print("\n--- HTML 앞부분 2000자 ---")
        print(html[:2000])


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul")

        for name, fn in (
            ("교보문고", diagnose_kyobo),
            ("예스24", diagnose_yes24),
            ("알라딘", diagnose_aladin),
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
