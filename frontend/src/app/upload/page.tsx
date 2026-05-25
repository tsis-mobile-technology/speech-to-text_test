'use client';

import { useState, useCallback, useRef } from 'react';
import { useRouter } from 'next/navigation';
import { Upload, FileAudio, AlertCircle, RefreshCw, CheckCircle, ArrowRight, Settings } from 'lucide-react';

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

  // 드래그 앤 드롭 핸들러 (동작 유지)
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

    if (!e.dataTransfer.files || e.dataTransfer.files.length === 0) {
      setErrorMessage('파일을 드롭해 주세요.');
      return;
    }

    const droppedFile = e.dataTransfer.files[0];

    if (!droppedFile.name) {
      setErrorMessage('파일명이 없는 파일입니다.');
      return;
    }

    const supportedFormats = ['.wav', '.mp3', '.m4a', '.mp4', '.ogg', '.webm', '.flac'];
    const fileExt = droppedFile.name.toLowerCase().slice(droppedFile.name.lastIndexOf('.'));
    const isAudioType = droppedFile.type.startsWith('audio/') || droppedFile.type.startsWith('video/');
    const isSupportedFormat = supportedFormats.some(fmt => droppedFile.name.toLowerCase().endsWith(fmt));

    if (!isAudioType && !isSupportedFormat) {
      setErrorMessage(`지원되지 않는 형식입니다. 지원 형식: ${supportedFormats.join(', ')}`);
      return;
    }

    const maxSize = 500 * 1024 * 1024; // 500MB
    if (droppedFile.size > maxSize) {
      setErrorMessage(`파일이 너무 큽니다. 최대 크기: 500MB (현재: ${(droppedFile.size / 1024 / 1024).toFixed(1)}MB)`);
      return;
    }

    if (droppedFile.size === 0) {
      setErrorMessage('빈 파일입니다.');
      return;
    }

    setFile(droppedFile);
    setStatus('idle');
    setErrorMessage(null);
  }, []);

  // 파일 브라우징 선택 핸들러
  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (!e.target.files || e.target.files.length === 0) {
      setErrorMessage('파일을 선택해 주세요.');
      return;
    }

    const selectedFile = e.target.files[0];
    const maxSize = 500 * 1024 * 1024;
    if (selectedFile.size > maxSize) {
      setErrorMessage(`파일이 너무 큽니다. 최대 크기: 500MB (현재: ${(selectedFile.size / 1024 / 1024).toFixed(1)}MB)`);
      return;
    }

    if (selectedFile.size === 0) {
      setErrorMessage('빈 파일입니다.');
      return;
    }

    setFile(selectedFile);
    setStatus('idle');
    setErrorMessage(null);
  };

  const triggerFileInput = () => {
    if (fileInputRef.current) {
      fileInputRef.current.click();
    }
  };

  // 업로드 및 배치 분석 시작
  const handleUploadSubmit = async () => {
    if (!file) {
      setErrorMessage('파일을 선택해 주세요.');
      return;
    }

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
        let errorMsg = '업로드에 실패했습니다.';
        if (response.status === 400) {
          try {
            const error = await response.json();
            errorMsg = error.detail || '잘못된 요청입니다.';
          } catch {
            errorMsg = await response.text();
          }
        } else if (response.status === 413) {
          errorMsg = '파일이 너무 큽니다. 최대 500MB입니다.';
        } else if (response.status === 500) {
          errorMsg = '서버 오류가 발생했습니다. 나중에 다시 시도해 주세요.';
        } else {
          try {
            const error = await response.json();
            errorMsg = error.detail || `HTTP ${response.status} 오류`;
          } catch {
            errorMsg = `HTTP ${response.status} 오류`;
          }
        }
        throw new Error(errorMsg);
      }

      const data = await response.json();
      if (!data.session_id) {
        throw new Error('응답에 세션 ID가 없습니다.');
      }

      setSessionId(data.session_id);
      setStatus('processing');

      // 세션 상세 폴링 및 편집기 페이지로 강제 라우팅
      router.push(`/sessions/${data.session_id}`);
    } catch (err: any) {
      console.error('❌ Upload error:', err);
      setStatus('error');
      setErrorMessage(err.message || '파일 업로드 중 오류가 발생했습니다.');
    } finally {
      setIsUploading(false);
    }
  };

  return (
    <div style={{ maxWidth: '680px', margin: '20px auto 0', contentVisibility: 'auto' }}>
      
      {/* 타이틀 헤더 */}
      <div style={{ textAlign: 'center', marginBottom: '40px' }}>
        <span className="gradient-text" style={{ fontSize: '0.9rem', fontWeight: 700, textTransform: 'uppercase', letterSpacing: '0.05em' }}>
          Batch Processing
        </span>
        <h1 style={{ fontSize: '2.5rem', marginTop: '4px', fontWeight: 800 }}>음성 파일 회의록 변환</h1>
        <p style={{ color: 'var(--text-secondary)', marginTop: '10px', fontSize: '0.95rem' }}>
          기록된 오디오 및 비디오 파일(WAV, MP3, M4A, MP4)을 일괄 전사하여 화자 정렬 회의록을 출력합니다.
        </p>
      </div>

      {/* 메인 폼 카드 */}
      <div className="glass-panel" style={{ padding: '40px', display: 'flex', flexDirection: 'column', gap: '30px' }}>
        
        {/* 업로드 드롭 박스 (네온 애니메이션 보더 추가) */}
        <div 
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={triggerFileInput}
          style={{
            border: '2.5px dashed',
            borderColor: isDragOver ? 'var(--color-primary)' : 'rgba(255, 255, 255, 0.08)',
            background: isDragOver ? 'rgba(99, 102, 241, 0.04)' : 'rgba(15, 17, 26, 0.45)',
            boxShadow: isDragOver ? 'var(--shadow-glow)' : 'none',
            transform: isDragOver ? 'scale(1.015)' : 'scale(1)',
            borderRadius: 'var(--radius-md)',
            padding: '52px 24px',
            textAlign: 'center',
            cursor: 'pointer',
            transition: 'all 0.3s cubic-bezier(0.4, 0, 0.2, 1)',
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
          
          <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: '18px' }}>
            
            {/* 업로드 아이콘 링 */}
            <div style={{
              width: '68px',
              height: '68px',
              borderRadius: '50%',
              backgroundColor: 'rgba(255,255,255,0.02)',
              display: 'flex',
              alignItems: 'center',
              justifyContent: 'center',
              border: '1.5px solid rgba(255, 255, 255, 0.08)',
              borderColor: isDragOver ? 'var(--color-primary)' : 'rgba(255, 255, 255, 0.08)',
              color: isDragOver ? 'var(--color-primary)' : 'var(--text-secondary)',
              boxShadow: isDragOver ? '0 0 15px rgba(99, 102, 241, 0.15)' : 'none',
              transition: 'all 0.2s ease'
            }}>
              <Upload size={30} />
            </div>
            
            {file ? (
              <div className="glass-panel" style={{ 
                padding: '16px 24px', 
                background: 'rgba(255, 255, 255, 0.01)', 
                borderColor: 'var(--border-hover)',
                boxShadow: 'var(--shadow-glow)',
                display: 'inline-flex',
                alignItems: 'center',
                gap: '12px',
                maxWidth: '90%'
              }}>
                <FileAudio size={20} color="var(--color-primary)" />
                <div style={{ textAlign: 'left', overflow: 'hidden' }}>
                  <p style={{ fontSize: '0.95rem', fontWeight: 700, color: 'white', overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap', maxWidth: '300px' }}>
                    {file.name}
                  </p>
                  <p style={{ fontSize: '0.75rem', color: 'var(--text-muted)', marginTop: '2px' }}>
                    {(file.size / (1024 * 1024)).toFixed(2)} MB
                  </p>
                </div>
              </div>
            ) : (
              <div>
                <p style={{ fontSize: '1.15rem', fontWeight: 700, color: 'white' }}>회의 파일을 드래그하여 드롭하세요</p>
                <p style={{ fontSize: '0.85rem', color: 'var(--text-secondary)', marginTop: '6px' }}>
                  또는 여기를 클릭해 탐색창에서 로컬 PC 파일을 선택합니다
                </p>
              </div>
            )}
            
            <span style={{ fontSize: '0.75rem', color: 'var(--text-muted)', fontWeight: 500 }}>
              지원 포맷: WAV, MP3, M4A, MP4, WEBM (최대 500MB 한계)
            </span>
          </div>
        </div>

        {/* 에러 패널 */}
        {errorMessage && (
          <div className="glass-panel" style={{
            padding: '16px 20px',
            backgroundColor: 'rgba(239, 68, 68, 0.08)',
            borderColor: 'rgba(239, 68, 68, 0.25)',
            display: 'flex',
            alignItems: 'center',
            gap: '12px'
          }}>
            <AlertCircle color="#ef4444" size={20} />
            <span style={{ fontSize: '0.9rem', color: '#fca5a5', fontWeight: 500 }}>{errorMessage}</span>
          </div>
        )}

        {/* 세부 옵션 & 변환 제출 제어 */}
        {file && (
          <div style={{ display: 'flex', flexDirection: 'column', gap: '24px', borderTop: '1px solid var(--border-light)', paddingTop: '24px' }}>
            
            {/* Diarization 옵션 카드 */}
            <div className="glass-panel" style={{ padding: '20px 24px', display: 'flex', alignItems: 'center', justifyContent: 'space-between', background: 'rgba(255,255,255,0.015)' }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: '14px' }}>
                <Settings size={20} color="var(--text-secondary)" />
                <div>
                  <h3 style={{ fontSize: '0.95rem', fontWeight: 700, color: 'white' }}>화자 인식 분리(Diarization)</h3>
                  <p style={{ fontSize: '0.8rem', color: 'var(--text-secondary)', marginTop: '2px' }}>
                    회의록 내 화자(SPEAKER_XX)를 pyannote.audio 신경망 기반으로 분리 매핑합니다.
                  </p>
                </div>
              </div>
              
              {/* globals.css에 추가한 custom-switch 적용 */}
              <label className="custom-switch">
                <input 
                  type="checkbox" 
                  checked={enableDiarization}
                  onChange={(e) => setEnableDiarization(e.target.checked)}
                />
                <span className="custom-slider" />
              </label>
            </div>

            {/* 작업 시작 버튼 */}
            {status === 'idle' && (
              <button onClick={handleUploadSubmit} className="btn btn-primary" style={{ width: '100%', padding: '15px', borderRadius: 'var(--radius-sm)' }}>
                배치 변환 분석 시작
                <ArrowRight size={18} />
              </button>
            )}
            
            {/* 업로드 진행/변환 대기 상태 스피너 */}
            {status === 'uploading' && (
              <button disabled className="btn btn-secondary" style={{ width: '100%', padding: '15px', cursor: 'not-allowed', display: 'flex', justifyContent: 'center', gap: '12px' }}>
                <RefreshCw className="spin" size={18} style={{ animation: 'spin 1.2s linear infinite', color: 'var(--color-primary)' }} />
                오디오 파일 전송 중...
              </button>
            )}
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
