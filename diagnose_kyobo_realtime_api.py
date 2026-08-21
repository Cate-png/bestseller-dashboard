"""교보문고 "실시간 베스트셀러"(store.kyobobook.co.kr/bestseller/realtime)가
TOP20만 보여주는 것이 실제로 사이트 자체의 한계인지, 아니면
test_save_kyobo_realtime.py가 페이지네이션을 시도하지 않아서인지 확인하기
위한 읽기 전용 진단 스크립트. Supabase에 아무것도 저장하지 않습니다.

배경: test_save_kyobo_realtime.py는 diagnose_realtime.py(정적 HTML/selector
개수만 확인, 네트워크 API 캡처는 하지 않음)를 근거로 TARGET_COUNT=20을
쓰고 있음. 그런데 그 이후 종합 주간 베스트셀러(test_save_kyobo.py)를 조사하며
store.kyobobook.co.kr/bestseller/total/weekly가 실제로는
api/gw/best/best-seller/total?page=N&per=20&period=002&bsslBksClstCode=A
라는 내부 API로 채워지고, page=1~5로 TOP100 전체를 커버한다는 것을 확인함.
실시간 페이지도 같은 API 계열(다른 period/파라미터)로 동작해서 페이지네이션이
가능한데 그냥 안 쓰고 있는 것인지, 아니면 실시간 자체가 원래 TOP20까지만
제공되는 것인지 실제 네트워크 응답으로 확인한다.

확인할 것:
1. /bestseller/realtime 페이지가 로딩될 때 어떤 API(URL/쿼리파라미터)가
   호출되는지 (api/gw/best/* 전부 캡처, best-seller/total로 좁히지 않음)
2. 그 API가 반환하는 항목 수, 그리고 응답 안에 "total"류 필드(전체 건수)가
   있는지
3. /bestseller/realtime?page=2 처럼 쿼리를 붙였을 때 실제로 다른 API
   호출(다른 page 파라미터)이 발생하는지, 발생한다면 그 응답이 새로운
   도서(21위~40위)인지 아니면 같은 TOP20을 반복하는지
"""

import json
import sys

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("오류: playwright 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

REALTIME_URL = "https://store.kyobobook.co.kr/bestseller/realtime"


def section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def capture_api_calls(page, url):
    captured = []

    def on_response(response):
        try:
            resp_url = response.url
            if "api/gw/best" not in resp_url:
                return
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            captured.append((resp_url, response.json()))
        except Exception:
            pass

    page.on("response", on_response)
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    finally:
        page.remove_listener("response", on_response)

    return captured


def describe_items(body):
    if not isinstance(body, dict):
        print(f"  (dict가 아닌 응답: {type(body)})")
        return None
    data = body.get("data")
    if not isinstance(data, dict):
        print(f"  최상위 키: {list(body.keys())} (data가 dict 아님: {type(data)})")
        return None
    print(f"  data 하위 키: {list(data.keys())}")
    items = data.get("bestSeller")
    if not isinstance(items, list):
        # bestSeller가 아닌 다른 키에 리스트가 들어있을 수 있음
        for k, v in data.items():
            if isinstance(v, list):
                print(f"  (참고) data.{k}는 리스트, {len(v)}건")
        return None
    ranks = [it.get("prstRnkn") for it in items]
    print(f"  bestSeller 항목 수: {len(items)}, prstRnkn 범위: {min(ranks) if ranks else '-'}~{max(ranks) if ranks else '-'}")
    for it in items[:3]:
        print(
            f"    prstRnkn={it.get('prstRnkn')} cmdtName={it.get('cmdtName')!r} "
            f"cmdtCode={it.get('cmdtCode')!r}"
        )
    # total류 필드가 있는지 확인
    total_like = {k: v for k, v in data.items() if "total" in k.lower() or "cnt" in k.lower() or "count" in k.lower()}
    if total_like:
        print(f"  전체 건수로 보이는 필드: {total_like}")
    return items


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul")

        section("[1] /bestseller/realtime (page 파라미터 없음) 로딩 시 실제 API 호출 캡처")
        captured1 = capture_api_calls(page, REALTIME_URL)
        print(f"캡처된 api/gw/best/* 응답 개수: {len(captured1)}")
        items_page1 = None
        for url, body in captured1:
            print(f"\n  URL: {url}")
            items = describe_items(body)
            if items:
                items_page1 = items

        section("[2] /bestseller/realtime?page=2 로딩 시 실제 API 호출 캡처 (페이지네이션 여부 확인)")
        captured2 = capture_api_calls(page, f"{REALTIME_URL}?page=2")
        print(f"캡처된 api/gw/best/* 응답 개수: {len(captured2)}")
        items_page2 = None
        for url, body in captured2:
            print(f"\n  URL: {url}")
            items = describe_items(body)
            if items:
                items_page2 = items

        if items_page1 and items_page2:
            isbns1 = {it.get("cmdtCode") for it in items_page1}
            isbns2 = {it.get("cmdtCode") for it in items_page2}
            overlap = isbns1 & isbns2
            section("[3] page 없음 vs page=2 결과 비교")
            print(f"page 없음 항목 수: {len(items_page1)}, page=2 항목 수: {len(items_page2)}")
            print(f"겹치는 ISBN 수: {len(overlap)} / {len(isbns1)}")
            if overlap == isbns1 == isbns2:
                print("-> 완전히 동일한 목록입니다. page 파라미터가 실시간 페이지에서는 무시되는 것으로 보입니다.")
            elif len(overlap) < len(isbns1):
                print("-> 서로 다른 도서가 포함되어 있습니다. page 파라미터가 실제로 다음 페이지를 반환하는 것으로 보입니다(페이지네이션 가능).")

        browser.close()

    print("\n" + "=" * 80)
    print("진단 완료. 이 스크립트는 Supabase에 아무것도 저장하지 않습니다.")
    print("=" * 80)


if __name__ == "__main__":
    main()
