// Flask App JS
// Written by Michael Chung

// Constants


/////////////////////////////////
// ADC Graph Stuff
//
/////////////////////////////////

// -------------------------
// Config
// -------------------------

const ADC_CHANNELS = 8;
const WINDOW_SEC = 30.0;
const DRAW_HZ = 10.0;

let runT0 = null;

let winT = [];
let winY = Array.from({ length: ADC_CHANNELS }, () => []);

// -------------------------
// Helpers (ADC Graph)
// -------------------------

function ingestSample(unix_t, adc) {
  if (!adc || adc.length !== ADC_CHANNELS) return;

  if (runT0 === null) runT0 = unix_t;
  const t = unix_t - runT0;

  winT.push(t);
  for (let i = 0; i < ADC_CHANNELS; i++) winY[i].push(Number(adc[i]));

  // Trim to last WINDOW_SEC
  while (winT.length > 0 && (winT[winT.length - 1] - winT[0]) > WINDOW_SEC) {
    winT.shift();
    for (let i = 0; i < ADC_CHANNELS; i++) winY[i].shift();
  }
}
// -------------------------
// Env graph Helpers
// -------------------------

// const ENV_WINDOW_SEC = 300.0; // 5 min looks nice for slow env trends
const ENV_WINDOW_SEC = WINDOW_SEC

let envT = [];
let envTemp = [];
let envRH = [];
let envCO2 = [];

let lastEnvUnix = null;

function ingestEnv(unix_t, temp_c, rh, co2_ppm) {
  if (unix_t == null) return;

  if (runT0 === null) runT0 = unix_t;
  const t = unix_t - runT0;

  envT.push(t);
  envTemp.push(temp_c != null ? Number(temp_c) : null);
  envRH.push(rh != null ? Number(rh) : null);
  envCO2.push(co2_ppm != null ? Number(co2_ppm) : null);

  lastEnvUnix = Number(unix_t);

  // trim window
  while (envT.length > 0 && (envT[envT.length - 1] - envT[0]) > ENV_WINDOW_SEC) {
    envT.shift();
    envTemp.shift();
    envRH.shift();
    envCO2.shift();
  }
}

function calcStats(arr) {
  const v = arr.filter(x => x != null && Number.isFinite(x));
  if (v.length === 0) return null;
  let mn = v[0], mx = v[0], sum = 0;
  for (const x of v) { mn = Math.min(mn, x); mx = Math.max(mx, x); sum += x; }
  return { mn, avg: sum / v.length, mx };
}

function co2Band(ppm) {
  if (ppm == null || !Number.isFinite(ppm)) return "-";
  if (ppm < 800) return "good";
  if (ppm < 1200) return "ok";
  if (ppm < 2000) return "stuffy";
  return "poor";
}

// -------------------------
// Other Helpers
// -------------------------

// Age indicator (Stream + Browser Latency Label)
let lastMsgUnix = null;
setInterval(() => {
  const el = document.getElementById("data_age");
  if (!el) return;

  if (lastMsgUnix == null) { el.textContent = "--"; return; }

  const ageSec = (Date.now() / 1000) - lastMsgUnix;
  el.textContent = `${ageSec.toFixed(1)}s ago`;
}, 200);


// -------------------------
// Chart.js setup
// -------------------------

const COLORS = [
  "#e41a1c", // red
  "#377eb8", // blue
  "#4daf4a", // green
  "#984ea3", // purple
  "#ff7f00", // orange
  "#a65628", // brown
  "#f781bf", // pink
  "#999999", // gray
];

function makeDatasets() {
  const ds = [];
  for (let i = 0; i < ADC_CHANNELS; i++) {
    ds.push({
      label: `ADC${i < 4 ? 0 : 1} CH${i % 4}`,
      data: [],
      borderColor: COLORS[i],
      backgroundColor: COLORS[i],
      borderWidth: 1.5,
      pointRadius: 0,
      tension: 0.0,
    });
  }
  return ds;
}

const ctx = document.getElementById("adcChart").getContext("2d");
const adcChart = new Chart(ctx, {
  type: "line",
  data: { datasets: makeDatasets() },
  options: {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    parsing: false,
    scales: {
      x: {
        type: "linear",
        title: { display: true, text: "t since start (s)" }
      },
      y: {
        title: { display: true, text: "ADC raw" },
        min: 0,
        max: 26400
      }
    },
    plugins: {
      legend: {
        display: true,
        position: "bottom",
        labels: {
          usePointStyle: true,
          boxWidth: 10,
          font: {
            size: 10
          }
        }
      }
    }
  }
});

function redrawChart() {
  if (winT.length === 0) return;

  const tEnd = winT[winT.length - 1];
  const tStart = Math.max(0, tEnd - WINDOW_SEC);

  for (let ch = 0; ch < ADC_CHANNELS; ch++) {
    adcChart.data.datasets[ch].data =
      winT.map((x, i) => ({ x, y: winY[ch][i] }));
  }

  // Force smooth scrolling window
  adcChart.options.scales.x.min = tStart;
  adcChart.options.scales.x.max = tEnd;

  adcChart.update("none");
}

// Redraw loop at fixed FPS
setInterval(() => {
  redrawChart();
}, Math.round(1000 / DRAW_HZ));


// ENV Graph
const envCtx = document.getElementById("envChart").getContext("2d");
const envChart = new Chart(envCtx, {
  type: "line",
  data: {
    datasets: [
      { label: "Temp (°C)", data: [], borderWidth: 1.5, pointRadius: 0, tension: 0.0 },
      { label: "RH (%RH)", data: [], borderWidth: 1.5, pointRadius: 0, tension: 0.0, yAxisID: "y1" },
      { label: "CO₂ (ppm)", data: [], borderWidth: 1.5, pointRadius: 0, tension: 0.0, yAxisID: "y2" },
    ]
  },
  options: {
    animation: false,
    responsive: true,
    maintainAspectRatio: false,
    parsing: false,
    scales: {
      x: { type: "linear", title: { display: true, text: "t since env start (s)" } },
      y: { title: { display: true, text: "°C" } },
      y1: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "%RH" } },
      y2: { position: "right", grid: { drawOnChartArea: false }, title: { display: true, text: "ppm" }, display: false } // hidden until CO2 exists
    },
    plugins: { legend: { display: true, position: "bottom" } }
  }
});

function redrawEnv() {
  if (envT.length === 0) return;

  const tEnd = envT[envT.length - 1];
  const tStart = Math.max(0, tEnd - ENV_WINDOW_SEC);

  envChart.data.datasets[0].data = envT.map((x, i) => ({ x, y: envTemp[i] })).filter(p => p.y != null);
  envChart.data.datasets[1].data = envT.map((x, i) => ({ x, y: envRH[i] })).filter(p => p.y != null);

  const hasCO2 = envCO2.some(v => v != null);
  envChart.options.scales.y2.display = hasCO2;
  envChart.data.datasets[2].data = envT.map((x, i) => ({ x, y: envCO2[i] })).filter(p => p.y != null);

  envChart.options.scales.x.min = tStart;
  envChart.options.scales.x.max = tEnd;

  envChart.update("none");

  // update cards
  const ts = calcStats(envTemp);
  const hs = calcStats(envRH);

  const lastTemp = [...envTemp].reverse().find(v => v != null);
  const lastRH = [...envRH].reverse().find(v => v != null);
  const lastCO2 = [...envCO2].reverse().find(v => v != null);

  document.getElementById("temp_val").textContent = lastTemp != null ? lastTemp.toFixed(2) : "-";
  document.getElementById("rh_val").textContent = lastRH != null ? lastRH.toFixed(2) : "-";
  document.getElementById("co2_val").textContent = lastCO2 != null ? Math.round(lastCO2) : "-";
  document.getElementById("co2_band").textContent = co2Band(lastCO2);

  document.getElementById("temp_stats").textContent = ts ? `${ts.mn.toFixed(2)}/${ts.avg.toFixed(2)}/${ts.mx.toFixed(2)}` : "-";
  document.getElementById("rh_stats").textContent = hs ? `${hs.mn.toFixed(1)}/${hs.avg.toFixed(1)}/${hs.mx.toFixed(1)}` : "-";
}

// you can reuse your 10 Hz loop; env can update slower but redraw is cheap
setInterval(() => {
  redrawEnv();
}, Math.round(1000 / 10.0));





// -------------------------
// SSE wiring (example)
// -------------------------

/*
function startSSE() {
  const es = new EventSource("/events");

  es.onmessage = (ev) => {
    const msg = JSON.parse(ev.data);

    // Your payload has: msg.t (unix seconds), msg.adc (8 ints)
    if (msg.t != null && msg.adc != null) {
      ingestSample(msg.t, msg.adc);
    }

    // ...keep your existing status/adc table updates here too...
  };

  es.onerror = () => {
    // handle disconnect message if you want
    // (EventSource will retry)
  };
}

startSSE();
*/



/////////////////////////////////
//
// Streams and Stuff
//
/////////////////////////////////

const names = ["ADC0 CH0","ADC0 CH1","ADC0 CH2","ADC0 CH3","ADC1 CH0","ADC1 CH1","ADC1 CH2","ADC1 CH3"];

function renderADC(vals) {
  const tbody = document.getElementById("adc");
  tbody.innerHTML = "";
  for (let i = 0; i < names.length; i++) {
    const tr = document.createElement("tr");
    const td1 = document.createElement("td");
    td1.className = "label";
    td1.textContent = names[i];
    const td2 = document.createElement("td");
    td2.className = "value";
    td2.textContent = (vals && vals.length === 8) ? vals[i] : "-";
    tr.appendChild(td1);
    tr.appendChild(td2);
    tbody.appendChild(tr);
  }
}

const es = new EventSource("/events");

function updateClip(labelId, valueId, val) {
  const label = document.getElementById(labelId);
  const valueElement = document.getElementById(valueId);
  const pct = val * 100.0;
  valueElement.textContent = pct.toFixed(1);

  if (pct > 0.0) {
    label.classList.remove("clip-ok");
    label.classList.add("clip-warn");
  }
  else {
    label.classList.remove("clip-warn");
    label.classList.add("clip-ok");
  }
}

es.onmessage = (ev) => {
  const msg = JSON.parse(ev.data);
  if (msg.t != null) lastMsgUnix = Number(msg.t);

  // Update status text
  document.getElementById("status").textContent = msg.status;
  
  // Update runT0
  if (runT0 === null && msg.runstart != null) {
    runT0 = Number(msg.runstart);
    document.getElementById("runstart").textContent = new Date(runT0 * 1000).toLocaleString();
  }

  // Update web fps
  document.getElementById("webfps").textContent = msg.web_fps.toFixed(2);

  // Update ADC list
  // msg.adc is array of 8 values
  for (let i = 0; i < msg.adc.length; i++) {
    const el = document.getElementById(`adc_${i}`);
    if (el) el.textContent = msg.adc[i];
  }

  // ADC Charts
  if (msg.t != null && msg.adc != null) {
    ingestSample(msg.t, msg.adc);
  }

  // Environment
  // Use msg.t as the timestamp if that's your unified sample time.
  if (msg.t != null) {
    const temp_c = msg.hdc_temp_c;     // msg temp
    const rh = msg.hdc_humidity_rh;             // relative humidity
    const co2 = msg.co2_ppm;       // later
    if (temp_c != null || rh != null || co2 != null) {
      ingestEnv(msg.t, temp_c, rh, co2);
    }
  }

  // Color bar
  /*
    if (msg.ir_min != null && msg.ir_max != null) {
    document.getElementById("cb_min").textContent = `Min ${msg.ir_min.toFixed(1)}°C`;
    document.getElementById("cb_max").textContent = `Max ${msg.ir_max.toFixed(1)}°C`;
  }
  */
  if (msg.ir_min != null && msg.ir_max != null) {
    const mode = msg.norm_mode;

    const fixed_norm = (mode === "fixed")

    const mn = !fixed_norm ? msg.ir_min : msg.norm_min;
    const mx = !fixed_norm ? msg.ir_max : msg.norm_max;

    const tf = (f) => mn + f * (mx - mn);

    document.getElementById("tick0").textContent   = `Min ${tf(0.00).toFixed(1)}°C`;
    document.getElementById("tick25").textContent  = tf(0.25).toFixed(1);
    document.getElementById("tick50").textContent  = tf(0.50).toFixed(1);
    document.getElementById("tick75").textContent  = tf(0.75).toFixed(1);
    document.getElementById("tick100").textContent = `Max ${tf(1.00).toFixed(1)}°C`;
  
    // only show saturation if fixed normalization
    const normLabel = document.getElementById("norm_label");
    const clipBlock = document.getElementById("clip_block");
    const rangeBlock = document.getElementById("range_block");
    if (fixed_norm) {
      normLabel.innerHTML = "<b>Fixed Normalization Clipping:</b>";
      clipBlock.style.display = "inline";
      rangeBlock.style.display = "none";
    }
    else {
      normLabel.innerHTML = "<b>Min-max Normalization</b>";
      clipBlock.style.display = "none";
      rangeBlock.style.display = "inline";
      
      const dt = mx - mn;
      document.getElementById("tdelta").textContent = dt.toFixed(1);
    }

    if (msg.sat_below != null) {
      updateClip("clip_low", "sat_low", msg.sat_below)
    }
    if (msg.sat_above != null) {
      updateClip("clip_high", "sat_high", msg.sat_above)
    }
  }
};

es.onerror = () => {
  document.getElementById("status").textContent = "Disconnected";
  // Browser will auto-reconnect SSE by default
  const el = document.getElementById("data_age");
  if (el) el.textContent = "disconnected";

};


async function loadMetaOnce() {
  try {
    const r = await fetch("/meta");
    const obj = await r.json();
    document.getElementById("meta").textContent = JSON.stringify(obj, null, 2);
  } catch (e) {
    document.getElementById("meta").textContent = "Failed to load meta.";
  }
}

window.addEventListener("load", () => {
  loadMetaOnce();
});

