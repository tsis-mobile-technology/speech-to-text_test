'use client';

import { useEffect, useState, useRef } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  FileText, Play, Download, Trash2, Edit2, Check, X,
  Loader2, AlertCircle, Users, Clock, MessageSquare
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
  
  // 인라인 수정 모드 상태
  const [editingSegmentId, setEditingSegmentId] = useState<string | null>(null);
  const [editForm, setEditForm] = useState<{ text: string; speaker: string }>({ text: '', speaker: '' });

  // 세션 정보 로딩 (폴링 지원)
  useEffect(() => {
    let timerId: NodeJS.Timeout;
    
    const fetchSession = async () => {
      try {
        const host = window.location.hostname;
        const response = await fetch(`http://${host}:8000/api/v1/sessions/${sessionId}`);
        
        if (!response.ok) {
          throw new Error('회의 세션을 가져오는데 실패했습니다.');
        }

        const data: Session = await response.json();
        setSession(data);
        setLoading(false);

        // 변환 분석 중일 경우 3초마다 계속 폴링
        if (data.status === 'processing') {
          timerId = setTimeout(fetchSession, 3000);
        }
      } catch (err: any) {
        console.error(err);
        setError(err.message || '데이터를 가져오는 도중 오류가 발생했습니다.');
        setLoading(false);
      }
    };

    fetchSession();

    return () => {
      if (timerId) clearTimeout(timerId);
    };
  }, [sessionId]);

  // 자막 수정 모드 활성화
  const startEditSegment = (seg: Segment) => {
    setEditingSegmentId(seg.id);
    setEditForm({ text: seg.text, speaker: seg.speaker });
  };

  // 자막 수정 취소
  const cancelEdit = () => {
    setEditingSegmentId(null);
  };

  // 자막 수정 제출 (백엔드 PUT API 연동)
  const saveEditSegment = async (segmentId: string) => {
    try {
      const host = window.location.hostname;
      const response = await fetch(`http://${host}:8000/api/v1/sessions/${sessionId}/segments/${segmentId}`, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(editForm),
      });

      if (!response.ok) {
        throw new Error('자막 수정 동기화에 실패했습니다.');
      }

      // 로컬 상태 동적으로 교체
      setSession((prev) => {
        if (!prev) return null;
        const updated = prev.segments.map((seg) => {
          if (seg.id === segmentId) {
            return { ...seg, text: editForm.text, speaker: editForm.speaker };
          }
          return seg;
        });
        
        // 고유 화자수 재연산
        const spks = new Set(updated.map(s => s.speaker));
        return { ...prev, segments: updated, speaker_count: spks.size };
      });

      setEditingSegmentId(null);
    } catch (err: any) {
      alert(err.message || '수정 중 에러가 발생했습니다.');
    }
  };

  // 파일로 다운로드 내보내기 호출
  const handleExport = (format: 'srt' | 'txt' | 'json') => {
    const host = window.location.hostname;
    window.location.href = `http://${host}:8000/api/v1/sessions/${sessionId}/export?format=${format}`;
  };

  // 세션 삭제
  const handleDelete = async () => {
    if (!confirm('정말로 이 회의록 기록을 삭제하시겠습니까? (복구할 수 없습니다)')) return;

    try {
      const host = window.location.hostname;
      const response = await fetch(`http://${host}:8000/api/v1/sessions/${sessionId}`, {
        method: 'DELETE',
      });

      if (response.ok) {
        router.push('/');
      } else {
        throw new Error('삭제 요청에 실패했습니다.');
      }
    } catch (err: any) {
      alert(err.message);
    }
  };

  if (loading) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', justifyContent: 'center', height: '60vh', gap: '20px' }}>
        <Loader2 className="spin" size={48} style={{ animation: 'spin 1.5s linear infinite', color: 'var(--color-primary)' }} />
        <p style={{ color: 'var(--text-secondary)' }}>회의 정보를 불러오는 중입니다...</p>
      </div>
    );
  }

  if (error || !session) {
    return (
      <div className="glass-panel" style={{ padding: '40px', maxWidth: '600px', margin: '0 auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '20px' }}>
        <AlertCircle size={48} color="#ef4444" />
        <h2 style={{ fontSize: '1.5rem' }}>회의를 조회할 수 없습니다.</h2>
        <p style={{ color: 'var(--text-secondary)' }}>{error || '세션이 만료되었거나 캐시에 존재하지 않는 세션입니다.'}</p>
        <button onClick={() => router.push('/')} className="btn btn-secondary">
          메인 페이지로 이동
        </button>
      </div>
    );
  }

  // 처리 중 대기 화면
  if (session.status === 'processing') {
    return (
      <div className="glass-panel" style={{ padding: '60px 40px', maxWidth: '640px', margin: '60px auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '28px' }}>
        <Loader2 className="spin" size={60} style={{ animation: 'spin 2s linear infinite', color: 'var(--color-secondary)' }} />
        <div>
          <h2 style={{ fontSize: '1.75rem', marginBottom: '8px' }}>한국어 음성 분석 진행 중</h2>
          <p style={{ color: 'var(--text-secondary)', fontSize: '0.95rem' }}>
            서버 GPU(RTX 3060)에서 전사 및 화자 분리 연산을 수행하고 있습니다.
          </p>
        </div>
        
        <div style={{ width: '100%', padding: '16px', background: 'rgba(255,255,255,0.02)', border: '1px solid var(--border-light)', borderRadius: 'var(--radius-sm)', fontSize: '0.85rem', color: 'var(--text-muted)' }}>
          몇 분 소요될 수 있습니다. 본 화면은 결과를 받기 위해 자동으로 실시간 대기(Polling)합니다.
        </div>
        
        <button onClick={() => router.push('/')} className="btn btn-secondary" style={{ width: '100%' }}>
          회의 목록으로 나가기 (작업은 백그라운드에서 유지됩니다)
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

  // 실패 처리 화면
  if (session.status === 'failed') {
    return (
      <div className="glass-panel" style={{ padding: '40px', maxWidth: '600px', margin: '40px auto', textAlign: 'center', display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '20px' }}>
        <AlertCircle size={48} color="#ef4444" />
        <h2 style={{ fontSize: '1.5rem', color: '#fca5a5' }}>회의록 변환 실패</h2>
        <div style={{ padding: '16px', background: 'rgba(239, 68, 68, 0.05)', borderRadius: 'var(--radius-sm)', border: '1px solid rgba(239,68,68,0.2)', width: '100%', textAlign: 'left' }}>
          <p style={{ fontSize: '0.85rem', fontFamily: 'monospace', color: '#fca5a5', wordBreak: 'break-all' }}>
            {session.error_message || '알 수 없는 OOM 또는 런타임 오류가 발생했습니다.'}
          </p>
        </div>
        <button onClick={() => router.push('/upload')} className="btn btn-primary">
          재시도하기
        </button>
      </div>
    );
  }

  // 완료 화면
  return (
    <div style={{ display: 'grid', gridTemplateColumns: '340px 1fr', gap: '30px' }}>
      
      {/* 좌측 패널: 메타데이터 및 도구 */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: '20px' }}>
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '20px' }}>
          <div>
            <span className="gradient-text" style={{ fontSize: '0.8rem', fontWeight: 700, textTransform: 'uppercase' }}>
              Completed Session
            </span>
            <h2 style={{ fontSize: '1.35rem', marginTop: '4px', wordBreak: 'break-all' }}>회의 결과 요약</h2>
          </div>

          <div style={{ display: 'flex', flexDirection: 'column', gap: '14px', borderTop: '1px solid var(--border-light)', paddingTop: '16px' }}>
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Clock size={16} color="var(--color-primary)" />
              <div style={{ fontSize: '0.9rem' }}>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>오디오 녹음 길이</div>
                <strong>{Math.floor(session.duration_sec / 60)}분 {Math.round(session.duration_sec % 60)}초</strong>
              </div>
            </div>
            
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <Users size={16} color="var(--color-secondary)" />
              <div style={{ fontSize: '0.9rem' }}>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>참석 화자 수</div>
                <strong>{session.speaker_count}명</strong>
              </div>
            </div>

            <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
              <MessageSquare size={16} color="var(--color-accent)" />
              <div style={{ fontSize: '0.9rem' }}>
                <div style={{ color: 'var(--text-secondary)', fontSize: '0.75rem' }}>총 발화 문장수</div>
                <strong>{session.segments.length}개</strong>
              </div>
            </div>
          </div>
        </div>

        {/* 내보내기 다운로드 패널 */}
        <div className="glass-panel" style={{ padding: '24px', display: 'flex', flexDirection: 'column', gap: '16px' }}>
          <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>결과물 내보내기</h3>
          
          <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
            <button onClick={() => handleExport('srt')} className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}>
              <Download size={16} />
              자막 파일 (SRT) 다운로드
            </button>
            <button onClick={() => handleExport('txt')} className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}>
              <FileText size={16} />
              텍스트 문서 (TXT) 다운로드
            </button>
            <button onClick={() => handleExport('json')} className="btn btn-secondary" style={{ justifyContent: 'flex-start' }}>
              <Download size={16} />
              원본 결과 (JSON) 다운로드
            </button>
          </div>
        </div>

        {/* 세션 파괴(삭제) */}
        <button onClick={handleDelete} className="btn btn-danger" style={{ width: '100%' }}>
          <Trash2 size={16} />
          회의록 데이터 파기
        </button>
      </div>

      {/* 우측 패널: 타임라인 에디터 */}
      <div className="glass-panel" style={{ padding: '30px', display: 'flex', flexDirection: 'column', gap: '30px', height: 'calc(100vh - 180px)', overflowY: 'auto' }}>
        <div style={{ borderBottom: '1px solid var(--border-light)', paddingBottom: '20px' }}>
          <h2 style={{ fontSize: '1.5rem', fontWeight: 700 }}>대화 타임라인 편집기</h2>
          <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
            시간대별 자막 내용과 화자명을 수정하여 보정할 수 있습니다.
          </p>
        </div>

        {/* 화자 통계 패널 */}
        {session.segments.length > 0 && (
          <div style={{ paddingBottom: '20px', borderBottom: '1px solid var(--border-light)' }}>
            <SpeakerStatistics segments={session.segments} />
          </div>
        )}

        <div style={{ display: 'flex', flexDirection: 'column', gap: '24px' }}>
          {session.segments.length === 0 ? (
            <p style={{ color: 'var(--text-muted)', textAlign: 'center', padding: '40px' }}>
              회의록에서 감지된 음성 문장이 없습니다.
            </p>
          ) : (
            session.segments.map((seg) => {
              const spkIndex = parseInt(seg.speaker.replace(/[^0-9]/g, '')) % 4 || 0;
              const badgeClass = `speaker-badge spk-${spkIndex}`;
              const isEditing = editingSegmentId === seg.id;

              return (
                <div key={seg.id} style={{
                  display: 'flex',
                  gap: '16px',
                  padding: '16px',
                  background: isEditing ? 'rgba(99,102,241,0.03)' : 'transparent',
                  border: isEditing ? '1px solid var(--border-hover)' : '1px solid transparent',
                  borderRadius: 'var(--radius-sm)',
                  transition: 'all 0.2s ease'
                }}>
                  {/* 화자 버블 및 정보 영역 */}
                  <div style={{ minWidth: '120px', display: 'flex', flexDirection: 'column', gap: '6px' }}>
                    {isEditing ? (
                      <input
                        type="text"
                        value={editForm.speaker}
                        onChange={(e) => setEditForm({ ...editForm, speaker: e.target.value })}
                        style={{
                          width: '100%',
                          padding: '4px 8px',
                          background: 'rgba(0,0,0,0.5)',
                          border: '1px solid var(--border-hover)',
                          borderRadius: '4px',
                          color: 'white',
                          fontSize: '0.8rem',
                          fontWeight: 'bold'
                        }}
                      />
                    ) : (
                      <span className={badgeClass}>{seg.speaker}</span>
                    )}
                    <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                      {Math.floor(seg.start / 60)}:{(seg.start % 60).toFixed(0).padStart(2, '0')} ~ 
                      {Math.floor(seg.end / 60)}:{(seg.end % 60).toFixed(0).padStart(2, '0')}
                    </span>
                  </div>

                  {/* 텍스트 내용 에디터 본문 */}
                  <div style={{ flex: 1 }}>
                    {isEditing ? (
                      <textarea
                        value={editForm.text}
                        onChange={(e) => setEditForm({ ...editForm, text: e.target.value })}
                        style={{
                          width: '100%',
                          minHeight: '60px',
                          padding: '10px',
                          background: 'rgba(0,0,0,0.5)',
                          border: '1px solid var(--border-hover)',
                          borderRadius: '4px',
                          color: 'white',
                          fontSize: '0.95rem',
                          fontFamily: 'var(--font-sans)',
                          lineHeight: '1.5'
                        }}
                      />
                    ) : (
                      <p style={{ fontSize: '1rem', color: 'var(--text-primary)', lineHeight: '1.6' }}>
                        {seg.text}
                      </p>
                    )}
                  </div>

                  {/* 액션 컨트롤러 버튼 */}
                  <div style={{ display: 'flex', gap: '8px', alignSelf: 'flex-start' }}>
                    {isEditing ? (
                      <>
                        <button onClick={() => saveEditSegment(seg.id)} className="btn" style={{ padding: '6px 12px', background: 'rgba(20, 184, 166, 0.1)', color: '#2dd4bf', borderColor: 'rgba(20, 184, 166, 0.2)' }}>
                          <Check size={14} />
                        </button>
                        <button onClick={cancelEdit} className="btn" style={{ padding: '6px 12px', background: 'rgba(239, 68, 68, 0.1)', color: '#fca5a5', borderColor: 'rgba(239, 68, 68, 0.2)' }}>
                          <X size={14} />
                        </button>
                      </>
                    ) : (
                      <button onClick={() => startEditSegment(seg)} className="btn" style={{ padding: '6px 12px', background: 'rgba(255,255,255,0.03)', color: 'var(--text-secondary)', borderColor: 'var(--border-light)' }}>
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
  );
}
