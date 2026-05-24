'use client';

import { useState } from 'react';
import { Download, FileText, Music, Code } from 'lucide-react';
import { exportSession } from '@/lib/exportService';

interface ExportPanelProps {
  sessionId: string;
  segments: Array<{
    id: string;
    start: number;
    end: number;
    text: string;
    speaker: string;
    confidence: number;
    is_final: boolean;
  }>;
  speakerCount: number;
  durationSec: number;
}

/**
 * 회의 기록을 다양한 형식으로 내보내기할 수 있는 패널
 * - SRT (자막 파일)
 * - TXT (일반 텍스트)
 * - JSON (구조화된 데이터)
 * - DOCX (Word 문서) - 서버에서 처리
 */
export function ExportPanel({
  sessionId,
  segments,
  speakerCount,
  durationSec,
}: ExportPanelProps) {
  const [isExporting, setIsExporting] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const handleExport = async (format: 'srt' | 'txt' | 'json' | 'docx') => {
    setIsExporting(format);
    setError(null);

    try {
      const sessionData = {
        session_id: sessionId,
        segments,
        speaker_count: speakerCount,
        duration_sec: durationSec,
        created_at: new Date().toISOString(),
      };

      if (format === 'docx') {
        // DOCX는 서버에서 생성
        const response = await fetch(
          `http://localhost:8000/api/v1/sessions/${sessionId}/export?format=docx`
        );

        if (!response.ok) {
          throw new Error(`HTTP ${response.status}`);
        }

        const blob = await response.blob();
        const url = URL.createObjectURL(blob);
        const link = document.createElement('a');
        link.href = url;
        link.download = `meeting_${new Date().toISOString().split('T')[0]}.docx`;
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
        URL.revokeObjectURL(url);
      } else {
        // 클라이언트 측에서 생성
        exportSession(sessionData, format);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '내보내기 실패');
    } finally {
      setIsExporting(null);
    }
  };

  const exportFormats = [
    {
      id: 'srt',
      name: 'SRT',
      desc: '자막 파일',
      icon: Music,
      color: '#6366f1',
    },
    {
      id: 'txt',
      name: 'TXT',
      desc: '텍스트',
      icon: FileText,
      color: '#f59e0b',
    },
    {
      id: 'json',
      name: 'JSON',
      desc: '데이터',
      icon: Code,
      color: '#10b981',
    },
    {
      id: 'docx',
      name: 'DOCX',
      desc: 'Word',
      icon: FileText,
      color: '#3b82f6',
    },
  ];

  return (
    <div
      style={{
        padding: '20px',
        borderRadius: '12px',
        backgroundColor: 'rgba(99, 102, 241, 0.05)',
        border: '1px solid rgba(99, 102, 241, 0.2)',
      }}
    >
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px', marginBottom: '16px' }}>
        <Download size={18} style={{ color: '#6366f1' }} />
        <h3 style={{ fontSize: '1rem', margin: 0 }}>내보내기</h3>
      </div>

      {/* 에러 메시지 */}
      {error && (
        <div
          style={{
            padding: '10px',
            marginBottom: '12px',
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            borderRadius: '6px',
            fontSize: '0.85rem',
            color: '#ef4444',
          }}
        >
          {error}
        </div>
      )}

      {/* 포맷 버튼 그리드 */}
      <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: '10px' }}>
        {exportFormats.map((fmt) => {
          const Icon = fmt.icon;
          const isLoading = isExporting === fmt.id;

          return (
            <button
              key={fmt.id}
              onClick={() => handleExport(fmt.id as any)}
              disabled={isLoading || segments.length === 0}
              style={{
                padding: '12px 10px',
                borderRadius: '8px',
                border: '1px solid rgba(255, 255, 255, 0.1)',
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
                color: 'white',
                cursor: segments.length > 0 ? 'pointer' : 'not-allowed',
                transition: 'all 0.2s ease',
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                gap: '8px',
                fontSize: '0.85rem',
                fontWeight: 600,
                opacity: segments.length > 0 ? 1 : 0.5,
              }}
              onMouseEnter={(e) => {
                if (segments.length > 0) {
                  (e.currentTarget as HTMLButtonElement).style.backgroundColor = `${fmt.color}20`;
                  (e.currentTarget as HTMLButtonElement).style.borderColor = fmt.color;
                }
              }}
              onMouseLeave={(e) => {
                (e.currentTarget as HTMLButtonElement).style.backgroundColor = 'rgba(255, 255, 255, 0.05)';
                (e.currentTarget as HTMLButtonElement).style.borderColor = 'rgba(255, 255, 255, 0.1)';
              }}
            >
              <Icon size={16} />
              <span>{fmt.name}</span>
              {isLoading && <span style={{ marginLeft: '4px' }}>...</span>}
            </button>
          );
        })}
      </div>

      {/* 상태 정보 */}
      <div style={{ marginTop: '12px', fontSize: '0.75rem', color: 'var(--text-muted)' }}>
        <div style={{ marginBottom: '4px' }}>
          📊 {segments.length}개 발언
        </div>
        <div>
          👥 화자 {speakerCount}명 • ⏱️ {Math.round(durationSec / 60)}분
        </div>
      </div>
    </div>
  );
}
