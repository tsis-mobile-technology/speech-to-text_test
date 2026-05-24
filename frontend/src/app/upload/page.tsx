'use client';

import { useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Upload, FileAudio, AlertCircle, RefreshCw, CheckCircle, ArrowRight } from 'lucide-react';

export default function AudioUploadPage() {
  const [file, setFile] = useState<File | null>(null);
  const [isDragOver, setIsDragOver] = useState(false);
  const [isUploading, setIsUploading] = useState(false);
  const [status, setStatus] = useState<'idle' | 'uploading' | 'processing' | 'success' | 'error'>('idle');
  const [errorMessage, setErrorMessage] = useState<string | null>(null);
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [enableDiarization, setEnableDiarization] = useState(true);
  
  const fileInputRef = useRef<HTMLInputElement | null>(null);
  const router = useRouter();

  // 드래그 앤 드롭 이벤트 핸들러
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(true);
  }, []);

  const handleDragLeave = useCallback(() => {
    setIsDragOver(false);
  }, []);

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setIsDragOver(false);
    
    if (e.dataTransfer.files && e.dataTransfer.files.length > 0) {
      const droppedFile = e.dataTransfer.files[0];
      // 오디오 또는 비디오 파일 형식 필터링
      if (droppedFile.type.startsWith('audio/') || droppedFile.type.startsWith('video/') || droppedFile.name.endsWith('.m4a') || droppedFile.name.endsWith('.mp3') || droppedFile.name.endsWith('.wav')) {
        setFile(droppedFile);
        setStatus('idle');
        setErrorMessage(null);
      } else {
        setErrorMessage('지원되지 않는 파일 형식입니다. 오디오 파일을 업로드해 주세요.');
      }
    }
  }, []);

  // 파일 선택 변경 핸들러
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files && e.target.files.length > 0) {
      setFile(e.target.files[0]);
      setStatus('idle');
      setErrorMessage(null);
    }
  };

  // 업로드 영역 클릭 시 탐색기 창 열기
  const triggerFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  // 업로드 및 배치 변환 시작
  const handleUploadSubmit = async () => {
    if (!file) return;
    
    setIsUploading(true);
    setStatus('uploading');
    setErrorMessage(null);
    
    const formData = new FormData();
    formData.append('audio_file', file);
    formData.append('enable_diarization', String(enableDiarization));

    try {
      const host = window.location.hostname;
      const response = await fetch(`http://${host}:8000/api/v1/transcribe`, {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        throw new Error('서버 업로드 또는 요청 등록에 실패했습니다.');
      }

      const data = await response.json();
      setSessionId(data.session_id);
      setStatus('processing');
      
      // 변환이 시작되면 세션 상세 페이지로 즉시 이동하여 변환 로딩 상태를 보여줍니다.
      router.push(`/sessions/${data.session_id}`);
      
    } catch (err: any) {
      console.error(err);
      setStatus('error');
      setErrorMessage(err.message || '파일 처리 도중 오류가 발생했습니다.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div style={{ maxWidth: '680px', margin: '0 auto' }}>
      <div style={{ textAlign: 'center', marginBottom: '40px' }}>
        <span className="gradient-text" style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Batch Processing
        </span>
        <h1 style={{ fontSize: '2.5rem', marginTop: '4px', fontWeight: 800 }}>음성 파일 회의록 변환</h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: '10px' }}>
          녹음되거나 촬영된 회의 파일(WAV, MP3, M4A, MP4)을 업로드하여 자막과 화자 분리를 일괄 생성합니다.
        </p>
      </div>

      <div className="glass-panel" style={{ padding: '40px', display: 'flex', flexDirection: 'column', gap: '30px' }}>
        
        {/* 드래그 앤 드롭 업로드 카드 영역 */}
        <div 
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={triggerFileInput}
          style={{
            border: '2px dashed var(--border-light)',
            borderColor: isDragOver ? 'var(--color-primary)' : 'var(--border-light)',
            background: isDragOver ? 'rgba(99, 102, 241, 0.03)' : 'rgba(0,0,0,0.15)',
            borderRadius: 'var(--radius-md)',
            padding: '48px 24px',
            textAlign: 'center',
            cursor: 'pointer',
            transition: 'all 0.2s ease',
            position: 'relative'
          }}
        >
          <input 
            type="file" 
            ref={fileInputRef}
            onChange={handleFileChange}
            accept="audio/*,video/*"
            style={{ display: 'none' }} 
          />
          
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '16px' }}>
            <div style={{
              width: '64px',
              height: '64px',
              borderRadius: '50%',
              backgroundColor: 'rgba(255,255,255,0.03)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1px solid var(--border-light)',
              color: 'var(--color-primary)'
            }}>
              <Upload size={28} />
            </div>
            
            {file ? (
              <div>
                <p style={{ fontSize: '1.1rem', fontWeight: 600, color: 'white' }}>{file.name}</p>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '4px' }}>
                  {(file.size / (1024 * 1024)).toFixed(2)} MB
                </p>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: '1.1rem', fontWeight: 600 }}>여기에 오디오 파일을 드래그하여 놓으세요.</p>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '6px' }}>
                  또는 영역을 클릭하여 내 PC의 파일을 탐색합니다.
                </p>
              </div>
            )}
            
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)' }}>
              지원 형식: WAV, MP3, M4A, MP4, WEBM (최대 500MB)
            </span>
          </div>
        </div>

        {/* 에러 피드백 */}
        {errorMessage && (
          <div className="glass-panel" style={{
            padding: '16px 20px',
            backgroundColor: 'rgba(239, 68, 68, 0.1)',
            borderColor: 'rgba(239, 68, 68, 0.2)',
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}>
            <AlertCircle color="#ef4444" size={20} />
            <span style={{ fontSize: '0.9rem', color: '#fca5a5' }}>{errorMessage}</span>
          </div>
        )}

        {/* 옵션 및 제출 폼 보드 */}
        {file && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '20px', borderTop: '1px solid var(--border-light)', paddingTop: '24px' }}>
            <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between' }}>
              <div>
                <h3 style={{ fontSize: '1rem', fontWeight: 600 }}>화자 분리(Diarization) 사용</h3>
                <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)' }}>
                  회의 내 말하는 사람을 감지하여 구분(SPEAKER_00, 01 등)합니다.
                </p>
              </div>
              <label className="switch" style={{ position: 'relative', display: 'inline-block', width: '48px', height: '24px' }}>
                <input 
                  type="checkbox" 
                  checked={enableDiarization}
                  onChange={(e) => setEnableDiarization(e.target.checked)}
                  style={{ opacity: 0, width: 0, height: 0 }}
                />
                <span className="slider" style={{
                  position: 'absolute',
                  cursor: 'pointer',
                  top: 0, left: 0, right: 0, bottom: 0,
                  backgroundColor: enableDiarization ? 'var(--color-primary)' : 'rgba(255,255,255,0.1)',
                  borderRadius: '24px',
                  transition: '0.3s'
                }}>
                  <span style={{
                    position: 'absolute',
                    content: '""',
                    height: '18px', width: '18px',
                    left: enableDiarization ? '26px' : '3px',
                    bottom: '3px',
                    backgroundColor: 'white',
                    borderRadius: '50%',
                    transition: '0.3s'
                  }} />
                </span>
              </label>
            </div>

            {status === 'idle' && (
              <button onClick={handleUploadSubmit} className="btn btn-primary" style={{ width: '100%', padding: '14px' }}>
                변환 분석 시작
                <ArrowRight size={18} />
              </button>
            )}
            
            {status === 'uploading' && (
              <button disabled className="btn btn-secondary" style={{ width: '100%', padding: '14px', cursor: 'not-allowed', display: 'flex', justifyContent: 'center', gap: '12px' }}>
                <RefreshCw className="spin" size={18} style={{ animation: 'spin 1s linear infinite' }} />
                파일 업로드 중...
              </button>
            )}
          </div>
        )}
      </div>
      
      {/* CSS 스핀 정의 주입 */}
      <style jsx global>{`
        @keyframes spin {
          0% { transform: rotate(0deg); }
          100% { transform: rotate(360deg); }
        }
      `}</style>
    </div>
  );
}
