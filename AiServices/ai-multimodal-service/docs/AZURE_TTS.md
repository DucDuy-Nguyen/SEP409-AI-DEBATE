# AI đối thủ đọc to bằng Azure AI Speech

Phòng tranh biện đọc to bài nói của AI đối thủ theo từng câu, ngay khi câu đó stream xong. Service này giữ key Azure
và trả âm thanh MP3 cho từng câu. Khi không có key hoặc Azure lỗi, FE dùng giọng tiếng Việt của trình duyệt.

## Cấu hình (`.env` của service, không commit)

```env
AZURE_SPEECH_KEY=<key 1 của resource Speech>
AZURE_SPEECH_REGION=japaneast
# Tùy chọn
AZURE_TTS_VOICE=vi-VN-NamMinhNeural
AZURE_TTS_VOICES=vi-VN-NamMinhNeural,vi-VN-HoaiMyNeural
AZURE_TTS_RATE=+5%
```

- **Gói Free F0:** 0,5 triệu ký tự neural/tháng, khoảng 80 phiên tranh biện (mỗi phiên khoảng 6.000 ký tự). Hết
  hạn mức thì Azure trả 429 và FE chuyển sang giọng trình duyệt; không tự tính tiền.
- **Region:** subscription Azure for Students chỉ cho tạo ở `japaneast`, `japanwest`, `centralindia`,
  `indonesiacentral`, `malaysiawest`, trong đó chỉ 3 region đầu có Speech. Dùng `japaneast`.
- **Giọng:** `AZURE_TTS_VOICES` là danh sách giọng được phép chọn, để endpoint không thành cửa gọi tùy ý vào key Speech.
  Giọng có trên region này (2026-11-20): `vi-VN-HoaiMyNeural`, `vi-VN-NamMinhNeural`, và 4 giọng
  `MAI-Voice-2.1` (Flash và HD).

## Endpoint

| Method | Path | Mô tả |
|---|---|---|
| GET | `/multimodal/tts/config` | `{configured, voice, voices, max_chars}`: FE dùng để biết có giọng Azure hay không |
| POST | `/multimodal/tts` | Body `{text, voice?}` (tối đa 1000 ký tự, một câu) → `audio/mpeg` stream. Mã lỗi: 503 chưa có key, 429 Azure giới hạn hoặc hết hạn mức, 502 lỗi khác, 422 văn bản rỗng hoặc quá dài |

Qua Gateway: `/api/multimodal/tts`; qua Vite: `/multimodal/tts`.

## Độ trễ (đo 2026-11-20, từ Việt Nam tới `japaneast`)

| | Âm thanh đầu tiên của 1 câu |
|---|---|
| Mở kết nối mới mỗi câu | 1,2–1,6 giây |
| Giữ kết nối, gọi thẳng Azure (trung vị của 4 lần) | 0,8 giây |
| Qua endpoint của service (cả câu, kết nối giữ sẵn) | khoảng 1,1 giây |

Service dùng chung một `httpx.AsyncClient` để giữ kết nối TLS tới Azure.

Phía FE (`src/services/speechOut.ts`, `AudioSentenceSpeaker`):
- Tải trước tối đa 2 câu, nên câu sau thường đã sẵn khi câu trước phát xong, và không vượt giới hạn số request của gói F0.
- Câu nào tải lỗi hoặc trình duyệt chặn tự phát (chưa có thao tác nào của người dùng) thì câu đó và phần còn lại của
  lượt chuyển sang giọng trình duyệt.

## Test

`tests/test_azure_tts.py` giả lập Azure bằng `httpx.MockTransport`, không gọi mạng.
