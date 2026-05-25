'use client';

import './globals.css';
import { SessionProvider } from '@/context/SessionContext';
import Header from '@/components/Header';

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>
        <SessionProvider>
        {/* 공통 헤더 네비게이션 */}
        <Header />

        {/* 메인 콘텐츠 뷰포트 */}
        <main style={{ maxWidth: '1200px', margin: '0 auto', padding: '40px 24px' }}>
          {children}
        </main>
        </SessionProvider>
      </body>
    </html>
  );
}
