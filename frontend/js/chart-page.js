/**
 * Логика страницы chart.html — ECharts + данные из API
 */
(function () {
  const params  = new URLSearchParams(location.search);
  const indCode = params.get('code');
  if (!indCode) { document.body.innerHTML = '<p style="padding:2rem">Укажите код показателя (?code=6.1)</p>'; return; }

  let chartInstance = null;
  let allSeries     = [];
  let indicator     = null;
  let currentMode   = 'absolute'; // 'absolute' | 'yoy'
  let currentRange  = null;       // null = all, number = years

  // ── DOM refs ──────────────────────────────────────────────────────────────
  const elTitle      = document.getElementById('chart-title');
  const elUnit       = document.getElementById('chart-unit');
  const elSource     = document.getElementById('chart-source-name');
  const elUpdated    = document.getElementById('chart-updated');
  const elKpiValue   = document.getElementById('kpi-last-value');
  const elKpiUnit    = document.getElementById('kpi-last-unit');
  const elKpiPeriod  = document.getElementById('kpi-last-period');
  const elKpiDelta   = document.getElementById('kpi-delta');
  const elTableBody  = document.getElementById('data-table-body');
  const elChartWrap  = document.getElementById('main-chart');
  const elRelated    = document.getElementById('related-grid');
  const elBreadCat   = document.getElementById('breadcrumb-cat');

  // ── Init ─────────────────────────────────────────────────────────────────
  async function init() {
    try {
      const result = await api.indicatorData(indCode);
      indicator  = result.indicator;
      allSeries  = result.series;
      renderMeta();
      renderKPI();
      buildChart();
      renderTable();
      loadRelated();
    } catch (e) {
      console.error(e);
      elChartWrap.innerHTML = `<div style="padding:2rem;color:var(--color-negative)">Ошибка загрузки данных: ${e.message}</div>`;
    }
  }

  // ── Metadata ──────────────────────────────────────────────────────────────
  function renderMeta() {
    document.title = `${indicator.name} — Рынок недвижимости`;
    elTitle.textContent  = indicator.name;
    elUnit.textContent   = indicator.unit || '';
    elSource.textContent = indicator.source?.name || '—';
    elUpdated.textContent = indicator.last_updated
      ? new Date(indicator.last_updated).toLocaleDateString('ru-RU') : '—';
    if (elBreadCat && indicator.category) {
      elBreadCat.textContent = indicator.category.name;
      elBreadCat.href = `category.html?code=${indicator.category.code}`;
    }
  }

  // ── KPI row ───────────────────────────────────────────────────────────────
  function renderKPI() {
    const pts = allSeries.filter(p => p.value != null);
    if (!pts.length) return;
    const last = pts[pts.length - 1];
    elKpiValue.textContent  = fmtValue(last.value);
    elKpiUnit.textContent   = indicator.unit || '';
    elKpiPeriod.textContent = last.label || fmtDate(last.date, indicator.periodicity);
    elKpiDelta.innerHTML    = deltaHtml(last.yoy_change_pct);
  }

  // ── Filtered series ───────────────────────────────────────────────────────
  function getFiltered() {
    if (!currentRange) return allSeries;
    const cutoff = new Date();
    cutoff.setFullYear(cutoff.getFullYear() - currentRange);
    return allSeries.filter(p => new Date(p.date) >= cutoff);
  }

  // ── ECharts ───────────────────────────────────────────────────────────────
  function buildChart() {
    if (!chartInstance) {
      chartInstance = echarts.init(elChartWrap, null, { renderer: 'svg' });
      window.addEventListener('resize', () => chartInstance.resize());
    }
    const series = getFiltered();
    const isBar  = indicator.chart_type === 'bar';

    const xData  = series.map(p => fmtDate(p.date, indicator.periodicity));
    const yData  = currentMode === 'yoy'
      ? series.map(p => p.yoy_change_pct != null ? Number(p.yoy_change_pct) : null)
      : series.map(p => p.value != null ? Number(p.value) : null);

    const seriesName = currentMode === 'yoy' ? 'Изм. г/г, %' : (indicator.unit || 'Значение');
    const yFmt = currentMode === 'yoy'
      ? v => `${v > 0 ? '+' : ''}${fmtNum(v, 1)}%`
      : v => fmtValue(v, indicator.unit);

    const option = {
      animation: true,
      animationDuration: 400,
      grid: { left: 60, right: 20, top: 20, bottom: 60 },
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#0D1B2A',
        borderColor: '#0D1B2A',
        textStyle: { color: '#fff', fontFamily: 'IBM Plex Sans', fontSize: 13 },
        formatter: params => {
          const p = params[0];
          if (p.value == null) return `${p.axisValue}<br/><span style="color:#7A8B9A">нет данных</span>`;
          return `<b>${p.axisValue}</b><br/>${seriesName}: <b>${yFmt(p.value)}</b>`;
        },
      },
      xAxis: {
        type: 'category',
        data: xData,
        axisLabel: {
          fontFamily: 'IBM Plex Sans',
          fontSize: 11,
          color: '#7A8B9A',
          rotate: xData.length > 36 ? 30 : 0,
        },
        axisLine: { lineStyle: { color: '#DDE2E8' } },
        axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontFamily: 'IBM Plex Mono',
          fontSize: 11,
          color: '#7A8B9A',
          formatter: v => currentMode === 'yoy' ? `${v}%` : fmtNum(v),
        },
        splitLine: { lineStyle: { color: '#DDE2E8', type: 'dashed' } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [{
        name: seriesName,
        type: isBar || currentMode === 'yoy' ? 'bar' : 'line',
        data: yData,
        smooth: !isBar,
        symbol: yData.length < 60 ? 'circle' : 'none',
        symbolSize: 4,
        lineStyle: { width: 2, color: '#E8341C' },
        itemStyle: {
          color: params => {
            if (currentMode === 'yoy') {
              return params.value >= 0 ? '#0E7C56' : '#C0392B';
            }
            return '#E8341C';
          },
        },
        areaStyle: (!isBar && currentMode !== 'yoy') ? {
          color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [
              { offset: 0,   color: 'rgba(232,52,28,.18)' },
              { offset: 1,   color: 'rgba(232,52,28,.02)' },
            ]
          }
        } : undefined,
        connectNulls: false,
        markLine: currentMode === 'yoy' ? {
          data: [{ yAxis: 0 }],
          lineStyle: { color: '#DDE2E8', type: 'solid' },
          label: { show: false },
          symbol: 'none',
        } : undefined,
      }],
    };

    chartInstance.setOption(option, true);
  }

  // ── Table ──────────────────────────────────────────────────────────────────
  function renderTable() {
    const series = [...getFiltered()].reverse();
    elTableBody.innerHTML = series.map(p => `
      <tr>
        <td>${fmtDate(p.date, indicator.periodicity)}</td>
        <td class="num ${p.is_preliminary ? 'prelim' : ''}">${p.value != null ? fmtValue(p.value) : '—'}</td>
        <td class="num">${deltaHtml(p.yoy_change_pct)}</td>
        <td class="num">${p.prev_year_value != null ? fmtValue(p.prev_year_value) : '—'}</td>
      </tr>
    `).join('');
  }

  // ── Related indicators ────────────────────────────────────────────────────
  async function loadRelated() {
    if (!indicator?.category || !elRelated) return;
    try {
      const list = await api.categoryIndicators(indicator.category.code);
      const others = list.filter(i => i.code !== indCode).slice(0, 4);
      elRelated.innerHTML = others.map(i => `
        <a href="chart.html?code=${i.code}" class="related-card">
          <div class="related-card-name">${i.name}</div>
          <div class="related-card-value">${i.last_value != null ? fmtValue(i.last_value) : '—'}</div>
          <div class="related-card-unit">${i.unit || ''} &nbsp; ${deltaHtml(i.yoy_change_pct)}</div>
        </a>
      `).join('');
    } catch (e) { /* silence */ }
  }

  // ── Controls ──────────────────────────────────────────────────────────────
  document.querySelectorAll('[data-range]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-range]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentRange = btn.dataset.range === 'all' ? null : Number(btn.dataset.range);
      buildChart();
      renderTable();
    });
  });

  document.querySelectorAll('[data-mode]').forEach(btn => {
    btn.addEventListener('click', () => {
      document.querySelectorAll('[data-mode]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      currentMode = btn.dataset.mode;
      buildChart();
    });
  });

  document.getElementById('btn-download-png')?.addEventListener('click', () => {
    if (!chartInstance) return;
    const url = chartInstance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' });
    const a = document.createElement('a');
    a.href = url;
    a.download = `chart_${indCode}.png`;
    a.click();
  });

  document.getElementById('btn-download-xlsx')?.addEventListener('click', () => {
    window.open(api.indicatorXlsx(indCode));
  });

  // ── Search ────────────────────────────────────────────────────────────────
  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    let timer;
    searchInput.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = searchInput.value.trim();
        if (q.length < 2) { document.getElementById('search-results')?.remove(); return; }
        try {
          const results = await api.search(q);
          showSearchDropdown(results);
        } catch (e) { /* silence */ }
      }, 300);
    });
  }

  function showSearchDropdown(results) {
    document.getElementById('search-results')?.remove();
    if (!results.length) return;
    const div = document.createElement('div');
    div.id = 'search-results';
    div.style.cssText = `position:absolute;top:100%;left:0;right:0;background:#fff;
      border:1px solid var(--color-border);border-radius:var(--radius);
      box-shadow:var(--shadow-md);z-index:200;max-height:320px;overflow-y:auto;`;
    div.innerHTML = results.map(r => `
      <a href="chart.html?code=${r.code}" style="display:flex;gap:12px;align-items:center;
         padding:10px 16px;border-bottom:1px solid var(--color-border);font-size:.83rem;
         color:var(--color-ink);transition:background .1s;" 
         onmouseover="this.style.background='var(--color-bg)'"
         onmouseout="this.style.background=''">
        <span style="font-family:var(--font-mono);font-size:.72rem;color:var(--color-muted);
          background:var(--color-bg);padding:2px 6px;border-radius:3px">${r.code}</span>
        <span style="flex:1">${r.name}</span>
        <span style="font-size:.72rem;color:var(--color-muted)">${r.category_name || ''}</span>
      </a>
    `).join('');
    const wrap = document.querySelector('.header-search');
    if (wrap) { wrap.style.position = 'relative'; wrap.appendChild(div); }
    document.addEventListener('click', e => { if (!wrap?.contains(e.target)) div.remove(); }, { once: true });
  }

  init();
})();
