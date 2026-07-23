// BEACON operations map — hand-drawn Cedar Canyon terrain, warm-char palette.
// No tiles, no Leaflet, no keys. Pins positioned by percent coords.

const STREETS = {
  "cedar canyon rd": { x: 34, y: 61 }, "miner's bend": { x: 66, y: 26 },
  "ridgeway loop": { x: 72, y: 33 }, "pine hollow ct": { x: 61, y: 22 },
  "granite pass": { x: 78, y: 24 }, "old sawmill rd": { x: 46, y: 48 },
  "sumac trail": { x: 69, y: 41 }, "redtail dr": { x: 55, y: 55 },
  "quarry view ln": { x: 41, y: 37 }, "foxglove way": { x: 28, y: 47 },
  "larkspur ct": { x: 23, y: 68 }, "stagecoach rd": { x: 50, y: 72 },
};

// Six perimeter polygons, anchored top-right, each larger than the last.
const PERIMETERS = [
  "760,20 800,20 800,150 690,140 640,70",
  "700,10 800,10 800,220 640,220 560,120 620,50",
  "640,0 800,0 800,300 560,300 470,170 560,60",
  "560,0 800,0 800,360 470,380 380,220 500,70",
  "480,0 800,0 800,430 400,450 300,270 440,80",
  "380,0 800,0 800,520 320,540 220,320 380,90",
];

const MAPSZ = { W: 800, H: 600 };
const pctX = (x) => (x / 100) * MAPSZ.W;
const pctY = (y) => (y / 100) * MAPSZ.H;

const PIN_COLOR = {
  fire_rescue: "#FF5C2E", transport_assist: "#FFB020",
  accessible_shelter: "#7DB2E8", needs_human_review: "#FF5C2E",
  auto_answered: "#70634E", standard: "#70634E",
};
const FLAGGED = new Set(["fire_rescue", "transport_assist", "accessible_shelter", "needs_human_review"]);

function buildMap() {
  const streetDots = Object.entries(STREETS).map(([name, c]) => {
    const x = pctX(c.x), y = pctY(c.y);
    const label = name.replace(/\b\w/g, (m) => m.toUpperCase());
    return `<circle cx="${x}" cy="${y}" r="2" fill="#8A7B63"/>
      <text x="${x + 6}" y="${y + 3}" fill="#70634E" font-size="9.5"
        font-family="'IBM Plex Mono',monospace">${label}</text>`;
  }).join("");

  // Faint survey grid.
  let grid = "";
  for (let gx = 100; gx < MAPSZ.W; gx += 100) grid += `<line x1="${gx}" y1="0" x2="${gx}" y2="${MAPSZ.H}"/>`;
  for (let gy = 100; gy < MAPSZ.H; gy += 100) grid += `<line x1="0" y1="${gy}" x2="${MAPSZ.W}" y2="${gy}"/>`;

  return `
  <svg id="beaconMap" viewBox="0 0 ${MAPSZ.W} ${MAPSZ.H}" preserveAspectRatio="xMidYMid meet">
    <defs>
      <radialGradient id="terr" cx="28%" cy="72%" r="95%">
        <stop offset="0%" stop-color="#1C1611"/><stop offset="100%" stop-color="#14100C"/>
      </radialGradient>
      <radialGradient id="fireCore" cx="88%" cy="8%" r="80%">
        <stop offset="0%" stop-color="#FF8C5A" stop-opacity=".55"/>
        <stop offset="45%" stop-color="#FF5C2E" stop-opacity=".34"/>
        <stop offset="100%" stop-color="#FF5C2E" stop-opacity=".22"/>
      </radialGradient>
      <filter id="glow"><feGaussianBlur stdDeviation="3.5" result="b"/>
        <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>
    </defs>
    <rect width="${MAPSZ.W}" height="${MAPSZ.H}" fill="url(#terr)"/>
    <g stroke="#211A13" stroke-width="1">${grid}</g>

    <!-- ridgelines / contours -->
    <path d="M0,180 C150,120 320,210 480,150 S760,120 800,170" fill="none" stroke="#2E2519" stroke-width="3"/>
    <path d="M0,205 C160,150 330,235 490,178 S760,148 800,196" fill="none" stroke="#271F14" stroke-width="1.5"/>
    <path d="M0,300 C180,250 340,330 520,280 S780,260 800,300" fill="none" stroke="#2B2216" stroke-width="2.5"/>
    <path d="M0,328 C190,280 350,356 530,308 S780,288 800,326" fill="none" stroke="#251D12" stroke-width="1.2"/>
    <!-- river -->
    <path d="M120,600 C160,460 90,360 200,250 S180,120 260,0" fill="none" stroke="#3A5F7D" stroke-width="4" opacity=".55"/>
    <!-- evacuation route -->
    <path d="M0,520 C220,500 420,540 600,470 S780,430 800,440" fill="none" stroke="#57493A" stroke-width="2.5" stroke-dasharray="12 8"/>
    <text x="14" y="508" fill="#57493A" font-size="9.5" font-family="'IBM Plex Mono',monospace" letter-spacing="2">EVAC ROUTE 12 →</text>

    <!-- fire perimeter -->
    <polygon id="perimeter" points="${PERIMETERS[0]}" fill="url(#fireCore)"
      stroke="#FF8C5A" stroke-width="2" filter="url(#glow)" style="transition:all 1s ease"/>
    <circle cx="770" cy="40" r="5" fill="#FFC9A8" filter="url(#glow)"/>
    <text x="700" y="16" fill="#FF8C5A" font-size="9.5" font-family="'IBM Plex Mono',monospace" letter-spacing="2">ORIGIN</text>

    <!-- wind arrow (NE -> SW) -->
    <g transform="translate(742,88)" stroke="#9C8E77" fill="none" stroke-width="1.5">
      <line x1="18" y1="-14" x2="-18" y2="14"/><path d="M-10,6 L-18,14 L-8,16" />
    </g>
    <text x="700" y="120" fill="#9C8E77" font-size="9" font-family="'IBM Plex Mono',monospace" letter-spacing="1">WIND 24MPH</text>

    <!-- streets -->
    ${streetDots}
    <g id="pins"></g>

    <!-- legend -->
    <g font-family="'IBM Plex Mono',monospace" font-size="9.5">
      <rect x="12" y="12" width="158" height="92" fill="#14100C" fill-opacity=".85" stroke="#3B3122"/>
      <circle cx="26" cy="32" r="5" fill="#FF5C2E"/><text x="38" y="36" fill="#C9BCA5">FIRE / RESCUE</text>
      <circle cx="26" cy="52" r="5" fill="#FFB020"/><text x="38" y="56" fill="#C9BCA5">TRANSPORT</text>
      <circle cx="26" cy="72" r="5" fill="#7DB2E8"/><text x="38" y="76" fill="#C9BCA5">SHELTER</text>
      <circle cx="26" cy="91" r="3.5" fill="#70634E"/><text x="38" y="95" fill="#C9BCA5">STANDARD</text>
    </g>
  </svg>`;
}

function renderPins(cases) {
  const g = document.getElementById("pins");
  if (!g) return;
  g.innerHTML = cases.filter((c) => c.pin).map((c) => {
    const x = pctX(c.pin.x), y = pctY(c.pin.y);
    const color = PIN_COLOR[c.dispatch_path] || "#70634E";
    const flagged = FLAGGED.has(c.dispatch_path);
    const halo = flagged
      ? `<circle cx="${x}" cy="${y}" r="12" fill="none" stroke="${color}" stroke-width="1.5" opacity=".6">
           <animate attributeName="r" values="7;15" dur="1.6s" repeatCount="indefinite"/>
           <animate attributeName="opacity" values=".7;0" dur="1.6s" repeatCount="indefinite"/>
         </circle>` : "";
    return `${halo}<circle data-case="${c.id}" cx="${x}" cy="${y}" r="${flagged ? 6.5 : 3}"
      fill="${color}" stroke="#14100C" stroke-width="1.5" style="cursor:pointer"
      onmouseover="highlightCard('${c.id}', true)" onmouseout="highlightCard('${c.id}', false)"
      onclick="openReceipt('${c.id}')"><title>${(c.requester_name || "").replace(/[<>&"]/g, "")}</title></circle>`;
  }).join("");
}

function setPerimeter(step) {
  const p = document.getElementById("perimeter");
  if (p) p.setAttribute("points", PERIMETERS[Math.min(step, PERIMETERS.length - 1)]);
}

document.getElementById("mapHost").innerHTML = buildMap();
