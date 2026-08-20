import "./globals.css";

export const metadata = {
  title: "베스트셀러 실시간 현황",
  description: "교보문고 / 예스24 / 알라딘 베스트셀러 비교 대시보드",
};

export default function RootLayout({ children }) {
  return (
    <html lang="ko">
      <body>{children}</body>
    </html>
  );
}
