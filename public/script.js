// Airports the model was actually trained on - these are the only valid choices
const AIRPORTS = [
  { code: "ATL", city: "Atlanta" },
  { code: "BOS", city: "Boston" },
  { code: "CLT", city: "Charlotte" },
  { code: "DEN", city: "Denver" },
  { code: "DFW", city: "Dallas/Fort Worth" },
  { code: "DTW", city: "Detroit" },
  { code: "EWR", city: "Newark" },
  { code: "IAD", city: "Washington, D.C. (Dulles)" },
  { code: "JFK", city: "New York (JFK)" },
  { code: "LAX", city: "Los Angeles" },
  { code: "LGA", city: "New York (LaGuardia)" },
  { code: "MIA", city: "Miami" },
  { code: "OAK", city: "Oakland" },
  { code: "ORD", city: "Chicago (O'Hare)" },
  { code: "PHL", city: "Philadelphia" },
  { code: "SFO", city: "San Francisco" },
];

function setupCombobox(fieldId) {
  const field = document.getElementById(`${fieldId}-field`);
  const input = document.getElementById(fieldId);
  const hidden = document.getElementById(`${fieldId}-code`);
  const list = document.getElementById(`${fieldId}-list`);
  let activeIndex = -1;

  function render(query) {
    const q = query.trim().toLowerCase();
    const matches = AIRPORTS.filter(
      (a) => a.city.toLowerCase().includes(q) || a.code.toLowerCase().includes(q)
    );
    list.innerHTML = "";
    activeIndex = -1;

    if (matches.length === 0) {
      const empty = document.createElement("div");
      empty.className = "combobox-empty";
      empty.textContent = "No matching airport - pick from the list";
      list.appendChild(empty);
    } else {
      matches.forEach((a) => {
        const item = document.createElement("div");
        item.className = "combobox-item";
        item.innerHTML = `<span>${a.city}</span><span class="code">${a.code}</span>`;
        item.addEventListener("mousedown", (e) => {
          e.preventDefault(); // keep focus so we don't lose the click before it registers
          select(a);
        });
        list.appendChild(item);
      });
    }
    list.classList.remove("hidden");
  }

  function select(airport) {
    input.value = `${airport.city} (${airport.code})`;
    hidden.value = airport.code;
    list.classList.add("hidden");
  }

  input.addEventListener("focus", () => render(""));
  input.addEventListener("input", () => {
    hidden.value = ""; // typing invalidates any previous selection until they pick again
    render(input.value);
  });

  input.addEventListener("keydown", (e) => {
    const items = list.querySelectorAll(".combobox-item");
    if (e.key === "ArrowDown") {
      e.preventDefault();
      activeIndex = Math.min(activeIndex + 1, items.length - 1);
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      activeIndex = Math.max(activeIndex - 1, 0);
    } else if (e.key === "Enter" && activeIndex >= 0) {
      e.preventDefault();
      items[activeIndex].dispatchEvent(new Event("mousedown"));
      return;
    } else if (e.key === "Escape") {
      list.classList.add("hidden");
      return;
    } else {
      return;
    }
    items.forEach((el, i) => el.classList.toggle("active", i === activeIndex));
  });

  document.addEventListener("click", (e) => {
    if (!field.contains(e.target)) list.classList.add("hidden");
  });
}

setupCombobox("origin");
setupCombobox("destination");

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

  const origin = document.getElementById("origin-code").value;
  const destination = document.getElementById("destination-code").value;
  const flightDate = document.getElementById("flightDate").value;

  if (!origin || !destination) {
    showError("Please pick both airports from the dropdown list.");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "Predicting...";

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
