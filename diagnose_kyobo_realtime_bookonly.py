"""교보 실시간 베스트셀러(TOP100) API 응답에서 도서/비도서를 구분할 수 있는
필드를 실측으로 찾기 위한 읽기 전용 진단 스크립트. Supabase에 아무것도
저장하지 않습니다.

배경: TOP100 페이지네이션 적용 후 실제 실행 결과, 45/46위(디퓨저/차량용
방향제), 52위("Words from Within", isbn=480D260888480), 66위(음반 GOGO),
85위(만화 굿즈로 추정, isbn=480D260724410) 등 도서가 아닌 상품이 섞여
들어오는 것이 확인됨. 예전 TOP20 방식은
a[href*='product.kyobobook.co.kr/detail/'] img selector가 사실상 도서
전용 필터 역할을 했지만, API 기반으로 전환하면서 그 필터가 없어졌음.

이 스크립트는 다음을 확인합니다:
1. 실시간 TOP100(page=1~5) 전체 항목의 saleCmdtClstCode/saleCmdtClstName/
   saleCmdtGrpDvsnCode/saleCmdtDvsnCode 값 분포 - 어떤 필드가 도서/비도서를
   안정적으로 구분하는지
2. 이미 문제로 확인된 특정 순위(45,46,52,66,85 등 비13자리숫자 isbn13
   또는 이름으로 비도서로 추정되는 항목)의 위 필드 값을 정상 도서 항목과
   나란히 비교
3. page=6 이상을 요청했을 때도 실제로 데이터가 오는지(사이트가 top100
   너머의 순위 데이터도 갖고 있어서, 비도서를 제외한 뒤 그 다음 순위로
   TOP100을 채우는 것이 가능한지 확인하기 위함)
"""

import json
import sys
from collections import Counter

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("오류: playwright 라이브러리가 설치되어 있지 않습니다.")
    sys.exit(1)

from test_save_kyobo import USER_AGENT, fetch_best_seller_page

REALTIME_URL = "https://store.kyobobook.co.kr/bestseller/realtime"

# 이전 실제 실행(GitHub Actions)에서 비도서로 의심되는 것으로 확인된 상품명(일부)
SUSPECTED_NON_BOOK_NAME_SUBSTR = [
    "디퓨저", "방향제", "Words from Within", "GOGO", "슈퍼 뒤에서 담배 피우는 두 사람",
]


def section(title):
    print("\n" + "=" * 80)
    print(title)
    print("=" * 80)


def dump_item_key_fields(it, label=""):
    print(
        f"  {label}prstRnkn={it.get('prstRnkn')} cmdtName={it.get('cmdtName')!r}\n"
        f"    cmdtCode={it.get('cmdtCode')!r}\n"
        f"    saleCmdtClstCode={it.get('saleCmdtClstCode')!r} "
        f"saleCmdtClstName={it.get('saleCmdtClstName')!r}\n"
        f"    saleCmdtGrpDvsnCode={it.get('saleCmdtGrpDvsnCode')!r} "
        f"saleCmdtDvsnCode={it.get('saleCmdtDvsnCode')!r}\n"
        f"    cmdtCdtnCode={it.get('cmdtCdtnCode')!r} saleCdtnCode={it.get('saleCdtnCode')!r}"
    )


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent=USER_AGENT, locale="ko-KR", timezone_id="Asia/Seoul")

        section("[1] 실시간 TOP100 (page=1~5) 전체 항목 수집")
        all_items = []
        for page_num in range(1, 6):
            page_url = REALTIME_URL if page_num == 1 else f"{REALTIME_URL}?page={page_num}"
            try:
                items = fetch_best_seller_page(page, page_url)
            except Exception as e:
                print(f"  page={page_num}: 조회 실패 {e}")
                continue
            print(f"  page={page_num}: {len(items)}건")
            all_items.extend(items)
        print(f"\n총 수집: {len(all_items)}건")

        section("[2] saleCmdtClstCode / saleCmdtClstName 값 분포 (TOP100 전체)")
        clst_counter = Counter(
            (it.get("saleCmdtClstCode"), it.get("saleCmdtClstName")) for it in all_items
        )
        for (code, name), count in clst_counter.most_common():
            print(f"  {count:>3}건  saleCmdtClstCode={code!r}  saleCmdtClstName={name!r}")

        section("[3] saleCmdtGrpDvsnCode 값 분포 (TOP100 전체)")
        grp_counter = Counter(it.get("saleCmdtGrpDvsnCode") for it in all_items)
        for val, count in grp_counter.most_common():
            print(f"  {count:>3}건  saleCmdtGrpDvsnCode={val!r}")

        section("[4] saleCmdtDvsnCode 값 분포 (TOP100 전체)")
        dvsn_counter = Counter(it.get("saleCmdtDvsnCode") for it in all_items)
        for val, count in dvsn_counter.most_common():
            print(f"  {count:>3}건  saleCmdtDvsnCode={val!r}")

        section("[5] 비도서로 의심되는 항목들의 필드 값 (이름 매칭)")
        suspected = [
            it for it in all_items
            if any(s in (it.get("cmdtName") or "") for s in SUSPECTED_NON_BOOK_NAME_SUBSTR)
        ]
        print(f"이름으로 매칭된 의심 항목 수: {len(suspected)}")
        for it in suspected:
            dump_item_key_fields(it)
            print()

        section("[6] 정상 도서로 보이는 항목(TOP5) 필드 값 - 비교 기준")
        normal_books = sorted(all_items, key=lambda it: it.get("prstRnkn") or 9999)[:5]
        for it in normal_books:
            dump_item_key_fields(it)
            print()

        section("[7] isbn13이 13자리 순수 숫자가 아닌 항목 전체 (cmdtCode 기준)")
        non_numeric = [
            it for it in all_items
            if not (str(it.get("cmdtCode") or "").isdigit() and len(str(it.get("cmdtCode") or "")) == 13)
        ]
        print(f"cmdtCode가 13자리 순수 숫자가 아닌 항목 수: {len(non_numeric)}")
        for it in non_numeric:
            dump_item_key_fields(it)
            print()

        section("[8] page=6, page=7 요청 시 실제로 데이터가 오는지 확인 (TOP100 너머 백필 가능 여부)")
        for page_num in (6, 7):
            page_url = f"{REALTIME_URL}?page={page_num}"
            try:
                items = fetch_best_seller_page(page, page_url)
            except Exception as e:
                print(f"  page={page_num}: 조회 실패 {e}")
                continue
            if not items:
                print(f"  page={page_num}: 빈 응답 (항목 0건)")
                continue
            ranks = [it.get("prstRnkn") for it in items]
            print(
                f"  page={page_num}: {len(items)}건, prstRnkn "
                f"{min(ranks) if ranks else '-'}~{max(ranks) if ranks else '-'}, "
                f"total={items[0].get('total') if items else '-'}"
            )
            for it in items[:3]:
                dump_item_key_fields(it)

        browser.close()

    print("\n" + "=" * 80)
    print("진단 완료. 이 스크립트는 Supabase에 아무것도 저장하지 않습니다.")
    print("=" * 80)


if __name__ == "__main__":
    main()
