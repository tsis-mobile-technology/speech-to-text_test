'use client';

import { Users, MessageSquare, Clock, TrendingUp } from 'lucide-react';

interface Segment {
  id: string;
  start: number;
  end: number;
  text: string;
  speaker: string;
  confidence: number;
}

interface SpeakerStats {
  speaker: string;
  speakCount: number;
  totalDuration: number;
  avgConfidence: number;
  wordCount: number;
}

interface SpeakerStatisticsProps {
  segments: Segment[];
}

const SPEAKER_COLORS = [
  { bg: 'rgba(99, 102, 241, 0.1)', text: '#a5b4fc', border: 'rgba(99, 102, 241, 0.3)' },      // indigo
  { bg: 'rgba(168, 85, 247, 0.1)', text: '#d8b4fe', border: 'rgba(168, 85, 247, 0.3)' },      // purple
  { bg: 'rgba(236, 72, 153, 0.1)', text: '#f472b6', border: 'rgba(236, 72, 153, 0.3)' },     // pink
  { bg: 'rgba(249, 115, 22, 0.1)', text: '#fb923c', border: 'rgba(249, 115, 22, 0.3)' },     // orange
];

/**
 * 화자별 통계를 표시하는 컴포넌트
 * - 화자별 발언 수
 * - 화자별 총 말한 시간
 * - 화자별 평균 신뢰도
 * - 화자별 단어 수
 */
export function SpeakerStatistics({ segments }: SpeakerStatisticsProps) {
  // 화자별 통계 계산
  const stats = calculateSpeakerStats(segments);

  if (stats.length === 0) {
    return (
      <div
        style={{
          padding: '24px',
          borderRadius: '12px',
          backgroundColor: 'rgba(99, 102, 241, 0.05)',
          border: '1px solid rgba(99, 102, 241, 0.2)',
          textAlign: 'center',
          color: 'var(--text-muted)',
        }}
      >
        <Users size={32} style={{ margin: '0 auto 12px', opacity: 0.3 }} />
        <p>발언 데이터가 없습니다.</p>
      </div>
    );
  }

  // 총 시간 계산
  const totalDuration = stats.reduce((sum, s) => sum + s.totalDuration, 0);
  const totalSpeaks = stats.reduce((sum, s) => sum + s.speakCount, 0);

  return (
    <div
      style={{
        display: 'flex',
        flexDirection: 'column',
        gap: '20px',
      }}
    >
      {/* 헤더 */}
      <div style={{ display: 'flex', alignItems: 'center', gap: '10px' }}>
        <Users size={20} style={{ color: '#6366f1' }} />
        <h2 style={{ fontSize: '1.3rem', margin: 0 }}>화자 통계</h2>
      </div>

      {/* 요약 메트릭 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', gap: '12px' }}>
        <MetricCard
          icon={Users}
          label="총 화자"
          value={stats.length.toString()}
          color="#6366f1"
        />
        <MetricCard
          icon={MessageSquare}
          label="총 발언"
          value={totalSpeaks.toString()}
          color="#a855f7"
        />
        <MetricCard
          icon={Clock}
          label="총 시간"
          value={formatDuration(totalDuration)}
          color="#ec4899"
        />
        <MetricCard
          icon={TrendingUp}
          label="평균 신뢰도"
          value={`${calculateAverageConfidence(segments)}%`}
          color="#f59e0b"
        />
      </div>

      {/* 화자별 상세 통계 */}
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(250px, 1fr))', gap: '16px' }}>
        {stats.map((stat, index) => {
          const color = SPEAKER_COLORS[index % SPEAKER_COLORS.length];
          const speakingPercentage = (stat.totalDuration / totalDuration) * 100;

          return (
            <div
              key={stat.speaker}
              style={{
                padding: '16px',
                borderRadius: '10px',
                backgroundColor: color.bg,
                border: `1px solid ${color.border}`,
                display: 'flex',
                flexDirection: 'column',
                gap: '12px',
              }}
            >
              {/* 화자 이름 */}
              <div
                style={{
                  fontSize: '0.9rem',
                  fontWeight: 600,
                  color: color.text,
                  textTransform: 'uppercase',
                  letterSpacing: '0.05em',
                }}
              >
                {stat.speaker}
              </div>

              {/* 통계 항목 */}
              <div style={{ display: 'flex', flexDirection: 'column', gap: '8px', fontSize: '0.85rem' }}>
                <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                  <span>📢 발언 수</span>
                  <span style={{ fontWeight: 600, color: color.text }}>
                    {stat.speakCount}회
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                  <span>⏱️ 말한 시간</span>
                  <span style={{ fontWeight: 600, color: color.text }}>
                    {formatDuration(stat.totalDuration)}
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                  <span>📊 신뢰도</span>
                  <span style={{ fontWeight: 600, color: color.text }}>
                    {(stat.avgConfidence * 100).toFixed(0)}%
                  </span>
                </div>

                <div style={{ display: 'flex', justifyContent: 'space-between', color: 'var(--text-secondary)' }}>
                  <span>📝 단어 수</span>
                  <span style={{ fontWeight: 600, color: color.text }}>
                    {stat.wordCount}개
                  </span>
                </div>
              </div>

              {/* 진행률 바 */}
              <div style={{ marginTop: '4px' }}>
                <div
                  style={{
                    height: '4px',
                    backgroundColor: 'rgba(0, 0, 0, 0.1)',
                    borderRadius: '2px',
                    overflow: 'hidden',
                  }}
                >
                  <div
                    style={{
                      height: '100%',
                      width: `${speakingPercentage}%`,
                      backgroundColor: color.text,
                      transition: 'width 0.3s ease',
                    }}
                  />
                </div>
                <div style={{ fontSize: '0.7rem', marginTop: '4px', color: 'var(--text-muted)' }}>
                  말한 시간: {speakingPercentage.toFixed(1)}%
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}

/**
 * 화자별 통계 계산
 */
function calculateSpeakerStats(segments: Segment[]): SpeakerStats[] {
  const speakerMap = new Map<string, SpeakerStats>();

  segments.forEach((seg) => {
    if (!speakerMap.has(seg.speaker)) {
      speakerMap.set(seg.speaker, {
        speaker: seg.speaker,
        speakCount: 0,
        totalDuration: 0,
        avgConfidence: 0,
        wordCount: 0,
      });
    }

    const stat = speakerMap.get(seg.speaker)!;
    stat.speakCount += 1;
    stat.totalDuration += seg.end - seg.start;
    stat.wordCount += seg.text.split(/\s+/).length;
  });

  // 평균 신뢰도 계산
  const confidenceMap = new Map<string, { sum: number; count: number }>();
  segments.forEach((seg) => {
    if (!confidenceMap.has(seg.speaker)) {
      confidenceMap.set(seg.speaker, { sum: 0, count: 0 });
    }
    const conf = confidenceMap.get(seg.speaker)!;
    conf.sum += seg.confidence;
    conf.count += 1;
  });

  speakerMap.forEach((stat) => {
    const conf = confidenceMap.get(stat.speaker);
    if (conf) {
      stat.avgConfidence = conf.sum / conf.count;
    }
  });

  // 말한 시간순 정렬
  return Array.from(speakerMap.values()).sort((a, b) => b.totalDuration - a.totalDuration);
}

/**
 * 초를 "M분 S초" 형식으로 변환
 */
function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const secs = Math.round(seconds % 60);
  if (minutes > 0) {
    return `${minutes}분 ${secs}초`;
  }
  return `${secs}초`;
}

/**
 * 전체 평균 신뢰도 계산
 */
function calculateAverageConfidence(segments: Segment[]): number {
  if (segments.length === 0) return 0;
  const avg = segments.reduce((sum, seg) => sum + seg.confidence, 0) / segments.length;
  return Math.round(avg * 100);
}

/**
 * 메트릭 카드 컴포넌트
 */
function MetricCard({
  icon: IconComponent,
  label,
  value,
  color,
}: {
  icon: React.ComponentType<{ size?: number; style?: React.CSSProperties }>;
  label: string;
  value: string;
  color: string;
}) {
  return (
    <div
      style={{
        padding: '16px',
        borderRadius: '10px',
        backgroundColor: `${color}15`,
        border: `1px solid ${color}30`,
        display: 'flex',
        flexDirection: 'column',
        alignItems: 'center',
        gap: '8px',
        textAlign: 'center',
      }}
    >
      <IconComponent size={20} style={{ color }} />
      <div style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>{label}</div>
      <div style={{ fontSize: '1.3rem', fontWeight: 700, color }}>{value}</div>
    </div>
  );
}
