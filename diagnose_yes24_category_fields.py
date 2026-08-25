"""[진단 전용/1회성 - 완료 후 삭제 가능] 예스24 종합 TOP100 API 원본 응답에
도서별 분야/카테고리 필드가 있는지 확인합니다.

- Supabase에 아무것도 쓰지 않는 순수 읽기 전용 스크립트입니다.
- test_save_yes24.py와 완전히 동일한 요청(YES24_URL, CATEGORY_ID="001")을
  그대로 재사용하되, 저장 로직은 전혀 없습니다. test_save_yes24.py 자체는
  이 스크립트가 import조차 하지 않고, 파일 하나 통째로 별도입니다.
- 출력 범위를 의도적으로 최소화했습니다:
  - API 키(YES24_API_KEY) 값 자체는 절대 출력하지 않습니다(요청 헤더
    구성에만 쓰고, 어떤 print()에도 등장하지 않습니다).
  - 도서 제목/ISBN/저자 등은 전혀 조회·출력하지 않습니다.
  - 순위(sortOrder)만 최소 식별자로 쓰고, 그 옆에 "분야/카테고리로 보이는
    이름의 필드"만 값과 함께 출력합니다.
  - 전체 필드 "이름" 목록(값 아님)은 항상 출력합니다 - 필드명 자체는
    개인정보가 아니고, 아래 정규식이 못 찾은 후보를 사람이 직접 눈으로
    확인할 수 있어야 하기 때문입니다. 정규식에 안 걸렸다고 "분야 필드가
    없다"고 이 스크립트가 단정하지 않습니다 - 그 판단은 이 목록을 본
    사람이 내립니다.

필요 환경변수: YES24_API_KEY (기존 collect.yml의 yes24 job과 동일한
Secret을 그대로 재참조 - Secret 값 자체는 전혀 바꾸지 않습니다)
"""
import os
import re

import requests

YES24_URL = "https://apis.yes24.com/v1/category/bestseller"
CATEGORY_ID = "001"
PAGE_SIZE = 20  # 필드 존재 여부만 보면 되므로 TOP20까지만 조회

# 필드 "이름"이 분야/카테고리를 가리키는 것으로 보이는지 판별하는 느슨한
# 패턴입니다(교보 saleCmdtClstCode/Name처럼 로마자 축약어를 쓰는 경우가
# 있어 넉넉하게 잡습니다). 여기 걸린 필드는 값을 바로 보여주지만, 안 걸렸다고
# 분야 필드가 없다는 뜻은 아닙니다 - 아래에서 항상 전체 필드명을 따로
# 출력해 사람이 직접 판단하도록 합니다.
CATEGORY_FIELD_PATTERN = re.compile(
    r"categ|genre|clst|cls|gubun|kind|group|classif", re.IGNORECASE
)


def main():
    api_key = os.environ["YES24_API_KEY"]  # 값은 여기서만 쓰고 절대 출력하지 않음
    headers = {"X-Api-Key": api_key, "Accept": "application/json"}
    params = {"categoryId": CATEGORY_ID, "page": 1, "pageSize": PAGE_SIZE}

    response = requests.get(YES24_URL, headers=headers, params=params, timeout=30)
    response.raise_for_status()
    payload = response.json()
    items = (payload.get("data") or {}).get("items") or []

    print(f"응답 도서 수: {len(items)}")
    if not items:
        print("도서가 없어 필드를 확인할 수 없습니다.")
        return

    all_keys = sorted(items[0].keys())
    print(
        "\n[전체 필드 이름 목록] (값 아님, 스키마 확인용 - 이 목록을 보고 "
        f"분야 관련 후보가 더 있는지 사람이 직접 판단해주세요)\n{all_keys}"
    )

    category_like_keys = [k for k in all_keys if CATEGORY_FIELD_PATTERN.search(k)]

    if category_like_keys:
        print(f"\n[정규식으로 걸린 분야/카테고리 후보 필드] {category_like_keys}")
        print("\n[순위 | 후보 필드 값들] (제목/ISBN 등은 출력하지 않음)")
        for item in items:
            rank = item.get("sortOrder")
            values = {k: item.get(k) for k in category_like_keys}
            print(f"{rank}위 | {values}")
    else:
        print(
            "\n[정규식으로 걸린 후보] 없음 - 이것이 '분야 필드가 없다'는 "
            "결론은 아닙니다. 위 전체 필드 이름 목록을 직접 확인해 분야/"
            "카테고리로 추정되는 다른 이름의 필드가 있는지 사람이 판단해야 "
            "합니다. 정말 그런 필드가 없는 것으로 확인되면 '현재 응답에서 "
            "확인되지 않음'으로 결론 내리면 됩니다."
        )


if __name__ == "__main__":
    main()
