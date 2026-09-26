DEMO_HTML = """<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<title>ADPP - Demo AI Evaluator</title>
<style>
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, Segoe UI, Roboto, Arial, sans-serif;
    max-width: 780px; margin: 40px auto; padding: 0 20px;
    background: #f7f9fc; color: #1a1a1a;
  }
  h1 { color: #1f4e79; font-size: 22px; }
  .card {
    background: #fff; border: 1px solid #e0e4ea; border-radius: 10px;
    padding: 20px; margin-bottom: 16px;
  }
  label { display: block; font-weight: 600; margin: 12px 0 4px; font-size: 14px; }
  input[type=text], select, textarea {
    width: 100%; padding: 8px 10px; border: 1px solid #ccd3dc; border-radius: 6px;
    font-size: 14px; font-family: inherit;
  }
  textarea { min-height: 80px; resize: vertical; }
  .row { display: flex; gap: 12px; }
  .row > div { flex: 1; }
  button {
    margin-top: 16px; background: #1f4e79; color: #fff; border: none;
    padding: 10px 20px; border-radius: 6px; font-size: 15px; cursor: pointer;
  }
  button:disabled { background: #9aa; cursor: wait; }
  .score-big { font-size: 42px; font-weight: 700; color: #1f4e79; }
  .score-label { color: #666; font-size: 13px; }
  .crit-row { display: flex; justify-content: space-between; padding: 8px 0; border-bottom: 1px solid #eee; }
  .crit-name { font-weight: 600; width: 140px; }
  .crit-bar-bg { flex: 1; background: #eee; border-radius: 4px; height: 8px; margin: 6px 0; overflow: hidden; }
  .crit-bar { background: #1f4e79; height: 100%; }
  .crit-reason { font-size: 13px; color: #444; margin-top: 4px; }
  ul { margin: 6px 0; padding-left: 20px; }
  .strength { color: #2e7d32; }
  .weakness { color: #c62828; }
  .suggestion { color: #1565c0; }
  #error { color: #c62828; font-weight: 600; }
</style>
</head>
<body>
  <h1>🎤 ADPP — Demo AI Evaluator</h1>

  <div class="card">
    <label>Motion (chủ đề tranh biện)</label>
    <input type="text" id="motion" value="THBT mạng xã hội gây hại nhiều hơn lợi">

    <div class="row">
      <div>
        <label>Phía đứng</label>
        <select id="side">
          <option value="pro">Ủng hộ (Pro)</option>
          <option value="con">Phản đối (Con)</option>
        </select>
      </div>
      <div>
        <label>Giai đoạn</label>
        <select id="stage">
          <option value="opening">Mở đầu</option>
          <option value="rebuttal" selected>Phản biện</option>
          <option value="closing">Kết luận</option>
        </select>
      </div>
    </div>

    <label>Lập luận của đối phương (không bắt buộc)</label>
    <textarea id="opponent">Mạng xã hội giúp kết nối người ở xa nhau.</textarea>

    <label>Lập luận cần chấm điểm</label>
    <textarea id="argument">Mạng xã hội làm giảm thời gian tương tác trực tiếp giữa con người, dẫn đến suy giảm kỹ năng giao tiếp xã hội ở giới trẻ.</textarea>

    <button id="submitBtn" onclick="runEvaluation()">Chấm điểm</button>
    <div id="error"></div>
  </div>

  <div id="result"></div>

<script>
async function runEvaluation() {
  const btn = document.getElementById('submitBtn');
  const errorEl = document.getElementById('error');
  const resultEl = document.getElementById('result');
  errorEl.textContent = '';
  resultEl.innerHTML = '';
  btn.disabled = true;
  btn.textContent = 'Đang chấm điểm...';

  const payload = {
    motion: document.getElementById('motion').value,
    side: document.getElementById('side').value,
    stage: document.getElementById('stage').value,
    argument_text: document.getElementById('argument').value,
    opponent_argument_text: document.getElementById('opponent').value || null,
  };

  try {
    const res = await fetch('/evaluate', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const errBody = await res.json().catch(() => ({}));
      throw new Error(errBody.detail ? JSON.stringify(errBody.detail) : ('HTTP ' + res.status));
    }
    const data = await res.json();
    render(data);
  } catch (e) {
    errorEl.textContent = 'Lỗi: ' + e.message;
  } finally {
    btn.disabled = false;
    btn.textContent = 'Chấm điểm';
  }
}

function render(data) {
  const critHtml = data.criteria.map(c => `
    <div class="crit-row" style="flex-direction: column;">
      <div style="display:flex; justify-content:space-between;">
        <span class="crit-name">${c.name}</span>
        <span>${c.score} / 5</span>
      </div>
      <div class="crit-bar-bg"><div class="crit-bar" style="width:${c.score*20}%"></div></div>
      <div class="crit-reason">${c.reasoning}</div>
    </div>
  `).join('');

  const listHtml = (items, cls) => items && items.length
    ? `<ul>${items.map(i => `<li class="${cls}">${i}</li>`).join('')}</ul>`
    : '<p style="color:#999">Không có</p>';

  document.getElementById('result').innerHTML = `
    <div class="card" style="text-align:center;">
      <div class="score-big">${data.overall_score.toFixed(1)} / 10</div>
      <div class="score-label">Điểm tổng</div>
    </div>
    <div class="card">
      <h3>Chi tiết theo tiêu chí</h3>
      ${critHtml}
    </div>
    <div class="card">
      <h3>✅ Điểm mạnh</h3>
      ${listHtml(data.strengths, 'strength')}
      <h3>⚠️ Điểm cần cải thiện</h3>
      ${listHtml(data.weaknesses, 'weakness')}
      <h3>💡 Gợi ý cải thiện</h3>
      ${listHtml(data.suggestions, 'suggestion')}
    </div>
  `;
}
</script>
</body>
</html>"""
