import "./globals.css";

// og:title/og:description/og:image는 <title>과 별개로 카카오톡·슬랙 등
// 메신저 링크 미리보기가 실제로 읽는 태그입니다(<title>만으로는 자동
// 생성되지 않음) - 지금까지 이 태그 자체가 없어서 미리보기가 아예 다른
// 값(예전 캐시)을 보여주는 원인이 됐습니다. metadataBase를 지정해야
// openGraph.images의 상대 경로("/logo.png")가 절대 URL로 정상 변환됩니다.
export const metadata = {
  metadataBase: new URL("https://wisdom-bestseller.vercel.app"),
  title: "베스트셀러 대시보드",
  description: "교보문고 / 예스24 / 알라딘 베스트셀러 비교 대시보드",
  openGraph: {
    title: "베스트셀러 대시보드",
    description: "교보문고 / 예스24 / 알라딘 베스트셀러 비교 대시보드",
    images: ["/logo.png"],
    locale: "ko_KR",
    type: "website",
  },
  twitter: {
    card: "summary",
    title: "베스트셀러 대시보드",
    description: "교보문고 / 예스24 / 알라딘 베스트셀러 비교 대시보드",
    images: ["/logo.png"],
  },
};

export default function RootLayout({ children }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
