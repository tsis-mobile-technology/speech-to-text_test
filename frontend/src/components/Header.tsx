'use client';

import Link from 'next/link';
import { useSession } from '@/context/SessionContext';

export default function Header() {
  const { isRecording } = useSession();

  return (
    <header className="nav-header">
      <div className="nav-container">
        <div style={{ display: 'flex', alignItems: 'center', gap: '32px' }}>
          <Link href="/" style={{ textDecoration: 'none' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
              <div style={{
                width: '36px',
                height: '36px',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                position: 'relative'
              }}>
                <svg
                  width="26"
                  height="26"
                  viewBox="0 0 26 26"
                  fill="none"
                  xmlns="http://www.w3.org/2000/svg"
                  style={{ overflow: 'visible' }}
                >
                  <defs>
                    <linearGradient id="logo-grad-1" x1="0%" y1="0%" x2="100%" y2="100%">
                      <stop offset="0%" stopColor="#818cf8" />
                      <stop offset="50%" stopColor="#c084fc" />
                      <stop offset="100%" stopColor="#e879f9" />
                    </linearGradient>
                    <linearGradient id="logo-grad-2" x1="0%" y1="100%" x2="100%" y2="0%">
                      <stop offset="0%" stopColor="#2dd4bf" />
                      <stop offset="100%" stopColor="#818cf8" />
                    </linearGradient>
                  </defs>
                  <rect x="1" y="9" width="3" height="8" rx="1.5" fill="url(#logo-grad-1)" className="logo-bar-1" />
                  <rect x="6" y="4" width="3" height="18" rx="1.5" fill="url(#logo-grad-2)" className="logo-bar-2" />
                  <rect x="11" y="1" width="3" height="24" rx="1.5" fill="url(#logo-grad-1)" className="logo-bar-3" />
                  <rect x="16" y="6" width="3" height="14" rx="1.5" fill="url(#logo-grad-2)" className="logo-bar-4" />
                  <rect x="21" y="10" width="3" height="6" rx="1.5" fill="url(#logo-grad-1)" className="logo-bar-5" />
                </svg>
              </div>
              <span style={{
                fontWeight: 800,
                fontSize: '1.25rem',
                fontFamily: 'var(--font-display)',
                letterSpacing: '-0.03em',
                color: 'white'
              }}>
                Diversity <span className="gradient-text">STT</span>
              </span>
            </div>
          </Link>
          
          <nav style={{ display: 'flex', gap: '24px' }}>
            <Link href="/" style={{
              color: 'var(--text-secondary)',
              textDecoration: 'none',
              fontWeight: 600,
              fontSize: '0.9rem',
              transition: 'color 0.2s ease'
            }} className="nav-link">
              실시간 회의
            </Link>
            <Link href="/upload" style={{
              color: 'var(--text-secondary)',
              textDecoration: 'none',
              fontWeight: 600,
              fontSize: '0.9rem',
              transition: 'color 0.2s ease'
            }} className="nav-link">
              음성 파일 변환
            </Link>
            <Link href="/sessions" style={{
              color: 'var(--text-secondary)',
              textDecoration: 'none',
              fontWeight: 600,
              fontSize: '0.9rem',
              transition: 'color 0.2s ease'
            }} className="nav-link">
              회의록 관리
            </Link>
          </nav>
        </div>
        
        {/* 우측 위젯 영역: 녹음 표시등 및 GPU 위젯 */}
        <div style={{ display: 'flex', alignItems: 'center', gap: '16px' }}>
          {/* 글로벌 실시간 녹음 중 알림 표시등 */}
          {isRecording && (
            <div className="glass-panel" style={{
              padding: '6px 14px',
              borderRadius: '9999px',
              fontSize: '0.8rem',
              display: 'flex',
              alignItems: 'center',
              gap: '8px',
              backgroundColor: 'rgba(239, 68, 68, 0.1)',
              border: '1px solid rgba(239, 68, 68, 0.25)',
              boxShadow: '0 0 10px rgba(239, 68, 68, 0.15)'
            }}>
              <span className="pulsing-dot" style={{
                width: '8px',
                height: '8px',
                borderRadius: '50%',
                backgroundColor: '#ef4444',
                display: 'inline-block'
              }}></span>
              <span style={{ color: '#fca5a5', fontWeight: 700, letterSpacing: '0.03em' }}>
                RECORDING LIVE
              </span>
            </div>
          )}

          {/* GPU 상태 모니터 미니 위젯 */}
          <div className="glass-panel" style={{
            padding: '6px 14px',
            borderRadius: '9999px',
            fontSize: '0.8rem',
            display: 'flex',
            alignItems: 'center',
            gap: '8px',
            border: '1px solid rgba(20, 184, 166, 0.25)',
            boxShadow: '0 0 10px rgba(20, 184, 166, 0.1)'
          }}>
            <span className="pulsing-dot" style={{
              width: '8px',
              height: '8px',
              borderRadius: '50%',
              backgroundColor: 'var(--color-accent)',
              display: 'inline-block'
            }}></span>
            <span style={{ color: 'var(--text-primary)' }}>
              ON-PREMISE GPU: <strong style={{ color: 'white' }}>RTX 3060 12GB</strong>
            </span>
          </div>
        </div>
      </div>
    </header>
  );
}
