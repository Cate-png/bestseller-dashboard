// 분야별 TOP20 조회 UI에서 쓰는 분야 목록.
// Python 수집 스크립트 쪽 categories.py와 이름을 맞춰뒀습니다(수집/조회 양쪽 다
// 이 14개 분야를 다룹니다). "종합"은 여기 포함하지 않고, 기존 종합 TOP100과
// 구분해서 app/page.js / Dashboard.jsx에서 별도로 다룹니다.
// 배열 순서가 그대로 Dashboard.jsx의 분야 탭(2단) 표시 순서로 쓰입니다.
export const CATEGORIES = [
  "인문",
  "경제경영",
  "자기계발",
  "소설",
  "에세이/시",
  "사회과학",
  "역사",
  "예술",
  "과학",
  "만화",
  "여행",
  "건강",
  "기술/IT",
  "종교",
];

// 분야별 탭에서 서점명을 누르면 이동할 "그 분야 주간 베스트셀러" 서점 원본
// 페이지를 만드는 데 쓰는 서점별 분야 식별자(components/Dashboard.jsx의
// getCategoryStoreLink에서 URL로 조립). categories.py에 실측 확인해 정리된
// 값과 동일하게 맞춰뒀습니다(수집 스크립트가 실제로 쓰는 값이라 신뢰할 수
// 있는 출처).
export const CATEGORY_STORE_CODES = {
  인문: { kyobo: "05", yes24: "001001019", aladin: "656" },
  경제경영: { kyobo: "13", yes24: "001001025", aladin: "170" },
  자기계발: { kyobo: "15", yes24: "001001026", aladin: "336" },
  소설: { kyobo: "01", yes24: "001001046", aladin: "1" },
  "에세이/시": { kyobo: "03", yes24: "001001047", aladin: "55889" },
  사회과학: { kyobo: "17", yes24: "001001022", aladin: "798" },
  역사: { kyobo: "19", yes24: "001001010", aladin: "74" },
  예술: { kyobo: "23", yes24: "001001007", aladin: "517" },
  과학: { kyobo: "29", yes24: "001001002", aladin: "987" },
  만화: { kyobo: "47", yes24: "001001008", aladin: "2551" },
  여행: { kyobo: "32", yes24: "001001009", aladin: "1196" },
  건강: { kyobo: "09", yes24: "001001011", aladin: "55890" },
  "기술/IT": { kyobo: "33", yes24: "001001003", aladin: "351" },
  종교: { kyobo: "21", yes24: "001001021", aladin: "1237" },
};
