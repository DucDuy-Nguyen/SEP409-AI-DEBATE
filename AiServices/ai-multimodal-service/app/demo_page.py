DEMO_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>ADPP — Multimodal Debate Coach (DeepFace + Faster-Whisper)</title>
  <style>
    :root {
      --bg: #0f172a;
      --card-bg: #1e293b;
      --card-inner: #0b1120;
      --accent: #38bdf8;
      --accent-hover: #0284c7;
      --text: #f8fafc;
      --text-muted: #94a3b8;
      --success: #22c55e;
      --warning: #f59e0b;
      --danger: #ef4444;
      --border: #334155;
    }
    * { box-sizing: border-box; margin: 0; padding: 0; }
    body {
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: var(--bg);
      color: var(--text);
      padding: 24px;
      line-height: 1.5;
    }
    .header {
      max-width: 1200px;
      margin: 0 auto 22px;
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: 12px;
      border-bottom: 1px solid var(--border);
      padding-bottom: 16px;
    }
    .header h1 {
      font-size: 24px;
      color: var(--accent);
    }
    .header p {
      color: var(--text-muted);
      font-size: 14px;
    }
    .badge {
      padding: 6px 14px;
      border-radius: 999px;
      font-size: 12px;
      font-weight: 600;
      background: #065f46;
      color: #a7f3d0;
      border: 1px solid #059669;
    }
    .grid-main {
      max-width: 1200px;
      margin: 0 auto;
      display: grid;
      grid-template-columns: 1.05fr 1fr;
      gap: 20px;
    }
    @media (max-width: 900px) {
      .grid-main { grid-template-columns: 1fr; }
    }
    .card {
      background: var(--card-bg);
      border: 1px solid var(--border);
      border-radius: 12px;
      padding: 20px;
      margin-bottom: 20px;
    }
    .card h2 {
      font-size: 17px;
      margin-bottom: 12px;
      color: #e2e8f0;
      display: flex;
      align-items: center;
      gap: 8px;
    }
    .video-box {
      position: relative;
      width: 100%;
      height: 320px;
      background: #000;
      border-radius: 10px;
      overflow: hidden;
      margin-bottom: 14px;
      border: 1px solid var(--border);
    }
    video {
      width: 100%;
      height: 100%;
      object-fit: cover;
      transform: scaleX(-1);
    }
    canvas#overlay {
      position: absolute;
      top: 0;
      left: 0;
      width: 100%;
      height: 100%;
      pointer-events: none;
    }
    .hud-top {
      position: absolute;
      top: 12px;
      left: 12px;
      right: 12px;
      display: flex;
      justify-content: space-between;
      pointer-events: none;
    }
    .hud-pill {
      background: rgba(15, 23, 42, 0.82);
      border: 1px solid rgba(56, 189, 248, 0.4);
      padding: 5px 12px;
      border-radius: 6px;
      font-size: 13px;
      font-weight: 600;
      color: #38bdf8;
    }
    .metric-row {
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: 9px;
      font-size: 13.5px;
    }
    .progress-bar-bg {
      flex: 1;
      height: 8px;
      background: #334155;
      border-radius: 4px;
      margin: 0 12px;
      overflow: hidden;
    }
    .progress-bar {
      height: 100%;
      width: 0%;
      background: var(--accent);
      transition: width 0.2s ease;
    }
    .btn-row {
      display: flex;
      gap: 10px;
      flex-wrap: wrap;
      margin-top: 12px;
    }
    button {
      flex: 1;
      min-width: 140px;
      padding: 11px 14px;
      border: none;
      border-radius: 8px;
      font-size: 13.5px;
      font-weight: 600;
      cursor: pointer;
      transition: all 0.15s;
    }
    button:disabled { opacity: 0.45; cursor: not-allowed; }
    .btn-primary { background: var(--accent); color: #0f172a; }
    .btn-primary:hover:not(:disabled) { background: #7dd3fc; }
    .btn-danger { background: var(--danger); color: #fff; }
    .btn-secondary { background: #334155; color: #f8fafc; border: 1px solid #475569; }
    .btn-secondary:hover:not(:disabled) { background: #475569; }
    .btn-success { background: var(--success); color: #052e16; }
    label {
      display: block;
      font-size: 13px;
      font-weight: 600;
      color: var(--text-muted);
      margin: 10px 0 4px;
    }
    input[type=text], select, textarea {
      width: 100%;
      padding: 9px 12px;
      border-radius: 7px;
      border: 1px solid var(--border);
      background: var(--card-inner);
      color: var(--text);
      font-size: 13.5px;
      font-family: inherit;
    }
    textarea { min-height: 76px; resize: vertical; }
    .form-row { display: flex; gap: 12px; }
    .form-row > div { flex: 1; }
    .kpi-grid {
      display: grid;
      grid-template-columns: repeat(4, 1fr);
      gap: 10px;
      margin-bottom: 14px;
    }
    .kpi-box {
      background: var(--card-inner);
      border: 1px solid var(--border);
      border-radius: 8px;
      padding: 10px;
      text-align: center;
    }
    .kpi-val {
      font-size: 22px;
      font-weight: 700;
      color: var(--accent);
    }
    .kpi-lbl {
      font-size: 11.5px;
      color: var(--text-muted);
    }
    .report-img {
      width: 100%;
      border-radius: 8px;
      border: 1px solid var(--border);
      margin-top: 10px;
    }
    pre {
      background: var(--card-inner);
      padding: 12px;
      border-radius: 8px;
      font-size: 12px;
      overflow-x: auto;
      max-height: 240px;
      color: #7dd3fc;
      border: 1px solid var(--border);
    }
    .crit-item {
      padding: 8px 0;
      border-bottom: 1px solid var(--border);
      font-size: 13px;
    }
    .status-log {
      margin-top: 10px;
      font-size: 12px;
      color: var(--text-muted);
    }
  </style>
</head>
<body>
  <div class="header">
    <div>
      <h1>🎭 ADPP — Multimodal Debate Coach (DeepFace + Faster-Whisper)</h1>
      <p>Đánh giá toàn diện Phiên Tranh Biện: Cảm xúc khuôn mặt (DeepFace YuNet) + Giọng nói (Faster-Whisper) + Lập luận (AI Evaluator)</p>
    </div>
    <div id="modelBadge" class="badge">⏳ Đang kiểm tra Model...</div>
  </div>

  <div class="grid-main">
    <!-- CỘT TRÁI: CAMERA, MIC & THIẾT LẬP TRANH BIỆN -->
    <div>
      <div class="card">
        <h2>📷 1. Thu hình & Giọng nói Tranh biện (Realtime Vision & Voice)</h2>
        <div class="video-box">
          <video id="webcam" autoplay playsinline muted></video>
          <canvas id="overlay"></canvas>
          <div class="hud-top">
            <div class="hud-pill" id="timerPill">⏱️ 00:00</div>
            <div class="hud-pill" id="emotionPill">🎭 NEUTRAL (0%)</div>
          </div>
        </div>

        <div class="metric-row">
          <span style="width: 110px;">🎙️ Âm lượng Mic:</span>
          <div class="progress-bar-bg"><div class="progress-bar" id="micBar" style="background: var(--success)"></div></div>
          <span id="micText" style="width: 45px; text-align:right;">0%</span>
        </div>
        <div class="metric-row">
          <span style="width: 110px;">🧘 Độ điềm tĩnh:</span>
          <div class="progress-bar-bg"><div class="progress-bar" id="composureBar"></div></div>
          <span id="composureText" style="width: 45px; text-align:right;">0%</span>
        </div>
        <div class="metric-row">
          <span style="width: 110px;">👁️ Eye Contact:</span>
          <div class="progress-bar-bg"><div class="progress-bar" id="eyeBar" style="background: #a855f7"></div></div>
          <span id="eyeText" style="width: 45px; text-align:right;">0%</span>
        </div>

        <div class="btn-row">
          <button class="btn-secondary" id="camBtn" onclick="startCamera()">📷 Bật Camera & Mic</button>
          <button class="btn-primary" id="startBtn" onclick="startDebateTurn()" disabled>🎙️ Bắt đầu Lượt nói</button>
          <button class="btn-danger" id="stopBtn" onclick="stopDebateTurn()" disabled>⏹️ Dừng & Phân tích</button>
        </div>

        <div class="btn-row">
          <button class="btn-secondary" id="sampleBtn" onclick="runSampleAudioTest()">🧪 Test nhanh bằng File Mẫu (debate_audio.wav + DeepFace)</button>
        </div>

        <div class="status-log" id="statusLog">Trạng thái: Sẵn sàng. Bạn có thể Bật Camera/Mic hoặc bấm "Test nhanh bằng File Mẫu".</div>
      </div>

      <div class="card">
        <h2>⚖️ 2. Ngữ cảnh Tranh biện & Chấm điểm AI Evaluator</h2>
        <label>Chủ đề tranh biện (Motion)</label>
        <input type="text" id="motion" value="THBT mạng xã hội gây hại nhiều hơn lợi">

        <div class="form-row">
          <div>
            <label>Phe của bạn (Side)</label>
            <select id="side">
              <option value="pro">Ủng hộ (PRO)</option>
              <option value="con">Phản đối (CON)</option>
            </select>
          </div>
          <div>
            <label>Giai đoạn (Stage)</label>
            <select id="stage">
              <option value="opening">Mở đầu (Opening)</option>
              <option value="rebuttal" selected>Phản biện (Rebuttal)</option>
              <option value="closing">Kết luận (Closing)</option>
            </select>
          </div>
        </div>

        <label>Lập luận đối phương vừa nêu (Tùy chọn — để trống nếu phát biểu độc lập)</label>
        <textarea id="opponentText" placeholder="Chỉ nhập nếu bạn đang phản biện lại một luận điểm cụ thể của đối phương..."></textarea>

        <label>Văn bản nhận diện từ giọng nói (Faster-Whisper STT — có thể chỉnh sửa trước khi chấm)</label>
        <textarea id="transcriptInput" placeholder="Khi bạn nói xong hoặc chạy File Mẫu, văn bản Faster-Whisper sẽ tự động điền vào đây...">Kính thưa ban giám khảo, tôi xin trình bày luận điểm tranh biện: Mạng xã hội mặc dù mang lại khả năng kết nối nhanh chóng nhưng lại làm suy giảm nghiêm trọng thời gian tương tác trực tiếp và gây ảnh hưởng tiêu cực đến sức khỏe tinh thần của giới trẻ.</textarea>

        <div class="btn-row">
          <button class="btn-success" id="evalFullBtn" onclick="evaluateFullDebateTurn()">🚀 Chấm điểm Toàn diện (Phong thái DeepFace + Nội dung AI Evaluator)</button>
        </div>
      </div>
    </div>

    <!-- CỘT PHẢI: BÁO CÁO PHONG THÁI (VISION + VOICE) & ĐIỂM LẬP LUẬN -->
    <div>
      <div class="card">
        <h2>📊 3. Kết quả Đánh giá Phong thái (Multimodal Vision & Voice Report)</h2>
        <div class="kpi-grid">
          <div class="kpi-box">
            <div class="kpi-val" id="kpiDemeanor">--</div>
            <div class="kpi-lbl">Phong thái (/100)</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-val" id="kpiComposure">--</div>
            <div class="kpi-lbl">Điềm tĩnh (%)</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-val" id="kpiWpm">--</div>
            <div class="kpi-lbl">Tốc độ (WPM)</div>
          </div>
          <div class="kpi-box">
            <div class="kpi-val" id="kpiFillers">--</div>
            <div class="kpi-lbl">Từ đệm ngập ngừng</div>
          </div>
        </div>

        <div id="voiceSummaryBox" style="font-size: 13.5px; color: #cbd5e1; margin-bottom: 10px;">
          Hãy thực hiện một lượt nói hoặc nhấn <b>"Test nhanh bằng File Mẫu"</b> để xem báo cáo DeepFace + Faster-Whisper.
        </div>

        <div id="chartContainer"></div>
      </div>

      <div class="card" id="contentEvalCard">
        <h2>🧠 4. Kết quả Chấm điểm Lập luận & Nhận xét (AI Evaluator)</h2>
        <div id="contentEvalBody" style="font-size: 13.5px; color: var(--text-muted);">
          Nhấn <b>"Chấm điểm Toàn diện"</b> để gửi cả văn bản lập luận và gói chỉ số cảm xúc/giọng nói (`delivery_analytics`) sang AI Evaluator.
        </div>
      </div>

      <div class="card">
        <h2>📦 5. Gói JSON `delivery_analytics` chuẩn hóa gửi Backend</h2>
        <pre id="jsonPreview">// Chưa có dữ liệu</pre>
      </div>
    </div>
  </div>

  <script>
    let stream = null;
    let isRecording = false;
    let startTime = 0;
    let timerInterval = null;
    let frameInterval = null;
    let emotionTimeline = [];
    let totalFramesCount = 0;
    let faceDetectedCount = 0;
    let lastMultimodalResult = null;

    // Web Audio API de thu file WAV 16kHz chuan cho Faster-Whisper
    let audioCtx = null;
    let mediaStreamSource = null;
    let scriptProcessor = null;
    let recordedPcmChunks = [];
    let recordingSampleRate = 16000;

    function setStatus(msg) {
      document.getElementById('statusLog').textContent = 'Trạng thái: ' + msg;
    }

    async function checkHealth() {
      try {
        const res = await fetch('/health');
        const data = await res.json();
        const badge = document.getElementById('modelBadge');
        badge.textContent = `✅ DeepFace (${data.models?.detector_backend || 'yunet'}) + Whisper Ready`;
      } catch (e) {
        document.getElementById('modelBadge').textContent = '⚠️ Không kết nối được /health';
      }
    }

    async function startCamera() {
      try {
        setStatus('Đang mở Camera & Microphone...');
        stream = await navigator.mediaDevices.getUserMedia({
          video: { width: 640, height: 480 },
          audio: true
        });
        const video = document.getElementById('webcam');
        video.srcObject = stream;
        await new Promise(r => video.onloadedmetadata = r);
        const canvas = document.getElementById('overlay');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;

        document.getElementById('startBtn').disabled = false;
        setStatus('Camera & Mic đã sẵn sàng! Hãy nhấn "Bắt đầu Lượt nói".');
      } catch (err) {
        setStatus('Không mở được Camera/Mic (' + err.message + '). Bạn vẫn có thể dùng nút "Test nhanh bằng File Mẫu".');
      }
    }

    function encodeWavFromFloat32(samples, sampleRate) {
      const buffer = new ArrayBuffer(44 + samples.length * 2);
      const view = new DataView(buffer);
      const writeString = (offset, str) => {
        for (let i = 0; i < str.length; i++) view.setUint8(offset + i, str.charCodeAt(i));
      };
      writeString(0, 'RIFF');
      view.setUint32(4, 36 + samples.length * 2, true);
      writeString(8, 'WAVE');
      writeString(12, 'fmt ');
      view.setUint32(16, 16, true);
      view.setUint16(20, 1, true);
      view.setUint16(22, 1, true);
      view.setUint32(24, sampleRate, true);
      view.setUint32(28, sampleRate * 2, true);
      view.setUint16(32, 2, true);
      view.setUint16(34, 16, true);
      writeString(36, 'data');
      view.setUint32(40, samples.length * 2, true);
      let offset = 44;
      for (let i = 0; i < samples.length; i++, offset += 2) {
        let s = Math.max(-1, Math.min(1, samples[i]));
        view.setInt16(offset, s < 0 ? s * 0x8000 : s * 0x7FFF, true);
      }
      let binary = '';
      const bytes = new Uint8Array(buffer);
      const chunkSize = 0x8000;
      for (let i = 0; i < bytes.length; i += chunkSize) {
        binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize));
      }
      return 'data:audio/wav;base64,' + btoa(binary);
    }

    async function captureAndAnalyzeFrame() {
      if (!isRecording || !stream) return;
      const video = document.getElementById('webcam');
      if (video. videoWidth === 0) return;

      const tmpCanvas = document.createElement('canvas');
      tmpCanvas.width = 320;
      tmpCanvas.height = 240;
      const tctx = tmpCanvas.getContext('2d');
      tctx.drawImage(video, 0, 0, tmpCanvas.width, tmpCanvas.height);
      const dataUrl = tmpCanvas.toDataURL('image/jpeg', 0.75);
      const elapsed = (Date.now() - startTime) / 1000.0;

      try {
        const res = await fetch('/multimodal/analyze-frame', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ image_base64: dataUrl, timestamp: elapsed })
        });
        if (!res.ok) return;
        const data = await res.json();
        totalFramesCount++;

        const overlay = document.getElementById('overlay');
        const ctx = overlay.getContext('2d');
        ctx.clearRect(0, 0, overlay.width, overlay.height);

        if (data.face_detected && data.region) {
          faceDetectedCount++;
          emotionTimeline.push({
            time: elapsed,
            dominant: data.dominant_emotion,
            scores: data.emotion_scores,
            face_detected: true
          });

          const scaleX = overlay.width / 320;
          const scaleY = overlay.height / 240;
          // Video dang mirror scaleX(-1) nen dao toa do X tren overlay
          const rx = overlay.width - (data.region.x + data.region.w) * scaleX;
          const ry = data.region.y * scaleY;
          const rw = data.region.w * scaleX;
          const rh = data.region.h * scaleY;

          ctx.strokeStyle = '#38bdf8';
          ctx.lineWidth = 3;
          ctx.strokeRect(rx, ry, rw, rh);

          document.getElementById('emotionPill').textContent =
            `🎭 ${data.dominant_emotion.toUpperCase()} (${data.dominant_score.toFixed(0)}%)`;
          document.getElementById('composureBar').style.width = `${data.composure_instant}%`;
          document.getElementById('composureText').textContent = `${data.composure_instant.toFixed(0)}%`;
        } else {
          document.getElementById('emotionPill').textContent = '⚠️ Không thấy mặt';
        }

        const eyeRate = totalFramesCount > 0 ? Math.round((faceDetectedCount / totalFramesCount) * 100) : 0;
        document.getElementById('eyeBar').style.width = `${eyeRate}%`;
        document.getElementById('eyeText').textContent = `${eyeRate}%`;
      } catch (e) {
        console.error(e);
      }
    }

    function startDebateTurn() {
      if (!stream) return;
      isRecording = true;
      startTime = Date.now();
      emotionTimeline = [];
      totalFramesCount = 0;
      faceDetectedCount = 0;
      recordedPcmChunks = [];

      audioCtx = new (window.AudioContext || window.webkitAudioContext)({ sampleRate: 16000 });
      recordingSampleRate = audioCtx.sampleRate;
      mediaStreamSource = audioCtx.createMediaStreamSource(stream);
      scriptProcessor = audioCtx.createScriptProcessor(4096, 1, 1);
      scriptProcessor.onaudioprocess = (e) => {
        if (!isRecording) return;
        const input = e.inputBuffer.getChannelData(0);
        recordedPcmChunks.push(new Float32Array(input));
        let sum = 0;
        for (let i = 0; i < input.length; i++) sum += input[i] * input[i];
        const rms = Math.sqrt(sum / input.length);
        const pct = Math.min(100, Math.round(rms * 400));
        document.getElementById('micBar').style.width = pct + '%';
        document.getElementById('micText').textContent = pct + '%';
      };
      mediaStreamSource.connect(scriptProcessor);
      scriptProcessor.connect(audioCtx.destination);

      document.getElementById('startBtn').disabled = true;
      document.getElementById('stopBtn').disabled = false;
      setStatus('🔴 Đang thu âm & phân tích biểu cảm khuôn mặt bằng DeepFace...');

      timerInterval = setInterval(() => {
        const sec = Math.floor((Date.now() - startTime) / 1000);
        const m = String(Math.floor(sec / 60)).padStart(2, '0');
        const s = String(sec % 60).padStart(2, '0');
        document.getElementById('timerPill').textContent = `⏱️ ${m}:${s}`;
      }, 500);

      frameInterval = setInterval(captureAndAnalyzeFrame, 600);
    }

    async function stopDebateTurn() {
      isRecording = false;
      clearInterval(timerInterval);
      clearInterval(frameInterval);
      document.getElementById('startBtn').disabled = false;
      document.getElementById('stopBtn').disabled = true;

      if (scriptProcessor) scriptProcessor.disconnect();
      if (mediaStreamSource) mediaStreamSource.disconnect();
      if (audioCtx) await audioCtx.close();

      const elapsed = Math.max(1.0, (Date.now() - startTime) / 1000.0);
      let totalLen = recordedPcmChunks.reduce((acc, c) => acc + c.length, 0);
      let merged = new Float32Array(totalLen);
      let offset = 0;
      for (const chunk of recordedPcmChunks) {
        merged.set(chunk, offset);
        offset += chunk.length;
      }
      const wavBase64 = encodeWavFromFloat32(merged, recordingSampleRate);

      setStatus('⏳ Đang chạy Faster-Whisper & tổng hợp báo cáo DeepFace...');
      try {
        const res = await fetch('/multimodal/analyze-turn', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            audio_base64: wavBase64,
            emotion_timeline: emotionTimeline,
            total_frames_captured: totalFramesCount,
            duration_seconds: elapsed,
            include_report_chart: true
          })
        });
        const data = await res.json();
        renderMultimodalResult(data);
        setStatus('✅ Đã phân tích xong lượt nói! Bạn có thể bấm "Chấm điểm Toàn diện" bên dưới.');
      } catch (err) {
        setStatus('❌ Lỗi khi phân tích lượt nói: ' + err.message);
      }
    }

    async function runSampleAudioTest() {
      const btn = document.getElementById('sampleBtn');
      btn.disabled = true;
      setStatus('⏳ Đang phân tích file debate_audio.wav bằng Faster-Whisper + DeepFace...');
      try {
        const res = await fetch('/multimodal/demo-sample-audio', { method: 'POST' });
        const data = await res.json();
        renderMultimodalResult(data);
        setStatus('✅ Đã chạy thành công trên file mẫu debate_audio.wav!');
      } catch (err) {
        setStatus('❌ Lỗi khi chạy file mẫu: ' + err.message);
      } finally {
        btn.disabled = false;
      }
    }

    function renderMultimodalResult(data) {
      lastMultimodalResult = data;
      document.getElementById('kpiDemeanor').textContent = data.overall_demeanor_score.toFixed(1);
      document.getElementById('kpiComposure').textContent = data.facial.composure_score.toFixed(1) + '%';
      document.getElementById('kpiWpm').textContent = data.voice.wpm.toFixed(1);
      document.getElementById('kpiFillers').textContent = data.voice.filler_count;

      if (data.voice.transcript_text) {
        document.getElementById('transcriptInput').value = data.voice.transcript_text;
      }

      document.getElementById('voiceSummaryBox').innerHTML = `
        <div>🗣️ <b>Đánh giá tốc độ nói:</b> ${data.voice.pace_evaluation} (${data.voice.word_count} từ / ${data.voice.duration_seconds}s — Điểm tốc độ: ${data.voice.pace_score}/100)</div>
        <div>🛑 <b>Độ trôi chảy (Fluency):</b> ${data.voice.fluency_score}/100 (Phát hiện ${data.voice.filler_count} từ đệm ngập ngừng)</div>
        <div>🎭 <b>Cảm xúc chủ đạo:</b> <span style="color:var(--accent);font-weight:700;">${data.facial.dominant_emotion.toUpperCase()}</span> | Eye Contact: <b>${data.facial.eye_contact_rate}%</b></div>
      `;

      if (data.report_chart_base64) {
        document.getElementById('chartContainer').innerHTML = `
          <img class="report-img" src="${data.report_chart_base64}" alt="Debate Multimodal Report Chart" />
        `;
      }

      document.getElementById('jsonPreview').textContent = JSON.stringify(data.delivery_analytics, null, 2);
    }

    async function evaluateFullDebateTurn() {
      const btn = document.getElementById('evalFullBtn');
      btn.disabled = true;
      setStatus('⏳ Đang gửi dữ liệu sang AI Evaluator để chấm điểm Nội dung + Phong thái...');

      const hasRecordedTurn = Boolean(lastMultimodalResult);
      const turnData = hasRecordedTurn ? {
        emotion_timeline: emotionTimeline,
        total_frames_captured: lastMultimodalResult.facial.total_frames_analyzed,
        duration_seconds: lastMultimodalResult.voice.duration_seconds,
        transcript_override: document.getElementById('transcriptInput').value,
        include_report_chart: false
      } : {
        emotion_timeline: [],
        total_frames_captured: 0,
        duration_seconds: 0.0,
        transcript_override: document.getElementById('transcriptInput').value,
        include_report_chart: false
      };

      try {
        const res = await fetch('/multimodal/evaluate-speech', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            motion: document.getElementById('motion').value,
            side: document.getElementById('side').value,
            stage: document.getElementById('stage').value,
            opponent_argument_text: document.getElementById('opponentText').value || null,
            turn_data: turnData,
            existing_multimodal_result: lastMultimodalResult
          })
        });
        const data = await res.json();
        if (!hasRecordedTurn) {
          document.getElementById('voiceSummaryBox').innerHTML =
            '<div style="color:var(--text-muted);">ℹ️ Bạn đang chấm điểm văn bản trực tiếp (không thu Camera/Mic ở Bước 1), nên Mục 3 giữ trống và hệ thống chỉ chấm Điểm Nội dung Lập luận ở Mục 4.</div>';
        }

        const bodyEl = document.getElementById('contentEvalBody');
        if (data.content_evaluation) {
          const ce = data.content_evaluation;
          const critHtml = (ce.criteria || []).map(c => `
            <div class="crit-item">
              <div style="display:flex;justify-content:space-between;font-weight:600;color:#e2e8f0;">
                <span>${c.name}</span>
                <span style="color:var(--accent)">${c.score} / 5</span>
              </div>
              <div style="color:#94a3b8;margin-top:2px;">${c.reasoning}</div>
            </div>
          `).join('');

          bodyEl.innerHTML = `
            <div style="display:flex;align-items:center;justify-content:space-between;background:var(--card-inner);padding:12px 16px;border-radius:8px;margin-bottom:12px;border:1px solid var(--border);">
              <div>
                <div style="font-size:12px;color:var(--text-muted);">ĐIỂM NỘI DUNG LẬP LUẬN (RUBRIC v2_4x25)</div>
                <div style="font-size:13px;color:#e2e8f0;margin-top:4px;">${ce.overall_reasoning}</div>
              </div>
              <div style="font-size:28px;font-weight:800;color:var(--success);min-width:95px;text-align:right;">
                ${Number(ce.overall_score).toFixed(1)}/10
              </div>
            </div>
            ${critHtml}
            <div style="margin-top:10px;">
              <div style="color:var(--success);font-weight:600;">✅ Điểm mạnh:</div>
              <ul style="padding-left:18px;margin-bottom:8px;">${(ce.strengths || []).map(s => `<li>${s}</li>`).join('')}</ul>
              <div style="color:var(--warning);font-weight:600;">⚠️ Điểm cần cải thiện:</div>
              <ul style="padding-left:18px;margin-bottom:8px;">${(ce.weaknesses || []).map(w => `<li>${w}</li>`).join('')}</ul>
              <div style="color:var(--accent);font-weight:600;">💡 Gợi ý cải thiện (Nội dung & Phong thái):</div>
              <ul style="padding-left:18px;">${(ce.suggestions || []).map(sg => `<li>${sg}</li>`).join('')}</ul>
            </div>
          `;
          setStatus('✅ Đã hoàn tất chấm điểm Toàn diện (Phong thái DeepFace + Nội dung AI Evaluator)!');
        } else {
          bodyEl.innerHTML = `
            <div style="background:rgba(239,68,68,0.12);border:1px solid var(--danger);padding:14px;border-radius:8px;color:#fca5a5;">
              <div style="font-weight:700;color:var(--danger);margin-bottom:4px;">❌ Không thể chấm điểm Nội dung Lập luận (AI Evaluator lỗi)</div>
              <div>${data.evaluation_error || 'AI Evaluator không phản hồi'}</div>
            </div>
          `;
          setStatus('❌ Lỗi từ AI Evaluator: ' + (data.evaluation_error || ''));
        }
      } catch (err) {
        setStatus('❌ Lỗi khi gọi /multimodal/evaluate-speech: ' + err.message);
      } finally {
        btn.disabled = false;
      }
    }

    window.onload = checkHealth;
  </script>
</body>
</html>
"""

