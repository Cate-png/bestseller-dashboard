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

# 알라딘은 일시적인 403(CloudFront 차단)이 흔해서, 기존 검증된 재시도 로직
# (test_save_aladin.py의 goto_with_retry)을 그대로 재사용한다. 이 스크립트는
# 읽기 전용 진단이라 test_save_aladin.py 자체는 전혀 건드리지 않고 import만
# 한다.
from test_save_aladin import goto_with_retry, parse_detail, CONTEXT_KWARGS

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

    # 1차 진단에서 'eBook19,800원' 같은 링크가 'Goods/' 링크 목록에 섞여
    # 나온 것을 확인했음 -> 실시간 베스트에 eBook 개별 상품이 별도 순위
    # item으로 섞여 들어온다는 뜻. div.itemUnit(순위 아이템 컨테이너로
    # 추정) 단위로 실제 원본 HTML을 몇 개 통째로 찍어서, eBook과 종이책을
    # 구분할 수 있는 마커(클래스명/뱃지 텍스트 등)를 직접 확인한다.
    print(
        "\n--- div.itemUnit 원본 HTML 앞부분 (종이책/eBook 구분 마커 확인용, 최대 6개) ---"
    )
    units = soup.select("div.itemUnit")
    print(f"div.itemUnit 개수: {len(units)}")
    for i, unit in enumerate(units[:6]):
        snippet = str(unit)
        if len(snippet) > 1200:
            snippet = snippet[:1200] + " ...(생략)"
        print(f"\n[itemUnit {i + 1}]\n{snippet}")

    # 앞의 6개는 우연히 전부 종이책(span.gd_res == '[도서]')이었음. 'Goods/'
    # 링크 목록에서 미리 확인한 실제 eBook 상품 goods ID들을 콕 집어서, 그
    # itemUnit의 span.gd_res 값이 종이책과 어떻게 다른지 직접 확인한다.
    known_ebook_goods_ids = ["146281444", "195131395", "177150859"]
    print("\n--- 알려진 eBook 상품(goods ID)의 itemUnit에서 span.gd_res 값 확인 ---")
    for goods_id in known_ebook_goods_ids:
        unit = None
        for u in units:
            link = u.select_one(f"a[href*='/product/goods/{goods_id}']")
            if link:
                unit = u
                break
        if not unit:
            print(f"  goods/{goods_id}: 해당 itemUnit을 찾지 못함")
            continue
        gd_res = unit.select_one("span.gd_res")
        gd_name = unit.select_one("a.gd_name")
        print(
            f"  goods/{goods_id}: gd_res={gd_res.get_text(strip=True) if gd_res else '(없음)'}"
            f" / gd_name={gd_name.get_text(strip=True) if gd_name else '(없음)'}"
        )

    # itemUnit(리스트) 안에 저자/출판사/ISBN이 직접 보이는지 확인하기 위해
    # 첫 번째 itemUnit 전체(생략 없이)를 출력. 여기 없으면 상품 상세페이지를
    # 따로 방문해야 한다는 뜻이므로, 상세페이지도 1건 방문해서 author/
    # publisher/isbn13이 어떤 selector로 잡히는지 확인한다.
    if units:
        print("\n--- 첫 번째 itemUnit 전체 HTML (저자/출판사/ISBN 표기 확인용) ---")
        print(str(units[0]))

        first_link = units[0].select_one("a.gd_name") or units[0].select_one("a.lnk_img")
        detail_href = first_link.get("href", "") if first_link else ""
        if detail_href.startswith("/"):
            detail_href = "https://www.yes24.com" + detail_href
        if detail_href:
            print(f"\n--- 상품 상세페이지 확인: {detail_href} ---")
            try:
                page.goto(detail_href, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
                page.wait_for_timeout(1500)
                detail_html = page.content()
                detail_soup = BeautifulSoup(detail_html, "html.parser")
                print(f"상세페이지 타이틀: {detail_soup.title.get_text(strip=True) if detail_soup.title else '(없음)'}")

                # ISBN은 보통 meta 태그나 표(table) 형태로 노출되는 경우가 많음
                for meta in detail_soup.find_all("meta"):
                    name = meta.get("property") or meta.get("name") or ""
                    if "isbn" in name.lower() or "barcode" in name.lower():
                        print(f"  meta[{name}] = {meta.get('content')}")

                isbn_text_candidates = detail_soup.find_all(
                    string=lambda s: s and "ISBN" in s
                )
                for s in isbn_text_candidates[:5]:
                    parent = s.parent
                    print(
                        f"  'ISBN' 텍스트 포함 노드: <{parent.name} class="
                        f"{parent.get('class')}> 주변 텍스트: "
                        f"{parent.get_text(' ', strip=True)[:200]}"
                    )

                # 저자/출판사 링크 패턴 (자체 검색 링크로 보이는 것들)
                for a in detail_soup.find_all("a", href=True)[:0]:
                    pass
                author_like = detail_soup.select("a.gd_pubArea, a[href*='author'], a[href*='Author']")
                for a in author_like[:5]:
                    print(f"  저자/작가 후보 링크: '{a.get_text(strip=True)}' ({a.get('href')})")
                publisher_like = detail_soup.select("a[href*='publisher'], a[href*='Publisher']")
                for a in publisher_like[:5]:
                    print(f"  출판사 후보 링크: '{a.get_text(strip=True)}' ({a.get('href')})")
            except Exception as e:
                print(f"상세페이지 조회 실패: {e}")


def diagnose_aladin(page):
    section("[알라딘] wbest.aspx?BranchType=1&BestType=NowBest (지금 베스트)")
    url = "https://www.aladin.co.kr/shop/common/wbest.aspx?BranchType=1&BestType=NowBest"
    try:
        # 1차 진단에서 bare page.goto() 1회 시도로 CloudFront 403을 받았는데,
        # 기존 검증된 알라딘 스크래퍼는 원래도 일시적 403을 겪어서 재시도
        # 로직(goto_with_retry)을 쓰고 있었음. 같은 재시도 로직으로 재확인.
        html = goto_with_retry(page, url)
    except Exception as e:
        print(f"페이지 로딩 실패(재시도 {3}회 모두 실패): {e}")
        return

    soup = BeautifulSoup(html, "html.parser")
    print(f"페이지 타이틀: {soup.title.get_text(strip=True) if soup.title else '(없음)'}")

    boxes = soup.select("div.ss_book_box")
    print(f"\n기존 selector(div.ss_book_box) 매칭 개수: {len(boxes)}")
    items = []
    for i, box in enumerate(boxes[:15]):
        title_tag = box.select_one("a.bo3")
        title = title_tag.get_text(strip=True) if title_tag else "(제목 파싱 실패)"
        href = title_tag.get("href", "") if title_tag else ""
        if href and href.startswith("/"):
            href = "https://www.aladin.co.kr" + href
        items.append({"title": title, "url": href})
        print(f"  [{i + 1}] {title}")

    # 1차 진단에서 상위 15개 중 '[세트] 피를 마시는 새 오디오북', '감쪽같은
    # 수정 테이프 무소음' 처럼 도서가 아닌 상품(오디오북 세트, 문구류)이
    # 섞여 있는 것을 확인했음. 이런 항목이 기존 상세페이지 파싱
    # (parse_detail, isbn13 메타 태그 기준)에서 실제로 isbn13이 안 잡히는지
    # -> "isbn13 없으면 도서 아님으로 보고 제외"가 안전한 필터인지 확인한다.
    print("\n--- 의심 항목(도서 아닐 가능성) + 대조군 1건의 상세페이지 isbn13 확인 ---")
    suspects_by_title = [
        "[세트] 피를 마시는 새 오디오북 (총8권)",
        "감쪽같은 수정 테이프 무소음 (총3m)",
    ]
    to_check = [it for it in items if it["title"] in suspects_by_title]
    control = next((it for it in items if it["title"] not in suspects_by_title), None)
    if control:
        to_check.append(control)
    for it in to_check:
        if not it["url"]:
            print(f"  '{it['title']}': URL을 못 찾아 상세페이지 확인 불가")
            continue
        try:
            detail_html = goto_with_retry(page, it["url"])
            detail = parse_detail(detail_html)
        except Exception as e:
            print(f"  '{it['title']}': 상세페이지 조회 실패 ({e})")
            continue
        print(
            f"  '{it['title']}': isbn13={detail['isbn13'] or '(없음)'}"
            f" / author={detail['author'] or '(없음)'}"
            f" / publisher={detail['publisher'] or '(없음)'}"
        )

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
        page = browser.new_page(user_agent=USER_AGENT, **CONTEXT_KWARGS)

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
