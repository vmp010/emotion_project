const API_BASE =
  location.hostname === "localhost" || location.hostname === "127.0.0.1"
    ? "http://100.69.4.127:5000"
    : `${location.protocol}//${location.hostname}:5000`;

const EMOTION_CONFIG = {
  happy:  { emoji: "😊", color: "#4ade80", textColor: "text-green-400" },
  sad:    { emoji: "😢", color: "#fb923c", textColor: "text-orange-400" },
  angry:  { emoji: "😠", color: "#ef4444", textColor: "text-red-500" },
  neutral:{ emoji: "😐", color: "#9ca3af", textColor: "text-gray-400" },
};

const MAX_HISTORY = 60;
let history = { happy: [], sad: [], angry: [], neutral: [], labels: [] };
let chart = null;

function initChart() {
  const ctx = document.getElementById("trend-chart").getContext("2d");
  chart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        { label: "開心", data: [], borderColor: "#4ade80", backgroundColor: "rgba(74,222,128,0.1)", tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: "難過", data: [], borderColor: "#fb923c", backgroundColor: "rgba(251,146,60,0.1)", tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: "憤怒", data: [], borderColor: "#ef4444", backgroundColor: "rgba(239,68,68,0.1)", tension: 0.3, pointRadius: 0, borderWidth: 2 },
        { label: "平靜", data: [], borderColor: "#9ca3af", backgroundColor: "rgba(156,163,175,0.1)", tension: 0.3, pointRadius: 0, borderWidth: 2 },
      ],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: { duration: 200 },
      plugins: { legend: { labels: { color: "#d1d5db", boxWidth: 12, padding: 8 } } },
      scales: {
        x: { ticks: { display: false }, grid: { color: "rgba(75,85,99,0.3)" } },
        y: { min: 0, max: 1, ticks: { color: "#9ca3af", callback: v => (v * 100).toFixed(0) + "%" }, grid: { color: "rgba(75,85,99,0.3)" } },
      },
    },
  });
}

function updateUI(data) {
  const emotion = data.emotion || "unknown";
  const scores = data.scores || {};

  const config = EMOTION_CONFIG[emotion] || { emoji: "🤷", textColor: "text-gray-500" };

  document.getElementById("emotion-emoji").textContent = config.emoji;
  const nameEl = document.getElementById("emotion-name");
  nameEl.textContent = emotion === "unknown" ? "未偵測" : emotion;
  nameEl.className = `text-2xl font-bold ${config.textColor}`;

  const confEl = document.getElementById("emotion-confidence");
  const topScore = scores[emotion];
  confEl.textContent = topScore ? `${(topScore * 100).toFixed(0)}%` : "--%";
  confEl.className = `text-lg mt-1 ${config.textColor}`;

  document.getElementById("fps").textContent = data.fps != null ? data.fps.toFixed(1) : "--";
  const faceEl = document.getElementById("face-status");
  if (data.face_detected) {
    faceEl.textContent = `✅ ${data.face_count}人`;
    faceEl.className = "text-xl font-semibold text-green-400";
  } else {
    faceEl.textContent = "❌ 無";
    faceEl.className = "text-xl font-semibold text-red-400";
  }

  for (const e of ["happy", "sad", "angry", "neutral"]) {
    const pct = scores[e] != null ? Math.round(scores[e] * 100) : 0;
    const bar = document.querySelector(`#bar-${e} div div`);
    const pctEl = document.getElementById(`pct-${e}`);
    if (bar) bar.style.width = pct + "%";
    if (pctEl) pctEl.textContent = pct + "%";
  }
}

function updateChart(data) {
  const scores = data.scores || {};
  const now = new Date();
  const label = now.getHours().toString().padStart(2, "0") + ":" + now.getMinutes().toString().padStart(2, "0") + ":" + now.getSeconds().toString().padStart(2, "0");

  for (const e of ["happy", "sad", "angry", "neutral"]) {
    history[e].push(scores[e] || 0);
    if (history[e].length > MAX_HISTORY) history[e].shift();
  }
  history.labels.push(label);
  if (history.labels.length > MAX_HISTORY) history.labels.shift();

  if (!chart) return;
  chart.data.labels = history.labels;
  chart.data.datasets[0].data = history.happy;
  chart.data.datasets[1].data = history.sad;
  chart.data.datasets[2].data = history.angry;
  chart.data.datasets[3].data = history.neutral;
  chart.update("none");
}

function connectSSE() {
  const evtSource = new EventSource(API_BASE + "/api/stream");

  evtSource.onmessage = function (event) {
    try {
      const data = JSON.parse(event.data);
      updateUI(data);
      updateChart(data);
    } catch (e) {
      console.error("SSE parse error:", e);
    }
  };

  evtSource.onerror = function () {
    document.getElementById("connection-status").className = "text-xl font-semibold text-red-400";
    document.getElementById("connection-status").textContent = "🔴";
    evtSource.close();
    setTimeout(connectSSE, 3000);
  };

  evtSource.onopen = function () {
    document.getElementById("connection-status").className = "text-xl font-semibold text-green-400";
    document.getElementById("connection-status").textContent = "🟢";
  };
}

document.addEventListener("DOMContentLoaded", function () {
  initChart();
  connectSSE();
});
