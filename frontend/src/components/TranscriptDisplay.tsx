'use client';

import { useEffect, useRef } from 'react';

interface Segment {
  id: string;
  start: number;
  end: number;
  text: string;
  speaker: string;
  confidence: number;
  is_final: boolean;
}

interface TranscriptDisplayProps {
  segments: Segment[];
  partialSegment: Segment | null;
}

const SPEAKER_COLORS = [
  { bg: 'rgba(99, 102, 241, 0.2)', text: '#a5b4fc', name: 'Indigo' },      // spk-0
  { bg: 'rgba(168, 85, 247, 0.2)', text: '#d8b4fe', name: 'Purple' },       // spk-1
  { bg: 'rgba(236, 72, 153, 0.2)', text: '#f472b6', name: 'Pink' },         // spk-2
  { bg: 'rgba(249, 115, 22, 0.2)', text: '#fb923c', name: 'Orange' },       // spk-3
];

/**
 * 실시간 STT 결과를 시간 순서대로 표시하는 컴포넌트
 * - 확정된 세그먼트 (is_final=true)
 * - 부분 결과 (실시간 수신 중)
 * - 화자 배지, 타임스탐프, 신뢰도
 */
export function TranscriptDisplay({ segments, partialSegment }: TranscriptDisplayProps) {
  const transcriptEndRef = useRef<HTMLDivElement | null>(null);

  // 새 세그먼트 추가 시 자동 스크롤
  useEffect(() => {
    if (transcriptEndRef.current) {
      transcriptEndRef.current.scrollIntoView({ behavior: 'smooth' });
    }
  }, [segments, partialSegment]);

  const getColor = (speaker: string, fallback = true) => {
    if (!fallback) return null;
    const spkIndex = parseInt(speaker.replace(/[^0-9]/g, '')) % 4 || 0;
    return SPEAKER_COLORS[spkIndex];
  };

  const getConfidenceColor = (confidence: number) => {
    if (confidence >= 0.9) return '#10b981'; // green
    if (confidence >= 0.75) return '#f59e0b'; // amber
    return '#ef4444'; // red
  };

  return (
    <div
      style={{
        flex: 1,
        padding: '30px',
        overflowY: 'auto',
        display: 'flex',
        flexDirection: 'column',
        gap: '24px',
        maxHeight: 'calc(100vh - 380px)',
      }}
      className="glass-panel"
    >
      {segments.length === 0 && !partialSegment && (
        <div
          style={{
            flex: 1,
            display: 'flex',
            flexDirection: 'column',
            alignItems: 'center',
            justifyContent: 'center',
            color: 'var(--text-muted)',
            textAlign: 'center',
            padding: '40px',
          }}
        >
          <svg
            width="48"
            height="48"
            viewBox="0 0 24 24"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            style={{ marginBottom: '16px', opacity: 0.3 }}
          >
            <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z" />
            <path d="M19 10v2a7 7 0 0 1-14 0v-2" />
            <line x1="12" y1="19" x2="12" y2="23" />
            <line x1="8" y1="23" x2="16" y2="23" />
          </svg>
          <p style={{ fontSize: '1.1rem', fontWeight: 600 }}>회의 시작 버튼을 누르고 말씀해 주세요.</p>
          <p style={{ fontSize: '0.85rem', marginTop: '8px', color: 'var(--text-secondary)' }}>
            음성이 무음 VAD 필터를 거쳐 실시간으로 이곳에 표현됩니다.
          </p>
        </div>
      )}

      {/* 확정된 자막 목록 */}
      {segments.map((seg) => {
        const color = getColor(seg.speaker);
        const confidenceColor = getConfidenceColor(seg.confidence);

        return (
          <div
            key={seg.id}
            style={{
              display: 'flex',
              flexDirection: 'column',
              gap: '8px',
              padding: '12px',
              borderRadius: '8px',
              backgroundColor: color ? color.bg : 'rgba(99, 102, 241, 0.1)',
              borderLeft: `4px solid ${color ? color.text : '#a5b4fc'}`,
            }}
          >
            {/* 헤더: 화자 배지 + 시간 + 신뢰도 */}
            <div style={{ display: 'flex', alignItems: 'center', gap: '12px', flexWrap: 'wrap' }}>
              <span
                style={{
                  fontSize: '0.75rem',
                  fontWeight: 600,
                  padding: '4px 12px',
                  borderRadius: '16px',
                  backgroundColor: color ? color.bg : 'rgba(99, 102, 241, 0.2)',
                  color: color ? color.text : '#a5b4fc',
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                {seg.speaker}
              </span>

              <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
                {seg.start.toFixed(1)}s - {seg.end.toFixed(1)}s
              </span>

              {/* 신뢰도 표시 */}
              <div
                style={{
                  display: 'flex',
                  alignItems: 'center',
                  gap: '6px',
                  fontSize: '0.75rem',
                  color: confidenceColor,
                }}
              >
                <span
                  style={{
                    width: '4px',
                    height: '4px',
                    borderRadius: '50%',
                    backgroundColor: confidenceColor,
                  }}
                />
                {(seg.confidence * 100).toFixed(0)}%
              </div>
            </div>

            {/* 텍스트 본문 */}
            <p
              style={{
                fontSize: '1.05rem',
                color: 'var(--text-primary)',
                margin: 0,
                lineHeight: 1.5,
              }}
            >
              {seg.text}
            </p>
          </div>
        );
      })}

      {/* 실시간 수신 중인 부분 자막 */}
      {partialSegment && (
        <div
          style={{
            display: 'flex',
            flexDirection: 'column',
            gap: '8px',
            padding: '12px',
            borderRadius: '8px',
            backgroundColor: 'rgba(99, 102, 241, 0.1)',
            borderLeft: '4px dashed rgba(99, 102, 241, 0.5)',
            opacity: 0.7,
            animation: 'pulse 2s cubic-bezier(0.4, 0, 0.6, 1) infinite',
          }}
        >
          <div style={{ display: 'flex', alignItems: 'center', gap: '12px' }}>
            <span
              style={{
                fontSize: '0.75rem',
                fontWeight: 600,
                padding: '4px 12px',
                borderRadius: '16px',
                backgroundColor: 'rgba(99, 102, 241, 0.2)',
                color: '#a5b4fc',
                textTransform: 'uppercase',
                letterSpacing: '0.05em',
              }}
            >
              수신중
            </span>
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              {partialSegment.start.toFixed(1)}s
            </span>
          </div>
          <p
            style={{
              fontSize: '1.05rem',
              color: 'var(--text-secondary)',
              margin: 0,
              fontStyle: 'italic',
              lineHeight: 1.5,
            }}
          >
            {partialSegment.text}
            <span style={{ animation: 'blink 1s steps(2) infinite' }}>...</span>
          </p>
        </div>
      )}

      {/* 스크롤 앵커 */}
      <div ref={transcriptEndRef} />

      <style jsx>{`
        @keyframes pulse {
          0%,
          100% {
            opacity: 0.7;
          }
          50% {
            opacity: 0.9;
          }
        }

        @keyframes blink {
          0%,
          49% {
            opacity: 1;
          }
          50%,
          100% {
            opacity: 0.2;
          }
        }
      `}</style>
    </div>
  );
}
