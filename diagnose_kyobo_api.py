"""교보문고 주간 베스트셀러 내부 JSON API로 전환하기 전, 실제 응답의 필드
의미/값 범위와 호출 방식을 GitHub Actions에서 직접 확인하기 위한 읽기 전용
진단 스크립트. Supabase에 아무것도 저장하지 않습니다.

확인할 것:
1. 이 API를 plain requests(Playwright 없이)로 직접 호출해도 되는지, 아니면
   Referer/쿠키 등 브라우저 컨텍스트가 필요한지 (짐작하지 않고 실측)
2. per=100 한 번 호출로 TOP100을 다 받을 수 있는지, 아니면 페이지네이션이
   필요한지, "total" 필드의 실제 의미
3. frmrRnkn(이전 순위)이 실제로 prstRnkn(현재 순위)과 다른 값을 갖는
   항목이 있는지(진짜 신호가 있는지), 신규 진입 도서는 frmrRnkn이 어떻게
   표현되는지(null/0/누락 등)
4. cmdtCode(ISBN)가 비어있는 항목이 있는지
5. 분야별(카테고리) 주간 베스트셀러 페이지는 어떤 API/파라미터를 쓰는지
   (교보 카테고리 코드별로 실제 네트워크 요청을 캡처해서 확인)
"""

import json
import sys

import requests

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("오류: playwright 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)

TOTAL_API_BASE = "https://store.kyobobook.co.kr/api/gw/best/best-seller/total"


def section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def summarize_items(items):
    print(f"항목 수: {len(items)}")
    if not items:
        return
    ranks = [it.get("prstRnkn") for it in items]
    print(f"prstRnkn 범위: {min(ranks)} ~ {max(ranks)}")

    diff_items = [it for it in items if it.get("frmrRnkn") != it.get("prstRnkn")]
    print(f"frmrRnkn != prstRnkn인 항목 수: {len(diff_items)} / {len(items)}")
    for it in diff_items[:5]:
        print(
            f"  '{it.get('cmdtName')}': prstRnkn={it.get('prstRnkn')} "
            f"frmrRnkn={it.get('frmrRnkn')} (raw type: {type(it.get('frmrRnkn')).__name__})"
        )

    null_frmr = [it for it in items if it.get("frmrRnkn") is None]
    print(f"frmrRnkn이 null인 항목 수: {len(null_frmr)}")
    for it in null_frmr[:5]:
        print(f"  '{it.get('cmdtName')}': prstRnkn={it.get('prstRnkn')} frmrRnkn=None")

    zero_frmr = [it for it in items if it.get("frmrRnkn") == 0]
    print(f"frmrRnkn이 0인 항목 수: {len(zero_frmr)}")
    for it in zero_frmr[:5]:
        print(f"  '{it.get('cmdtName')}': prstRnkn={it.get('prstRnkn')} frmrRnkn=0")

    no_isbn = [it for it in items if not it.get("cmdtCode")]
    print(f"cmdtCode(ISBN)가 비어있는 항목 수: {len(no_isbn)}")
    for it in no_isbn[:5]:
        print(f"  '{it.get('cmdtName')}': cmdtCode={it.get('cmdtCode')!r}")

    # total 필드가 무슨 의미인지 확인
    totals = {it.get("total") for it in items}
    print(f"응답에 포함된 'total' 필드 값(들): {totals}")


def diagnose_requests_direct_call():
    section("[교보 API] plain requests로 직접 호출 가능한지 확인")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    url = f"{TOTAL_API_BASE}?page=1&per=20&period=002&bsslBksClstCode=A"
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        print(f"헤더 없이(User-Agent만) 호출 -> status_code={resp.status_code}")
        if resp.status_code == 200:
            body = resp.json()
            print(f"최상위 키: {list(body.keys())}")
            items = body.get("data", {}).get("bestSeller", [])
            print(f"bestSeller 항목 수: {len(items)}")
        else:
            print(f"본문 일부: {resp.text[:500]}")
    except Exception as e:
        print(f"requests 직접 호출 실패: {e}")


def diagnose_per100_single_call():
    section("[교보 API] per=100 한 번 호출로 TOP100을 다 받을 수 있는지 확인")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    url = f"{TOTAL_API_BASE}?page=1&per=100&period=002&bsslBksClstCode=A"
    try:
        resp = requests.get(url, headers=headers, timeout=20)
        print(f"per=100 호출 -> status_code={resp.status_code}")
        if resp.status_code != 200:
            print(f"본문 일부: {resp.text[:500]}")
            return
        body = resp.json()
        items = body.get("data", {}).get("bestSeller", [])
        summarize_items(items)
    except Exception as e:
        print(f"per=100 호출 실패: {e}")


def diagnose_pagination_5x20():
    section("[교보 API] page=1..5, per=20으로 TOP100 커버 확인 (기존 방식과 동일한 페이지네이션)")
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    all_items = []
    for page in range(1, 6):
        url = f"{TOTAL_API_BASE}?page={page}&per=20&period=002&bsslBksClstCode=A"
        try:
            resp = requests.get(url, headers=headers, timeout=15)
            if resp.status_code != 200:
                print(f"  page={page}: status_code={resp.status_code}, 실패")
                continue
            body = resp.json()
            items = body.get("data", {}).get("bestSeller", [])
            print(f"  page={page}: {len(items)}건, rank {items[0]['prstRnkn'] if items else '-'}~{items[-1]['prstRnkn'] if items else '-'}")
            all_items.extend(items)
        except Exception as e:
            print(f"  page={page}: 예외 {e}")
    print()
    summarize_items(all_items)


def diagnose_category_api(page, category_label, kyobo_domestic_code):
    section(f"[교보 API] 분야별({category_label}, code={kyobo_domestic_code}) 페이지의 실제 네트워크 요청 캡처")

    captured = []

    def on_response(response):
        try:
            url = response.url
            if "kyobobook.co.kr/api/" not in url:
                return
            ctype = response.headers.get("content-type", "")
            if "json" not in ctype:
                return
            captured.append((url, response.json()))
        except Exception:
            pass

    page.on("response", on_response)
    url = f"https://store.kyobobook.co.kr/bestseller/online/weekly/domestic/{kyobo_domestic_code}"
    try:
        page.goto(url, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=30000)
        page.wait_for_timeout(2000)
    except Exception as e:
        print(f"페이지 로딩 실패: {e}")
        page.remove_listener("response", on_response)
        return
    page.remove_listener("response", on_response)

    print(f"캡처된 API 응답 개수: {len(captured)}")
    for url, body in captured:
        print(f"\n  {url}")
        if isinstance(body, dict) and "data" in body:
            data = body["data"]
            if isinstance(data, dict):
                for key, val in data.items():
                    if isinstance(val, list):
                        print(f"    data.{key}: 리스트, {len(val)}건")
                        if val:
                            print(f"    첫 항목 키: {list(val[0].keys())}")
                            print(f"    첫 항목 샘플: {json.dumps(val[0], ensure_ascii=False)[:500]}")


def diagnose_playwright_pagination():
    """plain requests가 403(API Gateway 라이센스 키 없음)으로 막혔으므로,
    기존에 검증된 방식대로 Playwright로 실제 페이지를 열고 그 안에서 발생하는
    API 호출을 가로채는 방식으로 page=1..5 페이지네이션이 실제로 동작하는지,
    그리고 frmrRnkn/cmdtCode가 TOP100 전체에서 어떤 값 범위를 갖는지 확인."""
    section("[교보 API] Playwright로 page=1..5 실제 탐색 + TOP100 전체 필드 확인")

    all_items = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul")

        for page_num in range(1, 6):
            captured = []

            def on_response(response, bucket=captured):
                try:
                    url = response.url
                    if "best-seller/total" not in url:
                        return
                    ctype = response.headers.get("content-type", "")
                    if "json" not in ctype:
                        return
                    bucket.append((url, response.json()))
                except Exception:
                    pass

            page.on("response", on_response)
            url = f"https://store.kyobobook.co.kr/bestseller/total/weekly?page={page_num}"
            try:
                page.goto(url, timeout=30000)
                page.wait_for_load_state("networkidle", timeout=30000)
                page.wait_for_timeout(1500)
            except Exception as e:
                print(f"  page={page_num}: 페이지 로딩 실패 {e}")
                page.remove_listener("response", on_response)
                continue
            page.remove_listener("response", on_response)

            if not captured:
                print(f"  page={page_num}: API 응답을 캡처하지 못함")
                continue
            url, body = captured[-1]
            items = body.get("data", {}).get("bestSeller", [])
            ranks = [it.get("prstRnkn") for it in items]
            print(
                f"  page={page_num}: 캡처된 URL={url}"
                f" -> {len(items)}건, prstRnkn {min(ranks) if ranks else '-'}~{max(ranks) if ranks else '-'}"
            )
            all_items.extend(items)

        browser.close()

    print()
    summarize_items(all_items)


def main():
    diagnose_requests_direct_call()
    diagnose_per100_single_call()
    diagnose_pagination_5x20()
    diagnose_playwright_pagination()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul")
        try:
            diagnose_category_api(page, "소설", "01")
        except Exception as e:
            print(f"\n[분야별 API 진단] 예외 발생: {e}")
        browser.close()

    print("\n" + "=" * 80)
    print("진단 완료. 이 스크립트는 Supabase에 아무것도 저장하지 않습니다.")
    print("=" * 80)


if __name__ == "__main__":
    main()
