/**
 * Рисует мини-график (sparkline) как SVG без внешних зависимостей
 */
function drawSparkline(container, values, opts = {}) {
  const {
    width  = 100,
    height = 40,
    color  = '#C8181A',
    fill   = true,
  } = opts;

  const nums = values.filter(v => v != null && !isNaN(v)).map(Number);
  if (nums.length < 2) { container.innerHTML = ''; return; }

  const min = Math.min(...nums);
  const max = Math.max(...nums);
  const range = max - min || 1;

  const pad = 2;
  const W = width - pad * 2;
  const H = height - pad * 2;

  const pts = nums.map((v, i) => {
    const x = pad + (i / (nums.length - 1)) * W;
    const y = pad + H - ((v - min) / range) * H;
    return [x, y];
  });

  const polyline = pts.map(([x, y]) => `${x},${y}`).join(' ');

  let pathD = `M ${pts[0][0]},${pts[0][1]}`;
  for (let i = 1; i < pts.length; i++) {
    pathD += ` L ${pts[i][0]},${pts[i][1]}`;
  }

  let fillPath = '';
  if (fill) {
    fillPath = `<path d="${pathD} L ${pts[pts.length-1][0]},${pad+H} L ${pts[0][0]},${pad+H} Z"
      fill="${color}" fill-opacity="0.12" stroke="none"/>`;
  }

  container.innerHTML = `
    <svg width="${width}" height="${height}" viewBox="0 0 ${width} ${height}"
         xmlns="http://www.w3.org/2000/svg" style="display:block">
      ${fillPath}
      <path d="${pathD}" stroke="${color}" stroke-width="1.5" fill="none"
            stroke-linecap="round" stroke-linejoin="round"/>
      <circle cx="${pts[pts.length-1][0]}" cy="${pts[pts.length-1][1]}" r="2.5"
              fill="${color}"/>
    </svg>`;
}
