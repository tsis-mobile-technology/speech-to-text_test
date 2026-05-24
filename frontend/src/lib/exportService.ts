/**
 * 회의 데이터를 다양한 포맷으로 내보내기
 * - SRT: 자막 형식
 * - TXT: 일반 텍스트
 * - JSON: 구조화된 데이터
 */

interface Segment {
  id: string;
  start: number;
  end: number;
  text: string;
  speaker: string;
  confidence: number;
  is_final: boolean;
}

interface SessionData {
  session_id: string;
  segments: Segment[];
  speaker_count: number;
  duration_sec: number;
  created_at?: string;
}

/**
 * SRT (SubRip) 형식으로 변환
 * 시간 형식: HH:MM:SS,mmm
 */
export function toSRT(session: SessionData): string {
  return session.segments
    .map((seg, index) => {
      const start = formatTime(seg.start);
      const end = formatTime(seg.end);
      return `${index + 1}\n${start} --> ${end}\n[${seg.speaker}] ${seg.text}\n`;
    })
    .join('\n');
}

/**
 * 일반 텍스트 형식으로 변환
 * 화자별로 구분하여 표시
 */
export function toTXT(session: SessionData): string {
  const lines: string[] = [
    `회의 기록`,
    `세션 ID: ${session.session_id}`,
    `화자 수: ${session.speaker_count}`,
    `총 시간: ${formatDuration(session.duration_sec)}`,
    session.created_at ? `작성 시간: ${new Date(session.created_at).toLocaleString('ko-KR')}` : '',
    `${'='.repeat(60)}`,
    '',
  ];

  session.segments.forEach((seg) => {
    lines.push(
      `[${formatTime(seg.start)}] ${seg.speaker} (${(seg.confidence * 100).toFixed(0)}%)`,
      seg.text,
      ''
    );
  });

  return lines.filter(Boolean).join('\n');
}

/**
 * JSON 형식으로 변환
 * 구조화된 데이터로 프로그래밍 언어에서 쉽게 파싱 가능
 */
export function toJSON(session: SessionData): string {
  return JSON.stringify(
    {
      metadata: {
        session_id: session.session_id,
        created_at: session.created_at || new Date().toISOString(),
        speaker_count: session.speaker_count,
        duration_sec: session.duration_sec,
      },
      segments: session.segments.map((seg) => ({
        id: seg.id,
        timestamp: {
          start: seg.start,
          end: seg.end,
          start_human: formatTime(seg.start),
          end_human: formatTime(seg.end),
        },
        speaker: seg.speaker,
        text: seg.text,
        confidence: seg.confidence,
        is_final: seg.is_final,
      })),
    },
    null,
    2
  );
}

/**
 * 시간을 SRT/일반 형식으로 변환
 * @param seconds - 초 단위 시간
 * @returns 형식화된 시간 문자열
 */
function formatTime(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);
  const ms = Math.round((seconds % 1) * 1000);

  return `${String(hours).padStart(2, '0')}:${String(minutes).padStart(2, '0')}:${String(secs).padStart(2, '0')},${String(ms).padStart(3, '0')}`;
}

/**
 * 초를 "HH:MM:SS" 형식으로 변환
 */
function formatDuration(seconds: number): string {
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = Math.floor(seconds % 60);

  const parts = [];
  if (hours > 0) parts.push(`${hours}시간`);
  if (minutes > 0) parts.push(`${minutes}분`);
  if (secs > 0) parts.push(`${secs}초`);

  return parts.join(' ') || '0초';
}

/**
 * 브라우저에서 파일 다운로드
 */
export function downloadFile(
  content: string,
  filename: string,
  mimeType: string = 'text/plain'
): void {
  const blob = new Blob([content], { type: mimeType });
  const url = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  document.body.removeChild(link);
  URL.revokeObjectURL(url);
}

/**
 * 세션을 선택된 형식으로 내보내기
 */
export function exportSession(
  session: SessionData,
  format: 'srt' | 'txt' | 'json'
): void {
  let content: string;
  let filename: string;
  let mimeType: string;

  const timestamp = new Date().toISOString().split('T')[0]; // YYYY-MM-DD
  const baseName = `meeting_${timestamp}`;

  switch (format) {
    case 'srt':
      content = toSRT(session);
      filename = `${baseName}.srt`;
      mimeType = 'text/plain';
      break;
    case 'txt':
      content = toTXT(session);
      filename = `${baseName}.txt`;
      mimeType = 'text/plain; charset=utf-8';
      break;
    case 'json':
      content = toJSON(session);
      filename = `${baseName}.json`;
      mimeType = 'application/json; charset=utf-8';
      break;
    default:
      throw new Error(`Unsupported format: ${format}`);
  }

  downloadFile(content, filename, mimeType);
}

/**
 * 세션 데이터를 DOCX 형식으로 생성 (추후 python-docx로 서버에서 처리)
 * 이 함수는 API 호출을 통해 서버에서 생성하도록 함
 */
export async function exportSessionDOCX(sessionId: string): Promise<void> {
  try {
    const response = await fetch(
      `http://localhost:8000/api/v1/sessions/${sessionId}/export?format=docx`
    );

    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }

    const blob = await response.blob();
    const timestamp = new Date().toISOString().split('T')[0];
    downloadFile(
      await blob.text(),
      `meeting_${timestamp}.docx`,
      'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
    );
  } catch (error) {
    console.error('DOCX export failed:', error);
    alert('DOCX 내보내기에 실패했습니다. 서버 상태를 확인해주세요.');
  }
}
