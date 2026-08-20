const form = document.getElementById("search-form");
const submitBtn = document.getElementById("submit-btn");
const resultCard = document.getElementById("result");
const errorCard = document.getElementById("error");
const badge = document.getElementById("result-badge");
const message = document.getElementById("result-message");
const detail = document.getElementById("result-detail");
const canvas = document.getElementById("price-chart");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  resultCard.classList.add("hidden");
  errorCard.classList.add("hidden");
  submitBtn.disabled = true;
  submitBtn.textContent = "Predicting...";

  const origin = document.getElementById("origin").value.trim().toUpperCase();
  const destination = document.getElementById("destination").value.trim().toUpperCase();
  const flightDate = document.getElementById("flightDate").value;

  try {
    const res = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origin, destination, flightDate }),
    });
    const data = await res.json();

    if (!res.ok || data.status === "error" || data.status === "too_far") {
      showError(data.message || "Something went wrong. Please try again.");
      return;
    }

    showResult(data);
  } catch (err) {
    showError("Could not reach the prediction service. Please try again.");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Predict";
  }
});

function showError(msg) {
  errorCard.classList.remove("hidden");
  document.getElementById("error-message").textContent = msg;
}

function showResult(data) {
  resultCard.classList.remove("hidden");
  badge.textContent = data.status === "buy_now" ? "Buy now" : "Wait & save";
  badge.className = "badge " + (data.status === "buy_now" ? "buy-now" : "wait");
  message.textContent = data.message;

  if (data.status === "wait") {
    detail.textContent = `Current: $${data.current_price} -> Predicted best: $${data.expected_best_price} in ${data.wait_days} day(s)`;
  } else {
    detail.textContent = `Predicted price: $${data.current_price}`;
  }

  if (data.curve && data.curve.length) {
    drawChart(data.curve, data.days_left);
  }
}

function drawChart(curve, daysLeft) {
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  const padding = { top: 20, right: 20, bottom: 30, left: 50 };
  ctx.clearRect(0, 0, w, h);

  // only chart the remaining window (today through departure), oldest-first for a left-to-right timeline
  const points = curve.filter(p => p.days_before_departure <= daysLeft)
                       .sort((a, b) => b.days_before_departure - a.days_before_departure);
  if (points.length < 2) return;

  const prices = points.map(p => p.predicted_fare);
  const minP = Math.min(...prices), maxP = Math.max(...prices);
  const priceRange = (maxP - minP) || 1;

  const xFor = (i) => padding.left + (i / (points.length - 1)) * (w - padding.left - padding.right);
  const yFor = (price) => padding.top + (1 - (price - minP) / priceRange) * (h - padding.top - padding.bottom);

  // axes
  ctx.strokeStyle = "#cfe8fb";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(padding.left, padding.top);
  ctx.lineTo(padding.left, h - padding.bottom);
  ctx.lineTo(w - padding.right, h - padding.bottom);
  ctx.stroke();

  // price line
  ctx.strokeStyle = "#4a90d9";
  ctx.lineWidth = 2.5;
  ctx.beginPath();
  points.forEach((p, i) => {
    const x = xFor(i), y = yFor(p.predicted_fare);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // fill under the line
  ctx.lineTo(xFor(points.length - 1), h - padding.bottom);
  ctx.lineTo(xFor(0), h - padding.bottom);
  ctx.closePath();
  ctx.fillStyle = "rgba(74, 144, 217, 0.08)";
  ctx.fill();

  // y-axis labels
  ctx.fillStyle = "#5b6b7a";
  ctx.font = "12px Inter, sans-serif";
  ctx.textAlign = "right";
  ctx.fillText(`$${Math.round(maxP)}`, padding.left - 8, padding.top + 4);
  ctx.fillText(`$${Math.round(minP)}`, padding.left - 8, h - padding.bottom);

  // x-axis labels (first and last day)
  ctx.textAlign = "left";
  ctx.fillText(`${points[0].days_before_departure}d out`, padding.left, h - padding.bottom + 20);
  ctx.textAlign = "right";
  ctx.fillText("Departure", w - padding.right, h - padding.bottom + 20);

  // turning point: the cheapest day in the window - prices are predicted to
  // climb after this, so mark it explicitly instead of leaving it implicit
  let minIdx = 0;
  points.forEach((p, i) => { if (p.predicted_fare < points[minIdx].predicted_fare) minIdx = i; });
  const turningPoint = points[minIdx];
  const tx = xFor(minIdx), ty = yFor(turningPoint.predicted_fare);

  ctx.save();
  ctx.setLineDash([4, 4]);
  ctx.strokeStyle = "#d98a2f";
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(tx, ty);
  ctx.lineTo(tx, h - padding.bottom);
  ctx.stroke();
  ctx.restore();

  ctx.beginPath();
  ctx.arc(tx, ty, 4.5, 0, Math.PI * 2);
  ctx.fillStyle = "#d98a2f";
  ctx.fill();
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 1.5;
  ctx.stroke();

  const nearRightEdge = tx > w - padding.right - 100;
  ctx.fillStyle = "#d98a2f";
  ctx.font = "600 12px Inter, sans-serif";
  ctx.textAlign = nearRightEdge ? "right" : "left";
  const labelX = nearRightEdge ? tx - 8 : tx + 8;
  const labelY = Math.max(ty - 10, padding.top + 10);
  const label = minIdx < points.length - 1
    ? `Rises after ${turningPoint.days_before_departure}d out`
    : `Lowest: $${Math.round(turningPoint.predicted_fare)}`;
  ctx.fillText(label, labelX, labelY);
}
