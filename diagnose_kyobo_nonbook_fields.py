"""이미 실제 실시간 TOP100에 등장했던 것으로 확인된 비도서 상품들
("The Scent of Page : 디퓨저 리필액 250ML", "The Scent of Page : 차량용
방향제(개선판)", "GOGO [정규 3집] [PHOTOBOOK VER]")을 교보문고 검색으로 직접
찾아서, best-seller API와 동일한 분류 필드(saleCmdtClstCode/
saleCmdtClstName/saleCmdtGrpDvsnCode/saleCmdtDvsnCode)가 검색 결과 JSON에도
있는지, 있다면 실제 값이 무엇인지 확인하는 읽기 전용 진단 스크립트.

배경: diagnose_kyobo_realtime_bookonly.py를 실행한 시점(2026-08-22)의
실시간 TOP100에는 이 비도서 상품들이 더 이상 순위에 없어서(실시간이라 계속
바뀜), 그 상품들 자체의 분류 필드 값을 직접 볼 수 없었음. 도서/비도서를
구분하는 필터 기준을 추측 없이 확정하려면 이 상품들의 실제 필드 값이
필요함.

Supabase에 아무것도 저장하지 않습니다.
"""

import json
import re
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

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

# 2026-08-21 실시간 TOP100 실제 수집 로그에서 확인된 비도서로 의심되는 상품의
# cmdtCode(=isbn13 자리에 들어온 상품 바코드)와 이름
KNOWN_NON_BOOK_ITEMS = [
    ("8809457270583", "The Scent of Page : 디퓨저 리필액 250ML"),
    ("8809457270590", "The Scent of Page : 차량용 방향제(개선판)"),
    ("8804775481000", "GOGO [정규 3집] [PHOTOBOOK VER]"),
]


def section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def search_and_capture(page, keyword):
    """교보문고 통합검색 페이지를 열고, 그 과정에서 발생하는 상품 관련 JSON
    API 응답 전부를 캡처한다. 캡처된 응답 안에서 cmdtCode/saleCmdtClstCode
    등 익숙한 필드가 있는 항목을 찾아 반환한다."""
    captured = []

    def on_response(response):
        try:
            url = response.url
            if "kyobobook.co.kr" not in url:
                return
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            captured.append((url, response.json()))
        except Exception:
            pass

    page.on("response", on_response)
    search_url = f"https://search.kyobobook.co.kr/search?keyword={keyword}"
    try:
        page.goto(search_url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"  검색 페이지 로딩 실패: {e}")
    page.remove_listener("response", on_response)
    return captured


def find_items_with_code(obj, target_code, found, path="root"):
    """중첩된 JSON 어디에 있든 cmdtCode == target_code인 dict를 찾아낸다."""
    if isinstance(obj, dict):
        if obj.get("cmdtCode") == target_code:
            found.append((path, obj))
        for k, v in obj.items():
            find_items_with_code(v, target_code, found, f"{path}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            find_items_with_code(v, target_code, found, f"{path}[{i}]")


def find_items_with_name_substr(obj, name_substr, found, path="root", max_found=5):
    """cmdtCode 필드명이 다를 수 있으므로, 대신 dict 안의 어떤 문자열 값이든
    name_substr을 포함하면 그 dict 전체를 찾아낸다(필드명을 추측하지 않기
    위한 보강)."""
    if len(found) >= max_found:
        return
    if isinstance(obj, dict):
        for v in obj.values():
            if isinstance(v, str) and name_substr in v:
                found.append((path, obj))
                break
        for k, v in obj.items():
            find_items_with_name_substr(v, name_substr, found, f"{path}.{k}", max_found)
    elif isinstance(obj, list):
        for i, v in enumerate(obj[:50]):
            find_items_with_name_substr(v, name_substr, found, f"{path}[{i}]", max_found)


CATEGORY_HINT_WORDS = [
    "음반", "문구", "생활", "뷰티", "디지털", "DVD", "굿즈", "잡화", "팬시",
    "가전", "리빙", "음악", "취미", "디퓨저", "방향제", "국내도서", "eBook",
    "외국도서", "사은품",
]


def search_html_and_follow_detail(page, name):
    """search.kyobobook.co.kr는 SSR이라 상품 데이터가 JSON API가 아니라
    렌더링된 HTML 자체에 있다. HTML에서 상품명이 일치하는 카드를 찾아
    상세페이지 링크를 따라가서, 상세페이지의 카테고리 브레드크럼/타이틀에
    비도서를 암시하는 단어가 있는지 확인한다."""
    search_url = f"https://search.kyobobook.co.kr/search?keyword={name}"
    try:
        page.goto(search_url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(1500)
    except Exception as e:
        print(f"  검색 페이지 로딩 실패: {e}")
        return

    html = page.content()
    soup = BeautifulSoup(html, "html.parser")

    # 상품명 일부(첫 단어 제외 특징적 단어)로 링크 후보 탐색
    keyword = name.split()[0]
    candidate_links = []
    for a in soup.find_all("a", href=True):
        text = a.get_text(strip=True)
        if keyword in text or (a.get("title") and keyword in a.get("title")):
            candidate_links.append((text, a["href"]))
    seen = set()
    candidate_links = [c for c in candidate_links if not (c in seen or seen.add(c))]
    print(f"  검색 HTML에서 {keyword!r} 포함 링크 후보: {len(candidate_links)}건")
    for text, href in candidate_links[:5]:
        print(f"    '{text}' -> {href}")

    detail_href = None
    for text, href in candidate_links:
        if "product.kyobobook.co.kr/detail/" in href:
            detail_href = href
            break
    if not detail_href:
        print("  상세페이지 링크를 찾지 못함.")
        return

    detail_url = detail_href if detail_href.startswith("http") else "https://product.kyobobook.co.kr" + detail_href
    print(f"  상세페이지로 이동: {detail_url}")
    try:
        page.goto(detail_url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(1500)
    except Exception as e:
        print(f"  상세페이지 로딩 실패: {e}")
        return

    detail_html = page.content()
    detail_soup = BeautifulSoup(detail_html, "html.parser")
    title = detail_soup.title.get_text(strip=True) if detail_soup.title else "(제목 없음)"
    print(f"  상세페이지 타이틀: {title}")

    # 브레드크럼으로 보이는 nav/ol/ul 요소들의 텍스트 출력
    for tag_name in ("nav", "ol", "ul"):
        for el in detail_soup.find_all(tag_name, class_=re.compile("category|bread|location|snb", re.I)):
            text = el.get_text(" > ", strip=True)
            if text:
                print(f"  [브레드크럼 후보 <{tag_name}>] {text[:200]}")

    # 페이지 전체 텍스트에서 비도서를 암시하는 단어가 있는지 스캔
    page_text = detail_soup.get_text(" ", strip=True)
    hits = [w for w in CATEGORY_HINT_WORDS if w in page_text]
    print(f"  페이지 텍스트 내 카테고리 힌트 단어 발견: {hits}")


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul")

        for cmdt_code, name in KNOWN_NON_BOOK_ITEMS:
            section(f"[HTML 방식] 검색: {name!r}")
            try:
                search_html_and_follow_detail(page, name)
            except Exception as e:
                print(f"  예외 발생: {e}")

        for cmdt_code, name in KNOWN_NON_BOOK_ITEMS:
            section(f"검색: {name!r} (cmdtCode={cmdt_code})")
            captured = search_and_capture(page, name)
            print(f"  캡처된 JSON 응답 개수: {len(captured)}")

            found = []
            for url, body in captured:
                find_items_with_code(body, cmdt_code, found)

            if found:
                for path, item in found:
                    print(f"\n  [일치] {path}")
                    print(
                        f"    cmdtName={item.get('cmdtName')!r}\n"
                        f"    saleCmdtClstCode={item.get('saleCmdtClstCode')!r} "
                        f"saleCmdtClstName={item.get('saleCmdtClstName')!r}\n"
                        f"    saleCmdtGrpDvsnCode={item.get('saleCmdtGrpDvsnCode')!r} "
                        f"saleCmdtDvsnCode={item.get('saleCmdtDvsnCode')!r}\n"
                        f"    saleCdtnCode={item.get('saleCdtnCode')!r} "
                        f"cmdtCdtnCode={item.get('cmdtCdtnCode')!r}"
                    )
            else:
                print("  정확히 cmdtCode가 일치하는 항목을 못 찾음. "
                      "필드명이 다를 수 있으므로 이름 일부(첫 단어)로도 찾아본다:")
                name_kw = name.split()[0]
                name_found = []
                for url, body in captured:
                    find_items_with_name_substr(body, name_kw, name_found)
                if name_found:
                    for path, item in name_found:
                        print(f"\n  [이름 일치: {name_kw!r}] {path}")
                        print(f"    전체 필드: {json.dumps(item, ensure_ascii=False)[:1500]}")
                else:
                    print(
                        "  이름으로도 못 찾음. 캡처된 응답의 최상위 구조를 그대로 덤프"
                        "(스키마 확인용, 최대 2개 응답):"
                    )
                    for url, body in captured[:2]:
                        print(f"\n  URL: {url}")
                        print(f"  {json.dumps(body, ensure_ascii=False)[:2000]}")

        browser.close()

    print("\n" + "=" * 80)
    print("진단 완료. 이 스크립트는 Supabase에 아무것도 저장하지 않습니다.")
    print("=" * 80)


if __name__ == "__main__":
    main()
