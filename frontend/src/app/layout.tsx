import './globals.css';
import Link from 'next/link';

export const metadata = {
  title: 'On-Premise STT Meeting Minutes System',
  description: 'NVIDIA GPU 가속 온프레미스 한국어 실시간 STT 회의록 시스템',
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ko">
      <body>
        {/* 공통 헤더 네비게이션 */}
        <header className="nav-header">
          <div className="nav-container">
            <div style={{ display: 'flex', alignItems: 'center', gap: '32px' }}>
              <Link href="/" style={{ textDecoration: 'none' }}>
                <div style={{ display: 'flex', alignItems: 'center', gap: '8px' }}>
                  <div style={{
                    width: '32px',
                    height: '32px',
                    borderRadius: '8px',
                    background: 'var(--gradient-neon)',
                    display: 'flex',
                    alignItems: 'center',
                    justifyContent: 'center',
                    fontWeight: 'bold',
                    fontSize: '1.2rem',
                    color: 'white'
                  }}>
                    Ω
                  </div>
                  <span style={{
                    fontWeight: 800,
                    fontSize: '1.25rem',
                    fontFamily: 'var(--font-display)',
                    letterSpacing: '-0.03em',
                    color: 'white'
                  }}>
                    Aura<span className="gradient-text">STT</span>
                  </span>
                </div>
              </Link>
              
              <nav style={{ display: 'flex', gap: '20px' }}>
                <Link href="/" style={{
                  color: 'var(--text-secondary)',
                  textDecoration: 'none',
                  fontWeight: 500,
                  fontSize: '0.9rem'
                }}>
                  실시간 회의
                </Link>
                <Link href="/upload" style={{
                  color: 'var(--text-secondary)',
                  textDecoration: 'none',
                  fontWeight: 500,
                  fontSize: '0.9rem'
                }}>
                  음성 파일 변환
                </Link>
              </nav>
            </div>
            
            {/* GPU 상태 모니터 미니 위젯 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <div className="glass-panel" style={{
                padding: '6px 14px',
                borderRadius: '9999px',
                fontSize: '0.8rem',
                display: 'flex',
                alignItems: 'center',
                gap: '8px'
              }}>
                <span style={{
                  width: '8px',
                  height: '8px',
                  borderRadius: '50%',
                  backgroundColor: '#14b8a6',
                  display: 'inline-block'
                }}></span>
                <span style={{ color: 'var(--text-secondary)' }}>
                  GPU: <strong>RTX 3060</strong>
                </span>
              </div>
            </div>
          </div>
        </header>

        {/* 메인 콘텐츠 뷰포트 */}
        <main style={{ maxWidth: '1200px', margin: '0 auto', padding: '40px 24px' }}>
          {children}
        </main>
      </body>
    </html>
  );
}
