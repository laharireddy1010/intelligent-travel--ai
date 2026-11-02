const form = document.getElementById("planner-form");
const startSelect = document.getElementById("start");
const destinationSelect = document.getElementById("destination");
const waypointSelect = document.getElementById("waypoint-select");
const waypointList = document.getElementById("waypoint-list");
const stopCities = [];
let currentResult = null;
let network = null;

const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (char) => ({
  "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"
})[char]);
const fmt = (n) => new Intl.NumberFormat("en-IN", { maximumFractionDigits: 0 }).format(n);
const durationText = (hours) => {
  const mins = Math.round(hours * 60);
  const h = Math.floor(mins / 60);
  const m = mins % 60;
  return h ? `${h}h ${m}m` : `${m}m`;
};
const preferenceLabel = (value) => ({ distance: "SHORTEST", cost: "LOWEST COST", time: "FASTEST" }[value]);

document.querySelectorAll(".preference-option input").forEach((input) => {
  input.addEventListener("change", () => {
    document.querySelectorAll(".preference-option").forEach((item) => item.classList.remove("selected"));
    input.closest(".preference-option").classList.add("selected");
  });
});

document.getElementById("swap-cities").addEventListener("click", () => {
  const previous = startSelect.value;
  startSelect.value = destinationSelect.value;
  destinationSelect.value = previous;
});

function renderStops() {
  waypointList.innerHTML = stopCities.map((city, index) =>
    `<span class="stop-chip">${escapeHtml(city)}<button type="button" data-remove="${index}" aria-label="Remove ${escapeHtml(city)}">×</button></span>`
  ).join("");
}
document.getElementById("add-stop").addEventListener("click", () => {
  const city = waypointSelect.value;
  if (!city) return;
  if (stopCities.length >= 3) {
    document.getElementById("form-error").textContent = "Choose up to 3 optional stops.";
    return;
  }
  if ([startSelect.value, destinationSelect.value, ...stopCities].includes(city)) {
    document.getElementById("form-error").textContent = "A city can only appear once in your journey.";
    return;
  }
  stopCities.push(city);
  waypointSelect.value = "";
  document.getElementById("form-error").textContent = "";
  renderStops();
});
waypointList.addEventListener("click", (event) => {
  const button = event.target.closest("[data-remove]");
  if (button) {
    stopCities.splice(Number(button.dataset.remove), 1);
    renderStops();
  }
});

document.getElementById("reset-button").addEventListener("click", () => {
  startSelect.value = "Madanapalle";
  destinationSelect.value = "Kochi";
  stopCities.length = 0;
  renderStops();
  document.querySelector('input[name="preference"][value="distance"]').checked = true;
  document.querySelectorAll(".preference-option").forEach((item, index) => item.classList.toggle("selected", index === 0));
  document.getElementById("form-error").textContent = "";
  document.getElementById("results").classList.add("hidden");
  currentResult = null;
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  const error = document.getElementById("form-error");
  error.textContent = "";
  const button = document.getElementById("plan-button");
  button.disabled = true;
  button.innerHTML = "Searching the road network…";
  try {
    const response = await fetch("/api/plan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        start: startSelect.value,
        destination: destinationSelect.value,
        waypoints: [...stopCities],
        preference: document.querySelector('input[name="preference"]:checked').value
      })
    });
    const result = await response.json();
    if (!response.ok) throw new Error(result.error || "Could not calculate a route.");
    currentResult = result;
    renderResults(result);
    document.getElementById("results").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (err) {
    error.textContent = err.message || "Unable to contact the local planner.";
  } finally {
    button.disabled = false;
    button.innerHTML = 'Find my best route <span>✦</span>';
  }
});

function coordsForRoute(path) {
  const all = network?.cities || [];
  const latitudes = all.map((city) => city.lat);
  const longitudes = all.map((city) => city.lon);
  const minLat = Math.min(...latitudes), maxLat = Math.max(...latitudes);
  const minLon = Math.min(...longitudes), maxLon = Math.max(...longitudes);
  const x = (name) => {
    const city = all.find((item) => item.name === name);
    return 26 + (city.lon - minLon) / (maxLon - minLon || 1) * 368;
  };
  const y = (name) => {
    const city = all.find((item) => item.name === name);
    return 28 + (maxLat - city.lat) / (maxLat - minLat || 1) * 112;
  };
  return { all, x, y };
}
function renderRouteMap(path) {
  if (!network || !path.length) return "";
  const { x, y } = coordsForRoute(path);
  const roads = network.roads.map((road) => {
    const used = path.some((city, index) => index < path.length - 1 &&
      ((city === road.from && path[index + 1] === road.to) || (city === road.to && path[index + 1] === road.from)));
    return `<line x1="${x(road.from)}" y1="${y(road.from)}" x2="${x(road.to)}" y2="${y(road.to)}" class="${used ? "svg-road-used" : "svg-road-alt"}"/>`;
  }).join("");
  const nodes = path.map((city, index) => {
    const cx = x(city), cy = y(city);
    const anchor = cx > 340 ? "end" : "start";
    const labelX = cx > 340 ? cx - 10 : cx + 10;
    return `<circle cx="${cx}" cy="${cy}" r="5" class="${index === path.length - 1 ? "svg-city-active" : "svg-city"}"/><text x="${labelX}" y="${cy + 3}" text-anchor="${anchor}" class="svg-city-label">${escapeHtml(city)}</text>`;
  }).join("");
  return `<svg viewBox="0 0 420 170" role="img" aria-label="Local map showing route ${path.map(escapeHtml).join(" to ")}">${roads}${nodes}</svg>`;
}
function metricsMarkup(total) {
  return `<div class="metric-item"><span>Distance</span><strong>${fmt(total.distance)} <small>km</small></strong></div>
    <div class="metric-item"><span>Est. duration</span><strong>${durationText(total.duration)}</strong></div>
    <div class="metric-item"><span>Est. cost</span><strong>₹${fmt(total.cost)}</strong></div>`;
}
function renderAoMini(steps) {
  const decisions = steps.filter((step) => step.type === "OR decision");
  const width = 270, height = 145, rootX = 25, rootY = height / 2;
  let svg = `<svg viewBox="0 0 ${width} ${height}" role="img" aria-label="AO star graph: AND journey root connected to OR leg decisions">`;
  svg += `<line class="ao-edge" x1="${rootX + 16}" y1="${rootY}" x2="105" y2="${rootY}"/>`;
  svg += `<rect class="ao-and" x="${rootX}" y="${rootY - 12}" width="24" height="24" rx="4"/><text class="ao-node-label" x="${rootX + 12}" y="${rootY + 3}" text-anchor="middle">AND</text>`;
  decisions.forEach((step, index) => {
    const y = decisions.length === 1 ? rootY : 25 + index * (95 / (decisions.length - 1));
    svg += `<line class="ao-edge" x1="105" y1="${rootY}" x2="145" y2="${y}"/>`;
    svg += `<circle class="ao-or" cx="154" cy="${y}" r="12"/><text class="ao-node-label" x="154" y="${y + 3}" text-anchor="middle">OR</text>`;
    svg += `<line class="ao-edge" x1="166" y1="${y}" x2="205" y2="${y}"/>`;
    svg += `<rect class="ao-and" x="205" y="${y - 11}" width="49" height="22" rx="4"/><text class="ao-node-label" x="229" y="${y + 3}" text-anchor="middle">route</text>`;
    svg += `<text class="ao-city-label" x="145" y="${y + 25}">leg ${index + 1}</text>`;
  });
  svg += "</svg>";
  return svg;
}
function renderResults(result) {
  const path = result.astar.path;
  document.getElementById("results").classList.remove("hidden");
  document.getElementById("result-subtitle").textContent = `${path[0]} to ${path[path.length - 1]} · A* recommendation and AO* evaluation`;
  document.getElementById("route-tag").textContent = preferenceLabel(result.preference);
  document.getElementById("route-visual").innerHTML = renderRouteMap(path);
  document.getElementById("route-cities").innerHTML = path.map(escapeHtml).join('<span>→</span>');
  document.getElementById("main-metrics").innerHTML = metricsMarkup(result.astar.total);
  document.getElementById("astar-steps").innerHTML = result.astar.steps.map((step, index) =>
    `<div class="step-row"><span>${index + 1}. Expanded <b>${escapeHtml(step.city)}</b></span><small>g ${step.g} · h ${step.h} · f ${step.f}</small></div>`
  ).join("");
  document.getElementById("ao-path").textContent = result.ao.path.join(" → ");
  document.getElementById("ao-graph-mini").innerHTML = renderAoMini(result.ao.steps);
  document.getElementById("ao-metrics").innerHTML = metricsMarkup(result.ao.total);
  document.getElementById("ao-steps").innerHTML = result.ao.steps.map((step) =>
    `<div class="step-row"><span><b>${escapeHtml(step.type)}</b> · ${escapeHtml(step.message)}</span><small>${escapeHtml(step.selected.join(" → "))}</small></div>`
  ).join("");
  document.getElementById("explored-nodes").innerHTML = result.astar.explored.map((city, index) =>
    `<span class="explored-chip ${city === path[path.length - 1] ? "final" : ""}">${index + 1}. ${escapeHtml(city)}</span>`
  ).join("");
  document.getElementById("compare-panel").classList.add("hidden");
}

document.getElementById("compare-button").addEventListener("click", () => {
  if (!currentResult) return;
  const container = document.getElementById("alternatives-grid");
  container.innerHTML = currentResult.alternatives.map((route, index) => {
    const isBest = route.path.join("|") === currentResult.astar.path.join("|");
    return `<article class="alternative-card ${isBest ? "best" : ""}"><div class="alt-top"><span>${isBest ? "✦ RECOMMENDED" : `OPTION ${index + 1}`}</span><span>#${index + 1}</span></div>
      <div class="alt-route">${route.path.map(escapeHtml).join(" → ")}</div>
      <div class="alt-metrics"><span>${fmt(route.total.distance)} <small>km</small></span><span>${durationText(route.total.duration)}</span><span>₹${fmt(route.total.cost)}</span></div></article>`;
  }).join("");
  document.getElementById("compare-panel").classList.toggle("hidden");
});
document.getElementById("steps-toggle").addEventListener("click", () => {
  document.getElementById("astar-steps").classList.toggle("hidden");
});
document.getElementById("ao-steps-toggle").addEventListener("click", () => {
  document.getElementById("ao-steps").classList.toggle("hidden");
});
document.querySelectorAll(".nav-link").forEach((link) => link.addEventListener("click", () => {
  document.querySelectorAll(".nav-link").forEach((item) => item.classList.remove("active"));
  link.classList.add("active");
}));
fetch("/api/network").then((response) => response.json()).then((data) => { network = data; }).catch(() => {
  document.getElementById("form-error").textContent = "Could not load the local road network.";
});
