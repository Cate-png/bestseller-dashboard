"""교보문고 "실시간 베스트셀러"(store.kyobobook.co.kr/bestseller/realtime) 조사.

Supabase에 아무것도 저장하지 않는 읽기 전용 진단 스크립트입니다.

1차 조사(이미 완료, 이 파일의 앞부분 로직)로 다음을 확인했습니다:
- 실시간 페이지는 api/gw/best/best-seller/realtime?page=N&per=20 이라는
  주간(best-seller/total)과는 별도의 API로 채워짐.
- 응답에 total=100이 명시되어 있고, page=1/page=2가 실제로 서로 다른
  20권(1~20위 / 21~40위, ISBN 겹침 0건)을 반환함 -> 페이지네이션으로
  TOP100 전체를 모을 수 있음이 확인됨.

이번(2차) 조사의 목적: rank_change를 이 API의 frmrRnkn 필드로 계산해도
되는지 판단하기 위해, "frmrRnkn이 실시간 문맥에서 진짜 무엇을 의미하는지"를
추측 없이 확인합니다. 주간(best-seller/total)의 frmrRnkn과 필드 이름은
같지만, 실시간 API이므로 의미가 다를 수 있다는 전제로 접근합니다.

확인할 것:
1. 실시간 TOP100(page=1~5) 응답에 frmrRnkn 필드가 실제로 존재하는지, 값의
   분포(= prstRnkn과 다른 값 개수, 0인 개수, null인 개수)
2. 실시간 응답의 frmrRnkn 값이 "같은 책의 주간(weekly) prstRnkn"과 우연히
   일치하는 비율이 높은지 낮은지 - 만약 대부분 일치한다면 실시간 API가
   frmrRnkn 자리에 실제로는 "주간 순위"를 재사용하고 있다는 뜻이 되므로
   "직전 시간대 순위"로 해석하면 안 됨. 반대로 거의 일치하지 않는다면
   주간 값과 무관한 별도의 값(진짜 실시간 이전 스냅샷일 가능성)이라는
   근거가 됨.
3. 응답에 순위 데이터 갱신 시각을 알 수 있는 다른 필드(ymw 등)가 있는지
   원본 JSON을 그대로 출력해서 확인.
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
WEEKLY_URL = "https://store.kyobobook.co.kr/bestseller/total/weekly"


def section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def capture_api_calls(page, url, url_substr):
    captured = []

    def on_response(response):
        try:
            resp_url = response.url
            if url_substr not in resp_url:
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
        page.wait_for_timeout(1500)
    finally:
        page.remove_listener("response", on_response)

    return captured


def fetch_paginated(page, base_url, url_substr, pages=5):
    """base_url?page=1..pages 를 순서대로 열어 각 응답의 bestSeller 항목을 모읍니다."""
    all_items = []
    raw_bodies = []
    for page_num in range(1, pages + 1):
        page_url = base_url if page_num == 1 else f"{base_url}?page={page_num}"
        captured = capture_api_calls(page, page_url, url_substr)
        if not captured:
            print(f"  page={page_num}: API 응답을 캡처하지 못함")
            continue
        _, body = captured[-1]
        raw_bodies.append(body)
        data = body.get("data", {}) if isinstance(body, dict) else {}
        items = data.get("bestSeller", [])
        ranks = [it.get("prstRnkn") for it in items]
        print(
            f"  page={page_num}: {len(items)}건, prstRnkn "
            f"{min(ranks) if ranks else '-'}~{max(ranks) if ranks else '-'}, "
            f"ymw={data.get('ymw')!r}, total={data.get('total')!r}"
        )
        all_items.extend(items)
    return all_items, raw_bodies


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul")

        section("[1] 실시간 TOP100 수집 (page=1~5, api/gw/best/best-seller/realtime)")
        realtime_items, realtime_raw = fetch_paginated(
            page, REALTIME_URL, "best-seller/realtime", pages=5
        )
        print(f"\n실시간 총 수집 항목 수: {len(realtime_items)}")

        # 중복 확인 (1~5페이지 사이에 같은 도서가 중복으로 들어왔는지)
        codes = [it.get("cmdtCode") for it in realtime_items if it.get("cmdtCode")]
        dup_count = len(codes) - len(set(codes))
        print(f"cmdtCode 기준 중복 건수: {dup_count}")

        section("[2] 실시간 응답의 원본 JSON 필드 전체 확인 (앞 3건)")
        for it in realtime_items[:3]:
            print(json.dumps(it, ensure_ascii=False, indent=2))

        section("[3] frmrRnkn 필드 존재 여부 및 값 분포 (실시간 TOP100 기준)")
        has_field = [it for it in realtime_items if "frmrRnkn" in it]
        print(f"frmrRnkn 키가 존재하는 항목 수: {len(has_field)} / {len(realtime_items)}")
        if has_field:
            null_frmr = [it for it in realtime_items if it.get("frmrRnkn") is None]
            zero_frmr = [it for it in realtime_items if it.get("frmrRnkn") == 0]
            diff_frmr = [
                it for it in realtime_items
                if it.get("frmrRnkn") not in (None, 0)
                and it.get("frmrRnkn") != it.get("prstRnkn")
            ]
            same_frmr = [
                it for it in realtime_items
                if it.get("frmrRnkn") not in (None, 0)
                and it.get("frmrRnkn") == it.get("prstRnkn")
            ]
            print(f"  frmrRnkn == null: {len(null_frmr)}건")
            print(f"  frmrRnkn == 0: {len(zero_frmr)}건")
            print(f"  frmrRnkn != prstRnkn (0/null 아님, 실제 변동으로 보이는 값): {len(diff_frmr)}건")
            print(f"  frmrRnkn == prstRnkn (변동 없음으로 보이는 값): {len(same_frmr)}건")
            for it in diff_frmr[:5]:
                print(
                    f"    '{it.get('cmdtName')}': prstRnkn={it.get('prstRnkn')} "
                    f"frmrRnkn={it.get('frmrRnkn')}"
                )

        section("[4] 실시간 TOP100 도서 중 '주간 TOP100'에도 있는 도서 대상, "
                "실시간 frmrRnkn 값이 '주간 prstRnkn(현재 주간 순위)'과 우연히 일치하는지 확인")
        weekly_items, _ = fetch_paginated(page, WEEKLY_URL, "best-seller/total", pages=5)
        weekly_rank_by_isbn = {
            it.get("cmdtCode"): it.get("prstRnkn")
            for it in weekly_items
            if it.get("cmdtCode")
        }
        print(f"\n주간 TOP100 수집 항목 수: {len(weekly_items)}")

        overlap_checked = 0
        matches_weekly_prstRnkn = 0
        for it in realtime_items:
            isbn = it.get("cmdtCode")
            frmr = it.get("frmrRnkn")
            if not isbn or isbn not in weekly_rank_by_isbn or frmr in (None, 0):
                continue
            overlap_checked += 1
            if frmr == weekly_rank_by_isbn[isbn]:
                matches_weekly_prstRnkn += 1

        print(
            f"실시간·주간 양쪽에 다 있고 frmrRnkn이 0/null이 아닌 도서: {overlap_checked}건 중, "
            f"실시간 frmrRnkn == 주간 prstRnkn(현재 주간 순위)인 경우: {matches_weekly_prstRnkn}건"
        )
        if overlap_checked > 0:
            ratio = matches_weekly_prstRnkn / overlap_checked * 100
            print(f"일치 비율: {ratio:.1f}%")
            if ratio > 50:
                print(
                    "-> 절반 이상 일치합니다. 실시간 API의 frmrRnkn이 실제로는 "
                    "'주간 순위'를 재사용하고 있을 가능성이 있습니다 "
                    "(직전 시간대 순위로 해석하면 안 될 수 있음)."
                )
            else:
                print(
                    "-> 대부분 일치하지 않습니다. 실시간 frmrRnkn이 주간 순위를 "
                    "그대로 재사용하는 것은 아닌 것으로 보입니다."
                )

        browser.close()

    print("\n" + "=" * 80)
    print("진단 완료. 이 스크립트는 Supabase에 아무것도 저장하지 않습니다.")
    print("=" * 80)


if __name__ == "__main__":
    main()
