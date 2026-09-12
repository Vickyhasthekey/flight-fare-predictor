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

function setupCombobox(fieldId, otherFieldId) {
  const field = document.getElementById(`${fieldId}-field`);
  const input = document.getElementById(fieldId);
  const hidden = document.getElementById(`${fieldId}-code`);
  const list = document.getElementById(`${fieldId}-list`);
  let activeIndex = -1;

  function otherCode() {
    return document.getElementById(`${otherFieldId}-code`).value;
  }

  function render(query) {
    const q = query.trim().toLowerCase();
    const exclude = otherCode();
    const matches = AIRPORTS.filter(
      (a) => a.code !== exclude && (a.city.toLowerCase().includes(q) || a.code.toLowerCase().includes(q))
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
    const otherHidden = document.getElementById(`${otherFieldId}-code`);
    if (otherHidden.value === airport.code) {
      otherHidden.value = "";
      document.getElementById(otherFieldId).value = "";
    }
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

setupCombobox("origin", "destination");
setupCombobox("destination", "origin");

function localISODate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

const flightDateInput = document.getElementById("flightDate");
{
  const today = new Date();
  const min = new Date(today);
  min.setDate(min.getDate() + 1);
  const max = new Date(today);
  max.setDate(max.getDate() + 60);
  flightDateInput.min = localISODate(min);
  flightDateInput.max = localISODate(max);
}

const form = document.getElementById("search-form");
const submitBtn = document.getElementById("submit-btn");
const resultCard = document.getElementById("result");
const errorCard = document.getElementById("error");
const badge = document.getElementById("result-badge");
const message = document.getElementById("result-message");
const canvas = document.getElementById("price-chart");

form.addEventListener("submit", async (e) => {
  e.preventDefault();
  resultCard.classList.add("hidden");
  errorCard.classList.add("hidden");

  const origin = document.getElementById("origin-code").value;
  const destination = document.getElementById("destination-code").value;
  const flightDate = document.getElementById("flightDate").value;
  const currentPriceRaw = document.getElementById("currentPrice").value.trim();
  const currentPrice = currentPriceRaw === "" ? null : Number(currentPriceRaw);
  const stops = document.getElementById("stops").value;

  if (!origin || !destination) {
    showError("Please pick both airports from the dropdown list.");
    return;
  }

  if (origin === destination) {
    showError("Origin and destination must be different airports.");
    return;
  }

  if (currentPriceRaw !== "" && !(currentPrice > 0)) {
    showError("Enter today's fare as a positive number, or leave it blank.");
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = currentPriceRaw === "" ? "Looking up today's fare…" : "Predicting...";

  try {
    const res = await fetch("/api/predict", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ origin, destination, flightDate, currentPrice, stops }),
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

function formatDate(iso) {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function showResult(data) {
  resultCard.classList.remove("hidden");
  badge.textContent = data.status === "buy_now" ? "Buy now" : "Wait & save";
  badge.className = "badge " + (data.status === "buy_now" ? "buy-now" : "wait");
  message.textContent = data.message;

  if (data.curve && data.curve.length) {
    drawChart(data);
  }
}

function drawChart(data) {
  const { curve, days_left: daysLeft } = data;
  const ctx = canvas.getContext("2d");
  const w = canvas.width, h = canvas.height;
  const padding = { top: 20, right: 20, bottom: 30, left: 50 };
  ctx.clearRect(0, 0, w, h);

  // only chart the remaining window (today through departure), oldest-first for a left-to-right timeline
  const points = curve.filter(p => p.days_before_departure <= daysLeft)
                       .sort((a, b) => b.days_before_departure - a.days_before_departure);
  if (points.length < 2) return;

  const idxOf = (days) => points.findIndex(p => p.days_before_departure === days);

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

  // shaded buy window, drawn first so the price line sits on top of it -
  // this exists for buy_now too (the window just happens to include today)
  {
    const startIdx = idxOf(data.buy_window_start_days);
    const endIdx = idxOf(data.buy_window_end_days);
    if (startIdx !== -1 && endIdx !== -1) {
      const x1 = xFor(startIdx), x2 = xFor(endIdx);
      const boxLeft = Math.min(x1, x2);
      const boxWidth = Math.max(Math.abs(x2 - x1), 10);
      ctx.fillStyle = "rgba(46, 158, 107, 0.12)";
      ctx.fillRect(boxLeft, padding.top, boxWidth, h - padding.top - padding.bottom);

      ctx.fillStyle = "#2e9e6b";
      ctx.font = "600 11px Inter, sans-serif";
      ctx.textAlign = "center";
      const windowLabel = data.buy_window_start === data.buy_window_end
        ? formatDate(data.best_date)
        : `${formatDate(data.buy_window_start)} – ${formatDate(data.buy_window_end)}`;
      ctx.fillText(`Buy ${windowLabel}`, boxLeft + boxWidth / 2, padding.top + 14);
    }
  }

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

  // x-axis: calendar dates, not "37d out"
  ctx.textAlign = "left";
  ctx.fillText(formatDate(data.today), padding.left, h - padding.bottom + 20);
  ctx.textAlign = "right";
  ctx.fillText(formatDate(data.flight_date || data.buy_window_end), w - padding.right, h - padding.bottom + 20);

  // "Today" marker
  const todayX = xFor(0), todayY = yFor(points[0].predicted_fare);
  ctx.beginPath();
  ctx.arc(todayX, todayY, 5, 0, Math.PI * 2);
  ctx.fillStyle = "#2f6fb0";
  ctx.fill();
  ctx.strokeStyle = "#ffffff";
  ctx.lineWidth = 2;
  ctx.stroke();

  ctx.font = "600 12px Inter, sans-serif";
  const todayText = `Today · ${formatDate(data.today)}`;
  const todayW = ctx.measureText(todayText).width;
  const minLabelY = padding.top + 28;
  const maxLabelY = h - padding.bottom - 6;
  const clampY = (y) => Math.min(Math.max(y, minLabelY), maxLabelY);
  const todayLX = todayX + 8;
  const todayLY = clampY(todayY - 12);
  ctx.fillStyle = "#2f6fb0";
  ctx.textAlign = "left";
  ctx.fillText(todayText, todayLX, todayLY);

  // lowest-price day: skip the label if it is today; otherwise keep it off Today's text
  if (data.best_day !== daysLeft) {
    const bestIdx = idxOf(data.best_day);
    if (bestIdx !== -1) {
      const bx = xFor(bestIdx), by = yFor(points[bestIdx].predicted_fare);

      ctx.save();
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = "#d98a2f";
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.moveTo(bx, by);
      ctx.lineTo(bx, h - padding.bottom);
      ctx.stroke();
      ctx.restore();

      ctx.beginPath();
      ctx.arc(bx, by, 4.5, 0, Math.PI * 2);
      ctx.fillStyle = "#d98a2f";
      ctx.fill();
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 1.5;
      ctx.stroke();

      const lowestText = `Lowest · ${formatDate(data.best_date)}`;
      const lowestW = ctx.measureText(lowestText).width;
      const nearRightEdge = bx > w - padding.right - 100;
      let lowAlign = nearRightEdge ? "right" : "left";
      let lowX = nearRightEdge ? bx - 8 : bx + 8;
      let lowY = clampY(by - 12);

      const box = (x, y, width, align) => {
        const left = align === "right" ? x - width : x;
        return { left, right: left + width, y };
      };
      const collides = (a, b) =>
        Math.abs(a.y - b.y) < 14 && a.left < b.right + 8 && b.left < a.right + 8;

      const todayBox = box(todayLX, todayLY, todayW, "left");
      if (collides(todayBox, box(lowX, lowY, lowestW, lowAlign))) {
        lowAlign = "left";
        lowX = todayLX + todayW + 12;
        lowY = todayLY;
        if (lowX + lowestW > w - padding.right) {
          lowX = todayLX;
          lowY = clampY(todayLY + 16);
          if (collides(todayBox, box(lowX, lowY, lowestW, "left"))) {
            lowY = clampY(todayLY - 16);
          }
        }
      }

      ctx.fillStyle = "#d98a2f";
      ctx.font = "600 12px Inter, sans-serif";
      ctx.textAlign = lowAlign;
      ctx.fillText(lowestText, lowX, lowY);
    }
  }
}
