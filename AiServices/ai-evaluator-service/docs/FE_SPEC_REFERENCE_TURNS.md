# Spec cho FE: gửi `reference_turns` khi chấm round

**Việc cần làm:** khi gọi `POST /api/evaluate/round`, gửi thêm các lượt của các round trước trong field mới `reference_turns`. Evaluator dùng các lượt này để đối chiếu, không chấm chúng.

**Vì sao:** hiện mỗi round được chấm mà không thấy các round trước. Bài closing của learner phản bác câu đối thủ nói ở round 2, evaluator không thấy câu gốc nên nhận xét sai kiểu "khẳng định mà không có bằng chứng".

**Trạng thái:** phía evaluator nằm trên branch `fix/evaluator-closing-round`, chưa merge. Chờ người phụ trách báo trước khi bật trên môi trường chung.

## Contract

Field tuỳ chọn. Không gửi, hoặc gửi mảng rỗng, thì evaluator hoạt động như cũ. Các field hiện có và response không đổi.

```ts
// src/types/ai.types.ts
export interface ReferenceTurn {
  round: number;            // 1 = opening, 2 = rebuttal, 3 = closing
  order: number;            // thứ tự nói trong cả trận, số nguyên từ 1, không trùng nhau
  speaker: TurnSpeaker;     // "learner" | "opponent"
  side: BackendDebateSide;  // "pro" | "con"
  text: string;             // không rỗng
}

export interface RoundEvaluationRequest {
  motion: string;
  side: BackendDebateSide;
  stage: DebateRoundType;
  turns: ArgumentTurn[];              // chỉ các lượt của round đang chấm, giữ nguyên như hiện tại
  reference_turns?: ReferenceTurn[];  // mới
}
```

## Quy tắc dựng dữ liệu

| Field | Lấy từ đâu | Lưu ý |
|---|---|---|
| Các lượt được gửi | Mọi message có `roundNumber` nhỏ hơn round đang chấm | Không đưa lượt của round đang chấm vào đây |
| `round` | `m.roundNumber` | |
| `order` | Vị trí của message trong `gradedMessages`, cộng 1 | Mảng phải theo thứ tự thời gian |
| `speaker` | `getEvaluatorSpeaker(m)` | Trả về `null` thì bỏ lượt đó, giống `turns` hiện tại |
| `side` | `debaterSide` nếu là `learner`, phe còn lại nếu là `opponent` | Không suy từ `m.side`, vì đó là chuỗi hiển thị |
| `text` | `m.content` | Bỏ lượt rỗng hoặc chỉ có khoảng trắng |

Round opening không có round trước: bỏ field này. Gửi `reference_turns` có phần tử ở opening sẽ bị 422.

## Thay đổi đề xuất

Trong `handleFinishDebate`, `src/pages/debater/DebatePractice/DebateRoom.tsx`, tại đoạn `for (const r of roundsToEvaluate)`:

```ts
const referenceTurnsFor = (round: number): ReferenceTurn[] =>
  gradedMessages.flatMap((m, index): ReferenceTurn[] => {
    const speaker = getEvaluatorSpeaker(m);
    if (!speaker || m.roundNumber >= round || !m.content?.trim()) return [];
    return [{
      round: m.roundNumber,
      order: index + 1,
      speaker,
      side: speaker === "learner" ? debaterSide : aiSide,
      text: m.content,
    }];
  });

// trong vòng lặp
const reference_turns = referenceTurnsFor(r.round);
const fingerprint = JSON.stringify({ turns: r.turns, reference_turns });   // BẮT BUỘC đổi, xem bên dưới
// ...
roundResult = await aiApi.evaluateDebateRound({
  motion: resolvedMotion,
  side: debaterSide,
  stage: r.stage,
  turns: r.turns,
  ...(reference_turns.length > 0 ? { reference_turns } : {}),
});
```

Ba điểm dễ sót:

1. **`fingerprint` phải gồm cả `reference_turns`.** Nếu không, khi retry FE có thể dùng lại kết quả chấm cũ dù ngữ cảnh đã đổi.
2. **`aiSide` chỉ là phe đối diện `debaterSide`.** Tên biến nói về AI nhưng ở P2P nó vẫn đúng là phe đối thủ, nên dùng được. Phải tính `side` từ cùng `debaterSide` đang gửi trong request; lấy từ nguồn khác có thể bị 422.
3. **Chỉ áp dụng cho `/evaluate/round`.** Không thêm vào `/evaluate` hay `/evaluate/session`.

## Ví dụ: closing của learner phe PRO

Thứ tự trong closing là CON rồi PRO, nên `turns` bắt đầu bằng `opponent`.

```json
{
  "motion": "AI nên được kiểm soát chặt chẽ bởi luật pháp quốc tế",
  "side": "pro",
  "stage": "closing",
  "turns": [
    { "speaker": "opponent", "text": "Bài closing của đối thủ" },
    { "speaker": "learner", "text": "Bài closing của learner" }
  ],
  "reference_turns": [
    { "round": 1, "order": 1, "speaker": "learner", "side": "pro", "text": "Opening của learner" },
    { "round": 1, "order": 2, "speaker": "opponent", "side": "con", "text": "Opening của đối thủ" },
    { "round": 2, "order": 3, "speaker": "learner", "side": "pro", "text": "Rebuttal của learner" },
    { "round": 2, "order": 4, "speaker": "opponent", "side": "con", "text": "Rebuttal của đối thủ" }
  ]
}
```

## Lỗi

Payload sai trả **422**, giống các lỗi validate hiện có. Luồng báo lỗi và retry hiện tại của FE dùng lại được. Đây là lỗi của code dựng payload, retry sẽ không tự hết.

| Nguyên nhân | Thông điệp chứa |
|---|---|
| `side` không khớp với `speaker` và `side` của request | `phai la phe` |
| `round` không nhỏ hơn round đang chấm | `khong nam truoc round hien tai` |
| `order` trùng nhau | `bi trung` |
| `text` rỗng, `round` hoặc `order` nhỏ hơn 1 | lỗi validate của field |

## Ảnh hưởng

- **Thời gian chấm:** prompt dài hơn khoảng 1,5 lần ở rebuttal và 2,3 lần ở closing. Nên kiểm tra lại timeout của `aiEvaluatorClient` và thông báo "Đang chấm vòng...".
- **Điểm số:** điểm có thể đổi so với trước trên cùng một bài. Không so sánh trực tiếp điểm chấm có và không có `reference_turns`.
- **Thứ tự triển khai:** không phụ thuộc nhau. Evaluator bản cũ bỏ qua field lạ, nên FE có thể lên trước.

## Tiêu chí nghiệm thu

- [ ] Opening: request không có `reference_turns`.
- [ ] Rebuttal: có đúng 2 lượt của round 1.
- [ ] Closing: có đúng 4 lượt của round 1 và 2, `order` tăng dần, `turns` giữ thứ tự CON rồi PRO.
- [ ] Learner phe CON: lượt của learner có `side: "con"`, đối thủ có `side: "pro"`, không bị 422.
- [ ] Retry sau khi một round lỗi: round đã chấm không gọi lại khi đầu vào không đổi; round có `reference_turns` đổi thì chấm lại.
- [ ] P2P: lượt của đối thủ là người thật mang `speaker: "opponent"`, không bị 422.
