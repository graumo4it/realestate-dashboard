/**
 * Логика страницы chart.html
 * Правки v1.2:
 *   - кнопки тулбара «1 год / 3 года / 5 лет»
 *   - ось X: горизонтальные двухстрочные метки (янв.\n2024), без наклона
 *   - ось Y: знак «-» для отрицательных, «%» если ед. изм. %, разделитель разрядов
 *   - tooltip: единица только в значении, не в названии серии
 *   - таблица: заголовки «Значение, ед.» / «ИЗМ. Г/Г» / «ИЗМ. М/М», значения динамики с ед.
 */
(function () {
  const params  = new URLSearchParams(location.search);
  const indCode = params.get('code');
  if (!indCode) { document.body.innerHTML = '<p style="padding:2rem">Укажите код показателя (?code=6.1)</p>'; return; }

  let chartInstance = null;
  let allSeries     = [];
  let indicator     = null;
  let currentMode        = 'absolute'; // 'absolute' | 'yoy' | 'mom'
  let currentRange       = null;
  let currentPeriodicity = 'quarterly'; // 'quarterly' | 'annual' — только для квартальных

  const elTitle     = document.getElementById('chart-title');
  const elUnit      = document.getElementById('chart-unit');
  const elSource    = document.getElementById('chart-source-name');
  const elUpdated   = document.getElementById('chart-updated');
  const elKpiValue  = document.getElementById('kpi-last-value');
  const elKpiUnit   = document.getElementById('kpi-last-unit');
  const elKpiPeriod = document.getElementById('kpi-last-period');
  const elKpiDelta  = document.getElementById('kpi-delta');
  const elTableBody = document.getElementById('data-table-body');
  const elChartWrap = document.getElementById('main-chart');
  const elRelated   = document.getElementById('related-grid');
  const elBreadCat  = document.getElementById('breadcrumb-cat');

  // Процентный показатель → динамика в п.п.
  function isPp() {
    return indicator && indicator.unit === '%';
  }

  // Количество знаков после запятой для оси Y на основе данных
  function axisDecimals(data) {
    const vals = data.filter(v => v != null).map(v => Math.abs(Number(v)));
    if (!vals.length) return 0;
    // Если все целые или >= 100 — без знаков
    const allLarge = vals.every(v => v >= 100);
    if (allLarge) return 0;
    // Иначе смотрим на дробную часть
    const hasDecimals = vals.some(v => (v % 1) !== 0);
    if (!hasDecimals) return 0;
    // Определяем нужную точность
    const maxDecimals = vals.reduce((acc, v) => {
      const s = v.toString();
      const dot = s.indexOf('.');
      if (dot === -1) return acc;
      return Math.max(acc, s.length - dot - 1);
    }, 0);
    return Math.min(maxDecimals, 2);
  }

  async function init() {
    try {
      const result = await api.indicatorData(indCode);
      indicator = result.indicator;
      allSeries = result.series;
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

  function renderMeta() {
    const displayName = cleanName(indicator.name);
    document.title = `${displayName} — Рынок недвижимости`;
    elTitle.textContent   = displayName;
    elUnit.textContent    = indicator.unit || '';
    elSource.textContent  = indicator.source?.name || '—';
    elUpdated.textContent = indicator.last_updated
      ? new Date(indicator.last_updated).toLocaleDateString('ru-RU') : '—';
    if (elBreadCat && indicator.category) {
      elBreadCat.textContent = indicator.category.name;
      elBreadCat.href = `category.html?code=${indicator.category.code}`;
    }

    // Breadcrumb — показываем название, не код
    const elBreadCode = document.getElementById('breadcrumb-code');
    if (elBreadCode) elBreadCode.textContent = cleanName(indicator.name);

    // Скрыть МоМ для годовых
    if (indicator.periodicity === 'annual') {
      document.querySelector('[data-mode="mom"]')?.remove();
    }
    // Переименовать кнопку для квартальных
    if (indicator.periodicity === 'quarterly') {
      const momBtn = document.querySelector('[data-mode="mom"]');
      if (momBtn) momBtn.textContent = 'Изм. кв./кв.';
    }
    // Инжектировать кнопки Квартал/Год для квартальных данных
    if (indicator.periodicity === 'quarterly' && window.PeriodToggle) {
      const toolbar = document.querySelector('.chart-toolbar');
      PeriodToggle.injectButtons(toolbar, {
        options: ['quarterly', 'annual'],
        defaultValue: 'quarterly',
        labels: { quarterly: 'Квартал', annual: 'Год' },
      }, (periodicity) => {
        currentPeriodicity = periodicity;
        const momBtn = document.querySelector('[data-mode="mom"]');
        if (momBtn) momBtn.style.display = periodicity === 'annual' ? 'none' : '';
        if (periodicity === 'annual' && currentMode === 'mom') {
          document.querySelectorAll('[data-mode]').forEach(b => b.classList.remove('active'));
          document.querySelector('[data-mode="absolute"]').classList.add('active');
          currentMode = 'absolute';
        }
        buildChart();
        renderTable();
      });
    }
  }

  function renderKPI() {
    const pts = allSeries.filter(p => p.value != null);
    if (!pts.length) return;
    const last = pts[pts.length - 1];
    elKpiValue.textContent  = fmtValue(last.value);
    elKpiUnit.textContent   = indicator.unit || '';
    // KPI период — однострочный формат
    elKpiPeriod.textContent = last.label || fmtDateInline(last.date, indicator.periodicity);

    const pp = isPp();
    const momLabel = indicator.periodicity === 'quarterly' ? 'кв./кв.' : 'м/м';
    const yoyHtml = last.yoy_change_pct != null
      ? `<span style="margin-right:12px">г/г: ${deltaHtml(last.yoy_change_pct, pp)}</span>` : '';
    const momHtml = (last.mom_change_pct != null && indicator.periodicity !== 'annual')
      ? `<span>${momLabel}: ${deltaHtml(last.mom_change_pct, pp)}</span>` : '';
    elKpiDelta.innerHTML = yoyHtml + momHtml;
  }

  function getFiltered() {
    let series = allSeries;

    // Агрегация квартальных → годовые
    if (indicator.periodicity === 'quarterly' && currentPeriodicity === 'annual') {
      const byYear = {};
      for (const p of allSeries) {
        if (p.value == null || !p.date) continue;
        const year = p.date.slice(0, 4);
        if (!byYear[year]) byYear[year] = [];
        byYear[year].push(Number(p.value));
      }
      series = Object.entries(byYear)
        .filter(([, vals]) => vals.length === 4)
        .sort(([a], [b]) => a.localeCompare(b))
        .map(([year, vals]) => {
          const sum = vals.reduce((a, b) => a + b, 0);
          return { date: `${year}-01-01`, label: year, value: sum,
                   yoy_change_pct: null, mom_change_pct: null };
        });
      for (let i = 1; i < series.length; i++) {
        const prev = series[i - 1].value;
        if (prev) series[i].yoy_change_pct = (series[i].value - prev) / Math.abs(prev) * 100;
      }
    }

    if (!currentRange) return series;
    const pts = series.filter(p => p.value != null);
    if (!pts.length) return series;
    const lastDate = new Date(pts[pts.length - 1].date);
    const cutoff = new Date(lastDate);
    cutoff.setFullYear(cutoff.getFullYear() - currentRange);
    cutoff.setDate(1);
    return series.filter(p => new Date(p.date) >= cutoff);
  }

  function buildChart() {
    if (!chartInstance) {
      chartInstance = echarts.init(elChartWrap, null, { renderer: 'svg' });
      window.addEventListener('resize', () => chartInstance.resize());
    }
    const series  = getFiltered();
    const isBar   = indicator.chart_type === 'bar';
    const isDelta = currentMode === 'yoy' || currentMode === 'mom';
    const pp      = isPp();
    const isPercent = indicator.unit === '%';

    // Метки оси X — двухстрочные для месячных, без наклона
    const xData = series.map(p => {
      if (p.label) {
        // Если label содержит пробел (напр. «Янв 2024») — делаем двустрочным
        if (indicator.periodicity === 'monthly' && p.label.includes(' ') && !p.label.startsWith('Q')) {
          const parts = p.label.split(' ');
          // «Январь 2024» → «янв.\n2024»
          const mon = parts[0].slice(0, 3).toLowerCase() + '.';
          return `${mon}\n${parts[parts.length - 1]}`;
        }
        return p.label;
      }
      return fmtDate(p.date, indicator.periodicity);
    });

    let yData, seriesName, useBar;

    if (currentMode === 'yoy') {
      yData = series.map(p => p.yoy_change_pct != null ? Number(p.yoy_change_pct) : null);
      seriesName = 'Значение';
      useBar = true;
    } else if (currentMode === 'mom') {
      yData = series.map(p => p.mom_change_pct != null ? Number(p.mom_change_pct) : null);
      seriesName = 'Значение';
      useBar = true;
    } else {
      yData = series.map(p => p.value != null ? Number(p.value) : null);
      seriesName = 'Значение';
      useBar = isBar;
    }

    const dec = isDelta
      ? (pp ? 2 : 1)
      : axisDecimals(yData);

    // Форматтер оси Y
    const yAxisFormatter = v => {
      if (isDelta) {
        const sign = v > 0 ? '+' : v < 0 ? '−' : '';
        return pp
          ? `${sign}${fmtNum(Math.abs(v), 2)} п.п.`
          : `${sign}${fmtNum(Math.abs(v), 1)}%`;
      }
      if (isPercent) {
        const sign = v < 0 ? '−' : '';
        return `${sign}${fmtNum(Math.abs(v), dec)}%`;
      }
      // Абсолютные: разделитель разрядов, без единиц
      const sign = v < 0 ? '−' : '';
      return `${sign}${fmtNum(Math.abs(v), dec)}`;
    };

    // Форматтер tooltip — единица только в значении
    const tooltipFormatter = p => {
      const pt = p[0];
      if (pt.value == null) return `${pt.axisValue}<br/><span style="color:#7A8B9A">нет данных</span>`;
      const v = Number(pt.value);
      let valStr;
      if (isDelta) {
        const sign = v > 0 ? '+' : v < 0 ? '−' : '';
        valStr = pp
          ? `${sign}${fmtNum(Math.abs(v), 2)} п.п.`
          : `${sign}${fmtNum(Math.abs(v), 1)}%`;
      } else if (isPercent) {
        valStr = `${fmtNum(v, dec)}%`;
      } else {
        valStr = fmtValue(v, indicator.unit);
      }
      // Однострочный период для tooltip (без \n)
      const axisLabel = pt.axisValue.replace('\n', ' ');
      return `<b>${axisLabel}</b><br/>Значение: <b>${valStr}</b>`;
    };

    // Интервал меток оси X — чтобы не слипались
    const total = xData.length;
    let xInterval = 'auto';
    if (indicator.periodicity === 'monthly') {
      if (total > 120) xInterval = 11;
      else if (total > 60) xInterval = 5;
      else if (total > 24) xInterval = 2;
    } else if (indicator.periodicity === 'quarterly') {
      if (total > 20) xInterval = 3;   // каждый год (каждые 4 квартала)
      else if (total > 8) xInterval = 1;
    }

    chartInstance.setOption({
      animation: true,
      animationDuration: 200,
      animationEasing: 'cubicOut',
      grid: { left: 72, right: 20, top: 20, bottom: 90 },
      dataZoom: [
        {
          type: 'slider',
          bottom: 8,
          height: 24,
          borderColor: '#DDE2E8',
          backgroundColor: '#F2F4F7',
          fillerColor: 'rgba(232,52,28,0.10)',
          handleStyle: { color: '#E8341C', borderColor: '#E8341C', borderWidth: 2 },
          moveHandleStyle: { color: '#E8341C', opacity: 0.8 },
          emphasis: {
            handleStyle: { color: '#C4240E', borderColor: '#C4240E' },
            moveHandleStyle: { color: '#C4240E' },
          },
          selectedDataBackground: {
            lineStyle: { color: '#E8341C', width: 1 },
            areaStyle: { color: 'rgba(232,52,28,0.08)' },
          },
          dataBackground: {
            lineStyle: { color: '#DDE2E8', width: 1 },
            areaStyle: { color: 'rgba(221,226,232,0.3)' },
          },
          textStyle: { fontFamily: 'IBM Plex Sans', fontSize: 10, color: '#7A8B9A' },
          brushSelect: false,
          showDetail: true,
          throttle: 16,
        },
        {
          type: 'inside',
          zoomOnMouseWheel: true,
          moveOnMouseMove: true,
          throttle: 16,
        },
      ],
      tooltip: {
        trigger: 'axis',
        backgroundColor: '#0D1B2A',
        borderColor: '#0D1B2A',
        textStyle: { color: '#fff', fontFamily: 'IBM Plex Sans', fontSize: 13 },
        formatter: tooltipFormatter,
      },
      xAxis: {
        type: 'category',
        data: xData,
        axisLabel: {
          fontFamily: 'IBM Plex Sans',
          fontSize: 11,
          color: '#7A8B9A',
          rotate: 0,           // всегда горизонтально
          interval: xInterval,
          lineHeight: 16,      // для двустрочных меток
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
          formatter: yAxisFormatter,
        },
        splitLine: { lineStyle: { color: '#DDE2E8', type: 'dashed' } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series: [{
        name: seriesName,
        type: useBar ? 'bar' : 'line',
        data: yData,
        smooth: !useBar,
        symbol: yData.length < 60 ? 'circle' : 'none',
        symbolSize: 4,
        lineStyle: { width: 2, color: '#E8341C' },
        itemStyle: { color: p => isDelta ? (p.value >= 0 ? '#0E7C56' : '#C0392B') : '#E8341C' },
        areaStyle: (!useBar && !isDelta) ? {
          color: { type: 'linear', x: 0, y: 0, x2: 0, y2: 1,
            colorStops: [{ offset: 0, color: 'rgba(232,52,28,.18)' }, { offset: 1, color: 'rgba(232,52,28,.02)' }] }
        } : undefined,
        connectNulls: false,
        markLine: isDelta ? {
          data: [{ yAxis: 0 }],
          lineStyle: { color: '#DDE2E8', type: 'solid' },
          label: { show: false }, symbol: 'none',
        } : undefined,
      }],
    }, true);
  }

  function renderTable() {
    const series   = [...getFiltered()].reverse();
    const showMom  = indicator.periodicity !== 'annual';
    const pp       = isPp();
    const isPercent = indicator.unit === '%';
    const momLabel = indicator.periodicity === 'quarterly' ? 'кв./кв.' : 'м/м';

    // Единица для динамики: п.п. для процентных, % для остальных
    const dynUnit = pp ? 'п.п.' : '%';

    const thead = document.querySelector('.data-table thead tr');
    if (thead) {
      thead.innerHTML = `
        <th>Период</th>
        <th style="text-align:right">Значение${indicator.unit ? ', ' + indicator.unit : ''}</th>
        <th style="text-align:right">ИЗМ. Г/Г</th>
        ${showMom ? `<th style="text-align:right">ИЗМ. М/М</th>` : ''}
      `;
    }

    // Форматтер значений динамики — с единицами
    const fmtDyn = (val, isPpFlag) => {
      if (val == null) return '—';
      const n = Number(val);
      const threshold = isPpFlag ? 0.001 : 0.05;
      if (Math.abs(n) < threshold) return `<span class="delta flat">0 ${dynUnit}</span>`;
      const cls = n > 0 ? 'up' : 'down';
      const arrow = n > 0 ? '↑' : '↓';
      const abs = isPpFlag ? fmtNum(Math.abs(n), 2) : fmtNum(Math.abs(n), 1);
      return `<span class="delta ${cls}">${arrow} ${abs} ${dynUnit}</span>`;
    };

    elTableBody.innerHTML = series.map(p => `
      <tr>
        <td>${p.label ? p.label.replace('\n', ' ') : fmtDateInline(p.date, indicator.periodicity)}</td>
        <td class="num ${p.is_preliminary ? 'prelim' : ''}">${p.value != null ? fmtValue(p.value) : '—'}</td>
        <td class="num">${fmtDyn(p.yoy_change_pct, pp)}</td>
        ${showMom ? `<td class="num">${fmtDyn(p.mom_change_pct, pp)}</td>` : ''}
      </tr>
    `).join('');
  }

  async function loadRelated() {
    if (!indicator?.category || !elRelated) return;
    try {
      const list = await api.categoryIndicators(indicator.category.code);
      const others = list.filter(i => i.code !== indCode).slice(0, 4);
      elRelated.innerHTML = others.map(i => `
        <a href="chart.html?code=${i.code}" class="related-card">
          <div class="related-card-name">${cleanName(i.name)}</div>
          <div class="related-card-value">${i.last_value != null ? fmtValue(i.last_value) : '—'}</div>
          <div class="related-card-unit">${i.unit || ''} &nbsp; ${deltaHtml(i.yoy_change_pct, i.unit === '%')}</div>
        </a>
      `).join('');
    } catch (e) { /* silence */ }
  }

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
    const a = document.createElement('a'); a.href = url; a.download = `chart_${indCode}.png`; a.click();
  });

  document.getElementById('btn-download-xlsx')?.addEventListener('click', () => {
    window.open(api.indicatorXlsx(indCode));
  });

  const searchInput = document.getElementById('search-input');
  if (searchInput) {
    let timer;
    searchInput.addEventListener('input', () => {
      clearTimeout(timer);
      timer = setTimeout(async () => {
        const q = searchInput.value.trim();
        if (q.length < 2) { document.getElementById('search-results')?.remove(); return; }
        try { showSearchDropdown(await api.search(q)); } catch (e) { /* silence */ }
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
         padding:10px 16px;border-bottom:1px solid var(--color-border);font-size:.83rem;color:var(--color-ink);"
         onmouseover="this.style.background='var(--color-bg)'" onmouseout="this.style.background=''">
        <span style="font-family:var(--font-mono);font-size:.72rem;color:var(--color-muted);background:var(--color-bg);padding:2px 6px;border-radius:3px">${r.code}</span>
        <span style="flex:1">${cleanName(r.name)}</span>
        <span style="font-size:.72rem;color:var(--color-muted)">${r.category_name || ''}</span>
      </a>
    `).join('');
    const wrap = document.querySelector('.header-search');
    if (wrap) { wrap.style.position = 'relative'; wrap.appendChild(div); }
    document.addEventListener('click', e => { if (!wrap?.contains(e.target)) div.remove(); }, { once: true });
  }

  init();
})();
