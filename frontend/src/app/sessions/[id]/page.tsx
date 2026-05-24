'use client';

import { useEffect, useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  FileText, Play, Download, Trash2, Edit2, Check, X,
  Loader2, AlertCircle, Users, Clock, MessageSquare, ArrowLeft, Save
} from 'lucide-react';
import { SpeakerStatistics } from '@/components/SpeakerStatistics';

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

export default function SessionDetailPage() {
  const params = useParams();
  const router = useRouter();
  const sessionId = params.id as string;

  const [session, setSession] = useState<Session | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // 인라인 편집 상태
  const [editingSegmentId, setEditingSegmentId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<{ text: string; speaker: string }>({ text: '', speaker: '' });
  const [savingSegmentId, setSavingSegmentId] = useState<string | null>(null);

  // 세션 로딩 및 폴링 루프 (비즈니스 로직 보존)
  useEffect(() => {
    let timerId: NodeJS.Timeout;
    let attemptCount = 0;
    const maxAttempts = 600; // 최대 30분 폴링 (3초 × 600)

    const fetchSession = async () => {
      if (!sessionId || sessionId.trim().length === 0) {
        setError('유효하지 않은 세션 ID입니다.');
        setLoading(false);
        return;
      }

      attemptCount++;

      try {
        const host = window.location.hostname;
        const response = await fetch(`http://${host}:8000/api/v1/sessions/${sessionId}`);

        if (!response.ok) {
          if (response.status === 404) {
            setError('세션을 찾을 수 없습니다. 세션 ID가 올바른지 확인하세요.');
            setLoading(false);
            return;
          }
          const errorText = await response.text();
          throw new Error(`HTTP ${response.status}: ${errorText}`);
        }

        const data: Session = await response.json();

        if (!data.session_id) {
          throw new Error('올바르지 않은 세션 데이터 형식입니다.');
        }

        setSession(data);
        setError(null);
        setLoading(false);

        // 여전히 처리 중일 경우 재귀 폴링
        if (data.status === 'processing' && attemptCount < maxAttempts) {
          timerId = setTimeout(fetchSession, 3000);
        } else if (data.status === 'processing' && attemptCount >= maxAttempts) {
          setError('회의록 분석 처리 시간이 초과되었습니다.');
        }
      } catch (err: any) {
        console.error('❌ Failed to fetch session:', err);

        if (err instanceof TypeError && err.message.includes('fetch')) {
          if (attemptCount < maxAttempts) {
            timerId = setTimeout(fetchSession, 5000);
            return;
          }
        }

        setError(err.message || '회의 정보를 가져오는 중 오류가 발생했습니다.');
        setLoading(false);
      }
    };

    fetchSession();

    return () => {
      if (timerId) clearTimeout(timerId);
    };
  }, [sessionId]);

  // 편집 모드 시작
  const startEditSegment = (seg: Segment) => {
    setEditingSegmentId(seg.id);
    setEditForm({ text: seg.text, speaker: seg.speaker });
  };

  const cancelEdit = () => {
    setEditingSegmentId(null);
  };

  // 세그먼트 동적 업데이트
  const saveEditSegment = async (segmentId: string) => {
    setSavingSegmentId(segmentId);
    try {
      const host = window.location.hostname;
      const response = await fetch(`http://${host}:8000/api/v1/sessions/${sessionId}/segments/${segmentId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm),
      });

      if (!response.ok) {
        throw new Error('자막 내용 수정 반영에 실패했습니다.');
      }

      setSession((prev) => {
        if (!prev) return null;
        const updated = prev.segments.map((seg) => {
          if (seg.id === segmentId) {
            return { ...seg, text: editForm.text, speaker: editForm.speaker };
          }
          return seg;
        });
        
        const speakers = new Set(updated.map(s => s.speaker));
        return { ...prev, segments: updated, speaker_count: speakers.size };
      });

      setEditingSegmentId(null);
    } catch (err: any) {
      alert(err.message || '수정 도중 오류가 발생했습니다.');
    } finally {
      setSavingSegmentId(null);
    }
  };

  // 내보내기 호출
  const handleExport = (format: 'srt' | 'txt' | 'json' | 'docx') => {
    const host = window.location.hostname;
    window.location.href = `http://${host}:8000/api/v1/sessions/${sessionId}/export?format=${format}`;
  };

  // 세션 데이터 파기
  const handleDelete = async () => {
    if (!confirm('정말로 이 회의록 기록을 완벽하게 파기하시겠습니까? (영구 삭제됩니다)')) return;

    try {
      const host = window.location.hostname;
      const response = await fetch(`http://${host}:8000/api/v1/sessions/${sessionId}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        router.push('/sessions');
      } else {
        throw new Error('삭제 처리에 실패했습니다.');
      }
    } catch (err: any) {
      alert(err.message);
    }
  };

  // 로딩 상태 화면
  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '60vh', gap: '20px' }}>
        <Loader2 className="spin" size={48} style={{ animation: 'spin 1.5s linear infinite', color: 'var(--color-primary)' }} />
        <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>회의 정보 분석 내용을 로드하는 중입니다...</p>
      </div>
    );
  }

  // 에러 발생 및 빈 세션 상태
  if (error || !session) {
    return (
      <div className="glass-panel" style={{ padding: '40px', maxWidth: '600px', margin: '40px auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '20px' }}>
        <AlertCircle size={48} color="var(--color-danger)" />
        <h2 style={{ fontSize: '1.5rem', fontWeight: 700 }}>회의 정보를 불러올 수 없습니다.</h2>
        <p style={{ color: 'var(--text-secondary)' }}>{error || '세션이 만료되었거나 리소스가 서버에 존재하지 않습니다.'}</p>
        <button onClick={() => router.push('/sessions')} className="btn btn-secondary" style={{ borderRadius: '9999px', padding: '10px 24px' }}>
          보관소 아카이브로 이동
        </button>
      </div>
    );
  }

  // 처리 대기중 스크린
  if (session.status === 'processing') {
    return (
      <div className="glass-panel" style={{ padding: '60px 40px', maxWidth: '640px', margin: '60px auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '28px' }}>
        <Loader2 className="spin" size={60} style={{ animation: 'spin 2s linear infinite', color: 'var(--color-secondary)' }} />
        <div>
          <h2 style={{ fontSize: '1.75rem', marginBottom: '8px', fontWeight: 800 }}>오디오 일괄 분석 진행 중</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem', lineHeight: '1.5' }}>
            온프레미스 GPU 서버(RTX 3060)에서 전사 알고리즘과 Pyannote 화자 분리 연산을 수행하고 있습니다.
          </p>
        </div>
        
        <div className="glass-panel" style={{ width: '100%', padding: '16px', background: 'rgba(255,255,255,0.015)', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          용량에 따라 수 분이 소요될 수 있습니다. 완료 시 상세 회의록 편집기로 자동 리다이렉션됩니다.
        </div>
        
        <button onClick={() => router.push('/sessions')} className="btn btn-secondary" style={{ width: '100%', borderRadius: 'var(--radius-sm)' }}>
          보관 목록으로 나가기 (작업은 서버 백그라운드에서 지속됩니다)
        </button>
        <style jsx global>{`
          @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
          }
        `}</style>
      </div>
    );
  }

  // 변환 실패 상태 스크린
  if (session.status === 'failed') {
    return (
      <div className="glass-panel" style={{ padding: '40px', maxWidth: '600px', margin: '40px auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '20px' }}>
        <AlertCircle size={48} color="var(--color-danger)" />
        <h2 style={{ fontSize: '1.5rem', color: '#fca5a5', fontWeight: 700 }}>회의록 변환 실패</h2>
        <div style={{ padding: '16px', background: 'rgba(239, 68, 68, 0.05)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(239,68,68,0.2)', width: '100%', textAlign: 'left' }}>
          <p style={{ fontSize: '0.85rem', fontFamily: 'monospace', color: '#fca5a5', wordBreak: 'break-all' }}>
            {session.error_message || '알 수 없는 GPU OOM 메모리 예외 혹은 파일 변환 예외가 발생했습니다.'}
          </p>
        </div>
        <button onClick={() => router.push('/upload')} className="btn btn-primary" style={{ padding: '10px 24px', borderRadius: '9999px' }}>
          다른 파일 업로드 시도
        </button>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
      
      {/* 뒤로 가기 보관소 링크 */}
      <div>
        <Link href="/sessions" style={{ textDecoration: 'none', display: 'inline-flex', alignItems: 'center', gap: '8px', color: 'var(--text-secondary)', fontSize: '0.9rem', fontWeight: 600 }} className="nav-link">
          <ArrowLeft size={16} />
          보관 목록으로 이동
        </Link>
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: '30px' }} style={{ contentVisibility: 'auto' }}>
        
        {/* 좌측: 요약 및 다운로드 패널 */}
        <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
          
          {/* 회의 기본 데이터 */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
            <div>
              <span className="gradient-text" style={{ fontSize: '0.8rem', fontWeight: 700, textTransform: 'uppercase' }}>
                Session Metrics
              </span>
              <h2 style={{ fontSize: '1.35rem', marginTop: '4px', wordBreak: 'break-all', fontWeight: 800 }}>회의 결과 보고</h2>
            </div>

            <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', borderTop: '1px solid var(--border-light)', paddingTop: '16px' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <Clock size={16} color="var(--color-primary)" />
                <div style={{ fontSize: '0.9rem' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>총 시간 길이</div>
                  <strong style={{ color: 'white' }}>{Math.floor(session.duration_sec / 60)}분 {Math.round(session.duration_sec % 60)}초</strong>
                </div>
              </div>
              
              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <Users size={16} color="var(--color-secondary)" />
                <div style={{ fontSize: '0.9rem' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>분석 화자 수</div>
                  <strong style={{ color: 'white' }}>{session.speaker_count}명</strong>
                </div>
              </div>

              <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
                <MessageSquare size={16} color="var(--color-accent)" />
                <div style={{ fontSize: '0.9rem' }}>
                  <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>총 발화 개수</div>
                  <strong style={{ color: 'white' }}>{session.segments.length} 문장</strong>
                </div>
              </div>
            </div>
          </div>

          {/* 파일 포맷별 다운로드 */}
          <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
            <h3 style={{ fontSize: '1rem', fontWeight: 700 }}>회의록 다운로드</h3>
            
            <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
              <button onClick={() => handleExport('docx')} className="btn btn-primary" style={{ justifyContent: 'flex-start', borderRadius: 'var(--radius-sm)' }}>
                <FileText size={16} />
                Word 문서 (DOCX) 내보내기
              </button>
              <button onClick={() => handleExport('srt')} className="btn btn-secondary" style={{ justifyContent: 'flex-start', borderRadius: 'var(--radius-sm)' }}>
                <Download size={16} />
                자막 파일 (SRT) 다운로드
              </button>
              <button onClick={() => handleExport('txt')} className="btn btn-secondary" style={{ justifyContent: 'flex-start', borderRadius: 'var(--radius-sm)' }}>
                <FileText size={16} />
                텍스트 파일 (TXT) 다운로드
              </button>
              <button onClick={() => handleExport('json')} className="btn btn-secondary" style={{ justifyContent: 'flex-start', borderRadius: 'var(--radius-sm)' }}>
                <Download size={16} />
                구조화 원본 (JSON) 다운로드
              </button>
            </div>
          </div>

          {/* 파기 버튼 */}
          <button onClick={handleDelete} className="btn btn-danger" style={{ width: '100%', padding: '14px', borderRadius: 'var(--radius-sm)' }}>
            <Trash2 size={16} />
            회의록 데이터 영구 파기
          </button>
        </div>

        {/* 우측: 타임라인 에디터 및 화자 비율 */}
        <div className="glass-panel" style={{ padding: '30px', display: 'flex', flexDirection: 'column', gap: '30px', height: 'calc(100vh - 200px)', overflowY: 'auto' }}>
          
          {/* 타이틀 */}
          <div style={{ borderBottom: '1px solid var(--border-light)', paddingBottom: '20px' }}>
            <h2 style={{ fontSize: '1.65rem', fontWeight: 800 }}>대화 타임라인 편집기</h2>
            <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
              각 타임라인 블록의 화자 구분 라벨과 전사 텍스트를 검수 및 수정할 수 있습니다.
            </p>
          </div>

          {/* 화자 통계 패널 연동 */}
          {session.segments && session.segments.length > 0 ? (
            <div style={{ paddingBottom: '10px', borderBottom: '1px solid var(--border-light)' }}>
              <SpeakerStatistics segments={session.segments} />
            </div>
          ) : (
            <div style={{ padding: '30px', textAlign: 'center', background: 'rgba(255,255,255,0.01)', border: '1px solid var(--border-light)', borderRadius: 'var(--radius-sm)' }}>
              <AlertCircle size={28} style={{ margin: '0 auto 10px', opacity: 0.4 }} />
              <p style={{ color: 'var(--text-secondary)', fontSize: '0.85rem' }}>자막 구간 정보가 비어 있습니다.</p>
            </div>
          )}

          {/* 타임라인 메신저 스타일 챗 */}
          <div className="chat-bubble-container" style={{ padding: '10px 0' }}>
            {session.segments.length === 0 ? (
              <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '40px' }}>
                회의록에 수록된 유효한 음성 문장이 없습니다.
              </p>
            ) : (
              session.segments.map((seg) => {
                const spkIndex = parseInt(seg.speaker.replace(/[^0-9]/g, '')) % 4 || 0;
                const badgeClass = `speaker-badge spk-${spkIndex}`;
                const isEditing = editingSegmentId === seg.id;
                const isSaving = savingSegmentId === seg.id;

                return (
                  <div key={seg.id} className="chat-row" style={{
                    width: '100%',
                    maxWidth: '100%',
                    padding: '16px',
                    background: isEditing ? 'rgba(99,102,241,0.04)' : 'rgba(255,255,255,0.005)',
                    border: isEditing ? '1px solid rgba(99,102,241,0.3)' : '1px solid var(--border-light)',
                    borderRadius: 'var(--radius-sm)',
                    boxShadow: isEditing ? 'var(--shadow-glow)' : 'none',
                    transition: 'all 0.25s ease',
                    display: 'flex',
                    gap: '20px'
                  }}>
                    
                    {/* 화자 배지 및 시간축 */}
                    <div style={{ minWidth: '130px', display: 'flex', flexDirection: 'column', gap: '8px' }}>
                      {isEditing ? (
                        <input
                          type="text"
                          value={editForm.speaker}
                          onChange={(e) => setEditForm({ ...editForm, speaker: e.target.value })}
                          style={{
                            width: '100%',
                            padding: '6px 10px',
                            background: 'rgba(0,0,0,0.4)',
                            border: '1px solid var(--border-hover)',
                            borderRadius: '4px',
                            color: 'white',
                            fontSize: '0.85rem',
                            fontWeight: 'bold'
                          }}
                        />
                      ) : (
                        <span className={badgeClass} style={{ alignSelf: 'flex-start' }}>{seg.speaker}</span>
                      )}
                      
                      <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 600 }}>
                        {Math.floor(seg.start / 60)}:{(seg.start % 60).toFixed(0).padStart(2, '0')} ~ 
                        {Math.floor(seg.end / 60)}:{(seg.end % 60).toFixed(0).padStart(2, '0')}
                      </span>
                    </div>

                    {/* 전사 내용 본문 */}
                    <div style={{ flex: 1 }}>
                      {isEditing ? (
                        <textarea
                          value={editForm.text}
                          onChange={(e) => setEditForm({ ...editForm, text: e.target.value })}
                          style={{
                            width: '100%',
                            minHeight: '70px',
                            padding: '12px',
                            background: 'rgba(0,0,0,0.4)',
                            border: '1px solid var(--border-hover)',
                            borderRadius: '4px',
                            color: 'white',
                            fontSize: '0.95rem',
                            lineHeight: '1.5',
                            fontFamily: 'inherit'
                          }}
                        />
                      ) : (
                        <p style={{ fontSize: '1rem', color: 'white', lineHeight: '1.6', fontWeight: 500 }}>
                          {seg.text}
                        </p>
                      )}
                    </div>

                    {/* 액션 컨트롤러 */}
                    <div style={{ display: 'flex', gap: '8px', alignSelf: 'center' }}>
                      {isEditing ? (
                        <>
                          <button 
                            onClick={() => saveEditSegment(seg.id)} 
                            className="btn" 
                            disabled={isSaving}
                            style={{ 
                              padding: '8px 14px', 
                              background: 'rgba(20, 184, 166, 0.1)', 
                              color: '#2dd4bf', 
                              borderColor: 'rgba(20, 184, 166, 0.25)',
                              borderRadius: '4px'
                            }}
                          >
                            {isSaving ? (
                              <Loader2 className="spin" size={14} style={{ animation: 'spin 1.5s linear infinite' }} />
                            ) : (
                              <Check size={14} />
                            )}
                          </button>
                          
                          <button 
                            onClick={cancelEdit} 
                            className="btn" 
                            disabled={isSaving}
                            style={{ 
                              padding: '8px 14px', 
                              background: 'rgba(239, 68, 68, 0.1)', 
                              color: '#fca5a5', 
                              borderColor: 'rgba(239, 68, 68, 0.25)',
                              borderRadius: '4px'
                            }}
                          >
                            <X size={14} />
                          </button>
                        </>
                      ) : (
                        <button 
                          onClick={() => startEditSegment(seg)} 
                          className="btn" 
                          style={{ 
                            padding: '8px 14px', 
                            background: 'rgba(255,255,255,0.03)', 
                            color: 'var(--text-secondary)', 
                            borderColor: 'var(--border-light)',
                            borderRadius: '4px'
                          }}
                        >
                          <Edit2 size={14} />
                        </button>
                      )}
                    </div>
                  </div>
                );
              })
            )}
          </div>
        </div>
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
