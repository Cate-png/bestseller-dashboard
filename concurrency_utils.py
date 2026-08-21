"""상세 페이지를 제한된 동시 실행(concurrency)으로 방문하기 위한 공용 헬퍼.

교보문고/알라딘의 종합·분야별 수집 스크립트 4개(test_save_kyobo.py,
test_save_kyobo_category.py, test_save_aladin.py, test_save_aladin_category.py)
가 공통으로 사용합니다. 상세 페이지 요청/파싱 로직 자체(fetch_detail,
parse_detail 등)는 각 스크립트에 그대로 두고, "여러 상세 페이지를 어떤
방식으로 방문하느냐"만 이 헬퍼가 담당합니다.

왜 스레드마다 완전히 별도의 Playwright 인스턴스를 쓰는가:
Playwright의 동기(sync) API는 같은 Browser/Page 객체를 여러 스레드에서
동시에 조작하는 것을 지원하지 않습니다(공식 문서상 스레드 간 공유 비권장).
그래서 워커 스레드마다 자기 자신만의 sync_playwright() 컨텍스트와 브라우저를
새로 띄워서 완전히 독립적으로 동작하게 했습니다. concurrency=4 기준으로
Chromium 인스턴스 4개가 동시에 뜨는 정도라 GitHub Actions 러너 리소스로
충분합니다.
"""

import random
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

from playwright.sync_api import sync_playwright


def enrich_details_concurrently(
    books,
    fetch_one,
    user_agent,
    concurrency=4,
    request_delay=2.0,
    context_kwargs=None,
):
    """books의 각 항목을 fetch_one(page, book)으로 처리해서 book(dict)에
    필요한 필드를 채워 넣습니다.

    - fetch_one(page, book): 상세 페이지 방문 + 파싱 + book 필드 채우기까지
      전부 책임집니다. 실패 시 자체적으로 예외를 처리하고 book에 기본값을
      채워 넣는 기존 각 스크립트의 방식을 그대로 재사용합니다(이 함수는
      fetch_one이 던지는 예외를 한 번 더 방어적으로 감싸기만 합니다).
    - concurrency개의 독립된 브라우저를 띄우고, books를 concurrency개
      그룹으로 나눠(라운드로빈) 워커별로 순차 처리합니다. 그룹 내부에서는
      기존과 동일하게 요청 사이에 request_delay(+지터)만큼 대기해서, 사이트에
      순간적으로 너무 많은 요청이 몰리지 않게 합니다.
    - book 객체는 그룹별로 겹치지 않게 나뉘므로, 여러 스레드가 같은 book을
      동시에 건드리는 경우는 없습니다.

    반환값은 books를 그대로 돌려줍니다(제자리에서 수정됨) - 기존
    enrich_with_details(...)의 반환 방식과 동일합니다.
    """
    context_kwargs = context_kwargs or {}
    if not books:
        return books

    worker_count = max(1, min(concurrency, len(books)))
    chunks = [books[i::worker_count] for i in range(worker_count)]

    def worker(chunk, worker_id):
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page(user_agent=user_agent, **context_kwargs)
            try:
                total = len(chunk)
                for i, book in enumerate(chunk):
                    print(
                        f"   [worker{worker_id}] [{book['rank']}] "
                        f"({i + 1}/{total}) 상세 조회 중: {book['title']}"
                    )
                    try:
                        fetch_one(page, book)
                    except Exception as e:
                        print(f"      -> [worker{worker_id}] 상세 페이지 조회 실패: {e}")
                    if i < total - 1:
                        time.sleep(request_delay + random.uniform(0, 1.0))
            finally:
                browser.close()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        futures = [
            executor.submit(worker, chunk, idx)
            for idx, chunk in enumerate(chunks)
            if chunk
        ]
        for f in as_completed(futures):
            f.result()

    return books
