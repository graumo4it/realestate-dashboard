/**
 * Логика страницы chart.html
 * Правки v1.2:
 *   - кнопки тулбара «1 год / 3 года / 5 лет»
 *   - ось X: горизонтальные двухстрочные метки (янв\n2024), без наклона
 *   - ось Y: знак «-» для отрицательных, «%» если ед. изм. %, разделитель разрядов
 *   - tooltip: единица только в значении, не в названии серии
 *   - таблица: единица только в заголовке значения; динамика с ед. в ячейках
 */
(function () {
  const params  = new URLSearchParams(location.search);
  const indCode = params.get('code');
  if (!indCode) { document.body.innerHTML = '<p style="padding:2rem">Укажите код показателя (?code=6.1)</p>'; return; }

  let chartInstance = null;
  let allSeries     = [];
  let annualSeries  = null; // официальные годовые значения из <code>.y, если есть
  let indicator     = null;
  let currentMode        = 'absolute'; // 'absolute' | 'yoy' | 'mom'
  let currentRange       = null;
  let currentPeriodicity = 'quarterly'; // 'quarterly' | 'annual' — только для квартальных
  let currentMonthlyPeriodicity = 'monthly'; // 'monthly' | 'quarterly' | 'annual' — для месячных с агрегацией

  const elTitle      = document.getElementById('chart-title');
  const elSource     = document.getElementById('chart-source-name');
  const elPeriodType = document.getElementById('chart-period-type');
  const elKpiValue  = document.getElementById('kpi-last-value');
  const elKpiUnit   = document.getElementById('kpi-last-unit');
  const elKpiPeriod = document.getElementById('kpi-last-period');
  const elKpiDelta  = document.getElementById('kpi-delta');
  const elTableBody = document.getElementById('data-table-body');
  const elChartWrap = document.getElementById('main-chart');
  const elRelated   = document.getElementById('related-grid');
  const elBreadCat  = document.getElementById('breadcrumb-cat');

  // Коды месячных индикаторов, для которых доступна агрегация Месяц/Квартал/Год
  const MONTHLY_AGG_CONFIG = {
    '5.8':      'sum',   // Количество сделок — квартиры
    'apt_area': 'avg',   // Средняя площадь сделок — квартиры
    '5.20':     'sum',   // Количество сделок — машиноместа
    '5.21':     'avg',   // Средняя площадь сделок — машиноместа
  };

  // Для бюджетов ось Y читается в млн руб., без изменения исходных значений.
  const Y_AXIS_LABEL_SCALE_CONFIG = {
    'apt_budget': { divisor: 1_000_000, decimals: 1 },
    '4.9':        { divisor: 1_000_000, decimals: 1 },
  };

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

      // Для квартальных показателей пробуем подгрузить официальные годовые значения
      // из индикатора-двойника <code>.y (is_public=false, создаётся миграцией 003).
      // Если двойника нет — getFiltered() падёт бэком на среднее из кварталов.
      if (indicator.periodicity === 'quarterly') {
        try {
          const annResult = await api.indicatorData(indCode + '.y');
          annualSeries = annResult.series.filter(p => p.value != null);
        } catch {
          annualSeries = null; // индикатора .y нет — будет avg-фолбэк
        }
      }

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
    elSource.textContent     = indicator.source?.name || '—';
    elPeriodType.textContent = periodTypeLabel(indicator.period_type || '');
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
        renderKPI();
      });
    }
    // Инжектировать кнопки Месяц/Квартал/Год для месячных индикаторов с агрегацией
    if (indicator.periodicity === 'monthly' && MONTHLY_AGG_CONFIG[indCode] && window.PeriodToggle) {
      const toolbar = document.querySelector('.chart-toolbar');
      PeriodToggle.injectButtons(toolbar, {
        options: ['monthly', 'quarterly', 'annual'],
        defaultValue: 'monthly',
        labels: { monthly: 'Месяц', quarterly: 'Квартал', annual: 'Год' },
      }, (periodicity) => {
        currentMonthlyPeriodicity = periodicity;
        const momBtn = document.querySelector('[data-mode="mom"]');
        if (momBtn) momBtn.style.display = periodicity === 'monthly' ? '' : 'none';
        if (periodicity !== 'monthly' && currentMode === 'mom') {
          document.querySelectorAll('[data-mode]').forEach(b => b.classList.remove('active'));
          document.querySelector('[data-mode="absolute"]').classList.add('active');
          currentMode = 'absolute';
        }
        buildChart();
        renderTable();
        renderKPI();
      });
    }
  }

  function renderKPI() {
    // Баг 1: читаем отфильтрованный ряд, а не allSeries
    const filtered = getFiltered();
    const pts = filtered.filter(p => p.value != null);
    if (!pts.length) return;
    const last = pts[pts.length - 1];
    elKpiValue.textContent  = fmtValue(last.value);
    elKpiUnit.textContent   = indicator.unit || '';
    // KPI период — однострочный формат
    elKpiPeriod.textContent = last.label || fmtDateInline(last.date, indicator.periodicity);

    const pp = isPp();
    const isAggQoQ = indicator.periodicity === 'quarterly' || currentMonthlyPeriodicity === 'quarterly';
    const momLabel = isAggQoQ ? 'кв./кв.' : 'м/м';
    const yoyHtml = last.yoy_change_pct != null
      ? `<span style="margin-right:12px">г/г: ${deltaHtml(last.yoy_change_pct, pp)}</span>` : '';
    // Скрывать кв./кв. дельту когда годовой вид; скрывать м/м когда агрегация в квартал/год
    const showMomDelta = last.mom_change_pct != null
      && indicator.periodicity !== 'annual'
      && currentPeriodicity !== 'annual'
      && currentMonthlyPeriodicity !== 'annual';
    const momHtml = showMomDelta
      ? `<span>${momLabel}: ${deltaHtml(last.mom_change_pct, pp)}</span>` : '';
    elKpiDelta.innerHTML = yoyHtml + momHtml;
  }

  function getFiltered() {
    let series = allSeries;

    // Агрегация месячных → квартальные/годовые
    if (indicator.periodicity === 'monthly' && MONTHLY_AGG_CONFIG[indCode] && currentMonthlyPeriodicity !== 'monthly') {
      series = PeriodToggle.aggregate(allSeries, currentMonthlyPeriodicity, MONTHLY_AGG_CONFIG[indCode]);
      // Применяем диапазон и возвращаем сразу (данные уже агрегированы)
      if (!currentRange) return series;
      const pts = series.filter(p => p.value != null);
      if (!pts.length) return series;
      const lastDate = new Date(pts[pts.length - 1].date);
      const cutoff = new Date(lastDate);
      cutoff.setFullYear(cutoff.getFullYear() - currentRange);
      return series.filter(p => new Date(p.date) >= cutoff);
    }

    // Агрегация квартальных → годовые
    if (indicator.periodicity === 'quarterly' && currentPeriodicity === 'annual') {
      if (annualSeries && annualSeries.length) {
        // Официальные годовые значения из индикатора-двойника <code>.y
        series = annualSeries.map(p => ({ ...p })); // копия, чтобы не мутировать
        // Пересчитываем г/г поверх официальных значений (в .y нет YoY из БД)
        for (let i = 1; i < series.length; i++) {
          const prev = series[i - 1].value;
          if (prev) series[i].yoy_change_pct = (series[i].value - prev) / Math.abs(prev) * 100;
        }
      } else {
        // Фолбэк: среднее из 4 кварталов (погрешность < 0.2%)
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
            const avg = vals.reduce((a, b) => a + b, 0) / vals.length;
            return { date: `${year}-01-01`, label: year, value: avg,
                     yoy_change_pct: null, mom_change_pct: null };
          });
        for (let i = 1; i < series.length; i++) {
          const prev = series[i - 1].value;
          if (prev) series[i].yoy_change_pct = (series[i].value - prev) / Math.abs(prev) * 100;
        }
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
    const yAxisLabelScale = !isDelta ? Y_AXIS_LABEL_SCALE_CONFIG[indCode] : null;

    // Эффективная периодичность: для месячных с агрегацией берём currentMonthlyPeriodicity
    const effPeriodicity = MONTHLY_AGG_CONFIG[indCode] ? currentMonthlyPeriodicity : indicator.periodicity;
    const xData = series.map(p => formatXAxisLabel(p.label, p.date, effPeriodicity));

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
      : yAxisLabelScale
        ? yAxisLabelScale.decimals
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
      const axisValue = yAxisLabelScale ? Math.abs(v) / yAxisLabelScale.divisor : Math.abs(v);
      return `${sign}${fmtNum(axisValue, dec)}`;
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
      const axisLabel = cleanAxisLabel(pt.axisValue);
      return `<b>${axisLabel}</b><br/>Значение: <b>${valStr}</b>`;
    };

    const xAxisCfg = xAxisLabelInterval(xData.length, effPeriodicity);

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
          handleStyle: { color: '#C8181A', borderColor: '#C8181A', borderWidth: 2 },
          moveHandleStyle: { color: '#C8181A', opacity: 0.8 },
          emphasis: {
            handleStyle: { color: '#A81416', borderColor: '#A81416' },
            moveHandleStyle: { color: '#A81416' },
          },
          selectedDataBackground: {
            lineStyle: { color: '#C8181A', width: 1 },
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
          interval: xAxisCfg.interval,
          lineHeight: 16,      // для двустрочных меток
          showMinLabel: xAxisCfg.showMinLabel,
          showMaxLabel: xAxisCfg.showMaxLabel,
          hideOverlap: false,
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
          showMinLabel: false,
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
        lineStyle: { width: 2, color: '#C8181A' },
        itemStyle: { color: p => isDelta ? (p.value >= 0 ? '#0E7C56' : '#C0392B') : '#C8181A' },
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
    // Учитываем currentPeriodicity (для квартальных) и currentMonthlyPeriodicity (для месячных с агрегацией)
    const showMom  = indicator.periodicity !== 'annual' && currentPeriodicity !== 'annual' && currentMonthlyPeriodicity !== 'annual';
    const pp       = isPp();
    const isPercent = indicator.unit === '%';
    const isAggQoQ = indicator.periodicity === 'quarterly' || currentMonthlyPeriodicity === 'quarterly';
    const momLabel = isAggQoQ ? 'кв./кв.' : 'м/м';

    // Единица для динамики: п.п. для процентных, % для остальных
    const dynUnit = pp ? 'п.п.' : '%';
    const fmtTableValue = (val) => {
      if (val == null || isNaN(Number(val))) return '—';
      const n = Number(val);
      return fmtNum(n, Math.abs(n) >= 1000 ? 0 : 2);
    };

    const thead = document.querySelector('.data-table thead tr');
    if (thead) {
      thead.innerHTML = `
        <th>Период</th>
        <th style="text-align:right">Значение${indicator.unit ? ', ' + indicator.unit : ''}</th>
        <th style="text-align:right">ИЗМ. Г/Г</th>
        ${showMom ? `<th style="text-align:right">ИЗМ. ${momLabel.toUpperCase()}</th>` : ''}
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
        <td class="num ${p.is_preliminary ? 'prelim' : ''}">${fmtTableValue(p.value)}</td>
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
