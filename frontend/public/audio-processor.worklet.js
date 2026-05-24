class AudioStreamProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    // 16kHz mono로 수집된 데이터를 누적할 청크 버퍼
    this.bufferSize = 4096; // 약 250ms 분량
    this.buffer = new Float32Array(this.bufferSize);
    this.bufferIndex = 0;
  }

  process(inputs, outputs, parameters) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    
    // 모노 채널(0번 채널)의 PCM 입력값 획득
    const channelData = input[0];
    
    for (let i = 0; i < channelData.length; i++) {
      this.buffer[this.bufferIndex] = channelData[i];
      this.bufferIndex++;
      
      // 버퍼가 가득 차면 메인 스레드로 포스트 전송
      if (this.bufferIndex >= this.bufferSize) {
        this.port.postMessage(this.buffer);
        // 버퍼 초기화
        this.buffer = new Float32Array(this.bufferSize);
        this.bufferIndex = 0;
      }
    }
    
    return true;
  }
}

registerProcessor('audio-stream-processor', AudioStreamProcessor);
