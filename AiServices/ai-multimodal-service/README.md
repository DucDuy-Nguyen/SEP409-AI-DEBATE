# AI Multimodal Service (DeepFace + Faster-Whisper)

Phân tích phong thái của một lượt nói: khuôn mặt và cảm xúc từ khung hình webcam (DeepFace, bộ phát hiện YuNet), giọng nói tiếng Việt thành văn bản, tốc độ nói và từ đệm (Faster-Whisper). Cổng mặc định 8003.

FE gọi service qua proxy Vite (`/multimodal/*`, `/multimodal-health`) hoặc Gateway (`/api/multimodal/*`). Nút ghi âm trong phòng tranh biện gửi:

- mỗi 600 ms một khung hình 320×240 tới `POST /multimodal/analyze-frame`;
- khi dừng ghi, file webm/opus của trình duyệt tới `POST /multimodal/analyze-turn`.

Chi tiết request và response: [docs/FE_INTEGRATION_GUIDE.md](docs/FE_INTEGRATION_GUIDE.md).

## Chạy local (Windows, Python 3.11)

```powershell
cd AiServices\ai-multimodal-service
python -m venv venv
.\venv\Scripts\python -m pip install -r requirements.txt
.\venv\Scripts\python -m uvicorn app.main:app --port 8003
```

Hoặc chạy `start-all.ps1` ở thư mục gốc repo, script này dùng `venv` ở đây nếu có.

- **Không cần TensorFlow:** `deepface==0.0.105` chạy model bằng onnxruntime.
- **Lần chạy đầu tải model về máy:**
  - DeepFace (YuNet và model cảm xúc, khoảng 6 MB) vào `~/.deepface/weights`;
  - Whisper `small` (khoảng 460 MB) vào cache HuggingFace.

  Sau đó service khởi động trong vài giây.
- **Kiểm tra:** `GET http://localhost:8003/health` phải trả về `deepface_ready` và `whisper_ready` là `true`. Trang thử nhanh: `http://localhost:8003/demo`.
- **Tốc độ trên CPU (máy dev):**
  - một khung hình khoảng 50 ms;
  - 18 giây âm thanh tiếng Việt khoảng 10–12 giây (wav, webm hay mp3 đều được).

## Cấu hình (`.env` hoặc biến môi trường)

| Biến | Mặc định | Ghi chú |
|---|---|---|
| `DETECTOR_BACKEND` | `yunet` | `opencv` (Haar) là phương án dự phòng |
| `YUNET_SCORE_THRESHOLD` | `0.6` | Xem phần dưới |
| `WHISPER_MODEL_SIZE` | `small` | `base` nhanh hơn nhưng kém chính xác hơn với tiếng Việt |
| `PREWARM_MODELS` | `true` | Nạp model khi khởi động |
| `EVALUATOR_SERVICE_URL` | evaluator trên Azure | Dùng cho `POST /multimodal/evaluate-speech` |

### Vì sao `YUNET_SCORE_THRESHOLD` là 0.6

Ngưỡng mặc định của DeepFace là 0.9. Trước khi phát hiện mặt, DeepFace thêm viền 50% quanh ảnh rồi thu ảnh về 640px. Khuôn mặt trong khung webcam vì thế nhỏ đi một nửa và điểm YuNet tụt còn khoảng 0.76–0.87. Với ngưỡng 0.9, gần như mọi khung hình đều báo `face_detected: false`.

Ở ngưỡng 0.6:

- mặt rộng 50–145px trong khung 640×480 đều được phát hiện;
- khung trống và khung nhiễu không bị nhận nhầm là có mặt;
- `analyze_single_frame` còn lọc thêm `face_confidence >= 0.45` và loại khung bao gần trọn ảnh (DeepFace trả về khung này khi không thấy mặt).

## Test

```powershell
.\venv\Scripts\python -m pytest -q tests
```

Repo không kèm ảnh mặt người thật, nên test phát hiện mặt cỡ webcam là bước **kiểm tra thủ công**: đặt `MULTIMODAL_TEST_FACE` trỏ tới một ảnh chân dung rồi chạy. Nếu không đặt, test đó tự bỏ qua; CI chỉ kiểm tra ngưỡng đã được áp dụng và khung trống không có mặt.

Nếu máy có thư mục `D:\Emotion-Test\deepface`, `analyzer.py` sẽ ưu tiên import DeepFace từ đó thay cho bản `0.0.105` đã ghim. Xem `deepface_source` trong `GET /health` để biết đang dùng bản nào.

`POST /multimodal/demo-sample-audio` đọc file mẫu `D:\Emotion-Test\deepface\debate_audio.wav`. Nếu không có file, endpoint chỉ dùng transcript mẫu.
