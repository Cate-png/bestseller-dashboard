// 출판사명이 정확히 "위즈덤하우스"로만 저장되어 있지 않을 수 있어서
// (예: "위즈덤하우스(주)", "Wisdom House", 공백 유무 등)
// 공백 제거 + 소문자 변환 후 핵심 문자열이 포함되어 있는지로 판단합니다.
// 다만 너무 느슨하면 다른 출판사가 잘못 걸릴 수 있으니, 아래 두 패턴으로만 제한합니다.
export function isWisdomHouse(publisher) {
  if (!publisher) return false;
  const normalized = publisher.replace(/\s/g, "").toLowerCase();
  return (
    normalized.includes("위즈덤하우스") || normalized.includes("wisdomhouse")
  );
}
