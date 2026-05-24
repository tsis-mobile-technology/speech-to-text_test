'use client';

import { useEffect, useState, useMemo } from 'react';
import Link from 'next/link';
import { 
  Folder, Clock, Users, HardDrive, Cpu, 
  Trash2, ChevronRight, Search, Play, 
  AlertCircle, CheckCircle, RefreshCw, BarChart2
} from 'lucide-react';

interface Segment {
  id: string;
  start: number;
  end: number;
  text: string;
  speaker: string;
  confidence: number;
}

interface Session {
  session_id: string;
  status: 'processing' | 'completed' | 'failed';
  created_at: string;
  duration_sec: number;
  speaker_count: number;
  segments: Segment[];
  error_message?: string;
}

interface GpuStatus {
  vram_used_mb: number;
  vram_total_mb: number;
}

export default function SessionsDashboardPage() {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [gpuUsage, setGpuUsage] = useState<GpuStatus | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // 전체 세션 목록 로드
  const fetchDashboardData = async () => {
    try {
      const host = window.location.hostname;
      
      // 1. 세션 리스트 호출
      const response = await fetch(`http://${host}:8000/api/v1/sessions`);
      if (!response.ok) {
        throw new Error(`세션 목록을 읽어오는데 실패했습니다: HTTP ${response.status}`);
      }
      const sessionsData: Session[] = await response.json();
      setSessions(sessionsData);

      // 2. GPU 헬스 체크 호출
      const gpuResponse = await fetch(`http://${host}:8000/api/v1/health/gpu`);
      if (gpuResponse.ok) {
        const gpuData: GpuStatus = await gpuResponse.json();
        setGpuUsage(gpuData);
      }
      
      setError(null);
    } catch (err: any) {
      console.error('❌ Failed to fetch dashboard data:', err);
      setError(err.message || '데이터를 가져오는 중 오류가 발생했습니다.');
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchDashboardData();
    // 10초마다 대시보드 상태 자동 갱신
    const interval = setInterval(fetchDashboardData, 10000);
    return () => clearInterval(interval);
  }, []);

  // 세션 영구 삭제
  const handleDeleteSession = async (e: React.MouseEvent, sessionId: string) => {
    e.preventDefault(); // 링크 클릭 방지
    if (!confirm('정말로 이 회의록 기록을 완전히 삭제하시겠습니까?')) return;

    try {
      const host = window.location.hostname;
      const response = await fetch(`http://${host}:8000/api/v1/sessions/${sessionId}`, {
        method: 'DELETE'
      });

      if (!response.ok) {
        throw new Error('삭제 처리에 실패했습니다.');
      }

      // 상태 목록에서 즉각 제외
      setSessions(prev => prev.filter(s => s.session_id !== sessionId));
    } catch (err: any) {
      alert(err.message || '삭제 도중 에러가 발생했습니다.');
    }
  };

  // 대시보드 메트릭 계산
  const metrics = useMemo(() => {
    const total = sessions.length;
    const completed = sessions.filter(s => s.status === 'completed').length;
    const processing = sessions.filter(s => s.status === 'processing').length;
    const failed = sessions.filter(s => s.status === 'failed').length;
    
    // 총 누적 기록 시간
    const totalDuration = sessions
      .filter(s => s.status === 'completed')
      .reduce((acc, s) => acc + s.duration_sec, 0);

    return { total, completed, processing, failed, totalDuration };
  }, [sessions]);

  // 검색어 필터링
  const filteredSessions = useMemo(() => {
    if (!searchQuery.trim()) return sessions;
    const query = searchQuery.toLowerCase();
    return sessions.filter(s => 
      s.session_id.toLowerCase().includes(query) ||
      (s.segments && s.segments.some(seg => seg.text.toLowerCase().includes(query)))
    );
  }, [sessions, searchQuery]);

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '32px' }}>
      
      {/* 타이틀 헤더 */}
      <div>
        <span className="gradient-text" style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Dashboard & Archive
        </span>
        <h1 style={{ fontSize: '2.5rem', marginTop: '4px', fontWeight: 800 }}>기록물 보관소 및 시스템 대시보드</h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: '8px' }}>
          온프레미스 GPU 가속 현황을 실시간 파악하고, 지금까지 기록된 회의 보관록을 탐색 및 다운로드합니다.
        </p>
      </div>

      {/* 대시보드 요약 위젯 카드 그리드 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(220px, 1fr))', gap: '20px' }}>
        
        {/* 총 회의록 */}
        <div className="glass-panel metric-card">
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: 500 }}>총 누적 회의 건수</span>
            <Folder size={20} color="var(--color-primary)" />
          </div>
          <strong style={{ fontSize: '2rem', color: 'white', marginTop: '8px' }}>{metrics.total} 건</strong>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            완료: {metrics.completed} / 진행중: {metrics.processing}
          </span>
        </div>

        {/* 누적 시간 */}
        <div className="glass-panel metric-card" style={{ contentVisibility: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: 500 }}>총 오디오 처리 시간</span>
            <Clock size={20} color="var(--color-secondary)" />
          </div>
          <strong style={{ fontSize: '2rem', color: 'white', marginTop: '8px' }}>
            {Math.floor(metrics.totalDuration / 60)}분 {Math.round(metrics.totalDuration % 60)}초
          </strong>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            성공 완료 세션 기준 연산
          </span>
        </div>

        {/* GPU VRAM 사용 현황 */}
        <div className="glass-panel metric-card" style={{ contentVisibility: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: 500 }}>NVIDIA VRAM 가용률</span>
            <HardDrive size={20} color="var(--color-accent)" />
          </div>
          {gpuUsage ? (
            <>
              <strong style={{ fontSize: '2rem', color: 'white', marginTop: '8px' }}>
                {((gpuUsage.vram_used_mb / gpuUsage.vram_total_mb) * 100).toFixed(1)} %
              </strong>
              <div style={{ width: '100%', height: '4px', backgroundColor: 'rgba(255,255,255,0.05)', borderRadius: '2px', overflow: 'hidden', marginTop: '8px' }}>
                <div style={{
                  width: `${(gpuUsage.vram_used_mb / gpuUsage.vram_total_mb) * 100}%`,
                  height: '100%',
                  background: 'var(--gradient-neon)',
                }} />
              </div>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
                {gpuUsage.vram_used_mb}MB / {gpuUsage.vram_total_mb}MB 사용중
              </span>
            </>
          ) : (
            <>
              <strong style={{ fontSize: '1.5rem', color: 'var(--text-muted)', marginTop: '8px' }}>대기중</strong>
              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '16px' }}>GPU 상태를 로드할 수 없습니다.</span>
            </>
          )}
        </div>

        {/* 시스템 헬스 상태 */}
        <div className="glass-panel metric-card" style={{ contentVisibility: 'auto' }}>
          <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center' }}>
            <span style={{ color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: 500 }}>시스템 상태</span>
            <Cpu size={20} color={error ? 'var(--color-danger)' : 'var(--color-accent)'} />
          </div>
          <strong style={{ fontSize: '2rem', color: error ? '#fca5a5' : '#2dd4bf', marginTop: '8px' }}>
            {error ? '오류' : '정상 작동'}
          </strong>
          <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '4px' }}>
            {error ? 'API 서버 연결 불량' : 'FastAPI 백엔드 활성화'}
          </span>
        </div>
      </div>

      {/* 기록물 목록 & 검색 인터페이스 */}
      <div className="glass-panel" style={{ padding: '30px', display: 'flex', flexDirection: 'column', gap: '24px' }}>
        
        {/* 컨트롤 헤더 및 검색창 */}
        <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'center', gap: '20px', flexWrap: 'wrap' }}>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700 }}>회의 보관록 목록</h2>
          
          <div style={{ position: 'relative', width: '320px' }}>
            <Search size={18} style={{ position: 'absolute', left: '14px', top: '13px', color: 'var(--text-muted)' }} />
            <input 
              type="text" 
              placeholder="세션 ID 또는 텍스트 검색..."
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              style={{
                width: '100%',
                padding: '12px 16px 12px 42px',
                background: 'rgba(0,0,0,0.2)',
                border: '1px solid var(--border-light)',
                borderRadius: '9999px',
                color: 'white',
                fontSize: '0.9rem'
              }}
            />
          </div>
        </div>

        {/* 테이블 본문 */}
        {loading ? (
          <div style={{ display: 'flex', justifyContent: 'center', padding: '60px 0', gap: '12px' }}>
            <RefreshCw className="spin" size={24} style={{ animation: 'spin 1.5s linear infinite', color: 'var(--color-primary)' }} />
            <p style={{ color: 'var(--text-secondary)' }}>회의록 보관소 목록을 불러오는 중입니다...</p>
          </div>
        ) : filteredSessions.length === 0 ? (
          <div style={{ textAlign: 'center', padding: '60px 20px', color: 'var(--text-muted)' }}>
            <Folder size={48} style={{ margin: '0 auto 16px', opacity: 0.3 }} />
            <p style={{ fontSize: '1.1rem', fontWeight: 600 }}>보관된 회의록이 없습니다.</p>
            <p style={{ fontSize: '0.85rem', marginTop: '6px' }}>첫 번째 실시간 회의나 파일 변환을 완료해 주세요.</p>
            <div style={{ display: 'flex', gap: '12px', justifyContent: 'center', marginTop: '20px' }}>
              <Link href="/" className="btn btn-primary" style={{ padding: '8px 20px', fontSize: '0.85rem', borderRadius: '9999px' }}>
                실시간 회의 시작
              </Link>
              <Link href="/upload" className="btn btn-secondary" style={{ padding: '8px 20px', fontSize: '0.85rem', borderRadius: '9999px' }}>
                파일 업로드
              </Link>
            </div>
          </div>
        ) : (
          <div style={{ overflowX: 'auto' }}>
            <table className="glass-table">
              <thead>
                <tr>
                  <th>세션 ID</th>
                  <th>등록 일시</th>
                  <th>총 시간</th>
                  <th>화자 수</th>
                  <th>상태</th>
                  <th style={{ textAlign: 'right' }}>작업</th>
                </tr>
              </thead>
              <tbody>
                {filteredSessions.map((session) => {
                  const createdAtFormatted = new Date(session.created_at).toLocaleString('ko-KR', {
                    year: 'numeric',
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit'
                  });

                  return (
                    <tr key={session.session_id} style={{ position: 'relative' }}>
                      <td style={{ fontWeight: 600, fontFamily: 'monospace', letterSpacing: '-0.02em' }}>
                        <Link href={`/sessions/${session.session_id}`} style={{ color: 'white', textDecoration: 'none' }}>
                          {session.session_id.substring(0, 8)}...{session.session_id.substring(session.session_id.length - 8)}
                        </Link>
                      </td>
                      <td style={{ color: 'var(--text-secondary)' }}>{createdAtFormatted}</td>
                      <td>
                        {session.status === 'completed' 
                          ? `${Math.floor(session.duration_sec / 60)}분 ${Math.round(session.duration_sec % 60)}초`
                          : '-'
                        }
                      </td>
                      <td>
                        {session.status === 'completed' ? (
                          <span style={{ display: 'flex', alignItems: 'center', gap: '6px' }}>
                            <Users size={14} color="var(--text-muted)" />
                            {session.speaker_count} 명
                          </span>
                        ) : '-'}
                      </td>
                      <td>
                        {session.status === 'completed' && (
                          <span className="glass-panel" style={{
                            padding: '4px 10px',
                            borderRadius: '9999px',
                            fontSize: '0.75rem',
                            fontWeight: 700,
                            backgroundColor: 'rgba(20, 184, 166, 0.1)',
                            borderColor: 'rgba(20, 184, 166, 0.25)',
                            color: '#2dd4bf'
                          }}>
                            분석 완료
                          </span>
                        )}
                        {session.status === 'processing' && (
                          <span className="glass-panel" style={{
                            padding: '4px 10px',
                            borderRadius: '9999px',
                            fontSize: '0.75rem',
                            fontWeight: 700,
                            backgroundColor: 'rgba(168, 85, 247, 0.1)',
                            borderColor: 'rgba(168, 85, 247, 0.25)',
                            color: '#c084fc',
                            display: 'inline-flex',
                            alignItems: 'center',
                            gap: '6px'
                          }}>
                            <RefreshCw className="spin" size={12} style={{ animation: 'spin 1.5s linear infinite' }} />
                            처리중
                          </span>
                        )}
                        {session.status === 'failed' && (
                          <span className="glass-panel" style={{
                            padding: '4px 10px',
                            borderRadius: '9999px',
                            fontSize: '0.75rem',
                            fontWeight: 700,
                            backgroundColor: 'rgba(239, 68, 68, 0.1)',
                            borderColor: 'rgba(239, 68, 68, 0.25)',
                            color: '#fca5a5'
                          }}>
                            실패
                          </span>
                        )}
                      </td>
                      <td style={{ textAlign: 'right' }}>
                        <div style={{ display: 'inline-flex', gap: '8px' }}>
                          <Link href={`/sessions/${session.session_id}`} className="btn btn-secondary" style={{
                            padding: '6px 12px',
                            borderRadius: 'var(--radius-sm)',
                            fontSize: '0.8rem'
                          }}>
                            회의록 보기
                            <ChevronRight size={14} />
                          </Link>
                          
                          <button 
                            onClick={(e) => handleDeleteSession(e, session.session_id)} 
                            className="btn btn-danger" 
                            style={{
                              padding: '6px 10px',
                              borderRadius: 'var(--radius-sm)'
                            }}
                            title="데이터 파기"
                          >
                            <Trash2 size={14} />
                          </button>
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>

      <style jsx global>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
