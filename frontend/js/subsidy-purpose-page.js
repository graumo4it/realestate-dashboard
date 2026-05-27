(function () {
  const PROGRAMS = {
    all: {
      key: 'all',
      base: '6.52',
      title: 'Цели кредитования: все программы',
      nav: 'Все',
      file: 'subsidy-purpose-all',
      goals: ['ddu', 'dkp_dev', 'izhs', 'house', 'secondary'],
    },
    lgota: {
      key: 'lgota',
      base: '6.53',
      title: 'Цели кредитования: льготная ипотека',
      nav: 'Льготная',
      file: 'subsidy-purpose-lgota',
      goals: ['ddu', 'dkp_dev', 'izhs', 'house', 'secondary'],
    },
    semya: {
      key: 'semya',
      base: '6.54',
      title: 'Цели кредитования: семейная ипотека',
      nav: 'Семейная',
      file: 'subsidy-purpose-semya',
      goals: ['ddu', 'dkp_dev', 'izhs', 'house', 'secondary_no_build', 'secondary_other'],
    },
    dv: {
      key: 'dv',
      base: '6.55',
      title: 'Цели кредитования: ДВ и Арктика',
      nav: 'ДВ и Арктика',
      file: 'subsidy-purpose-dv',
      goals: ['ddu', 'dkp_dev', 'izhs', 'house', 'secondary'],
    },
    it: {
      key: 'it',
      base: '6.56',
      title: 'Цели кредитования: IT-ипотека',
      nav: 'IT',
      file: 'subsidy-purpose-it',
      goals: ['ddu', 'dkp_dev', 'izhs', 'house', 'secondary'],
    },
    regions: {
      key: 'regions',
      base: '6.57',
      title: 'Цели кредитования: отдельные регионы',
      nav: 'Отдельные регионы',
      file: 'subsidy-purpose-regions',
      goals: ['ddu', 'dkp_dev', 'izhs', 'house', 'secondary'],
    },
  };

  const GOALS = {
    ddu: {
      suffix: '1',
      label: 'Покупка по ДДУ',
      short: 'ДДУ',
      color: '#E8341C',
    },
    dkp_dev: {
      suffix: '2',
      label: 'Покупка по ДКП у застройщика',
      short: 'ДКП у застройщика',
      kpiShort: 'ДКП застройщика',
      color: '#1A2B4A',
    },
    izhs: {
      suffix: '3',
      label: 'Индивидуальное жилищное строительство',
      short: 'ИЖС',
      color: '#F4A336',
    },
    house: {
      suffix: '4',
      label: 'Готовый индивидуальный жилой дом',
      short: 'Готовый ИЖД',
      color: '#2EC4B6',
    },
    secondary: {
      suffix: '5',
      label: 'Покупка квартир по ДКП на вторичке',
      short: 'Вторичка',
      color: '#8B5CF6',
    },
    secondary_no_build: {
      suffix: '5',
      label: 'Покупка квартир по ДКП на вторичке в городах без стройки',
      short: 'Вторичка: без стройки',
      kpiShort: 'Без стройки',
      color: '#8B5CF6',
    },
    secondary_other: {
      suffix: '6',
      label: 'Покупка квартир по ДКП на вторичке, прочее',
      short: 'Вторичка: прочее',
      kpiShort: 'Прочее',
      color: '#16a34a',
    },
  };

  const METRICS = {
    count: { suffix: '1', label: 'Количество', unit: 'шт.', decimals: 0 },
    volume: { suffix: '2', label: 'Объём', unit: 'млн руб.', decimals: 0 },
  };

  const PROGRAM_ORDER = ['all', 'lgota', 'semya', 'dv', 'it', 'regions'];

  const state = {
    program: null,
    allData: {},
    chart: null,
    metric: 'count',
    currentPeriodicity: 'monthly',
    currentRange: null,
    currentMode: 'absolute',
    currentTable: null,
    activeSeries: new Set(),
  };

  function codeFor(goalKey, metricKey = state.metric) {
    const goal = GOALS[goalKey];
    const metric = METRICS[metricKey];
    return `${state.program.base}.${goal.suffix}.${metric.suffix}`;
  }

  function codeForProgram(program, goalKey, metricKey) {
    const goal = GOALS[goalKey];
    const metric = METRICS[metricKey];
    return `${program.base}.${goal.suffix}.${metric.suffix}`;
  }

  function selectedCodes(metricKey = state.metric) {
    return state.program.goals.map(goalKey => codeFor(goalKey, metricKey));
  }

  function selectedLabels() {
    return state.program.goals.map(goalKey => GOALS[goalKey].short);
  }

  function metricConfig() {
    return METRICS[state.metric];
  }

  function setText(id, text) {
    const el = document.getElementById(id);
    if (el) el.textContent = text;
  }

  function initStaticUi() {
    syncProgramTitle();
    renderProgramNav();
    renderKpiCards();
    renderTableTabs();
    buildDropdown();
    buildToolbar();
    updateMetricLabels();
  }

  function syncProgramTitle() {
    document.title = `${state.program.title} — Рынок недвижимости России`;
    setText('page-title', state.program.title);
    setText('breadcrumb-current', state.program.title);
  }

  function renderProgramNav() {
    const nav = document.getElementById('program-nav');
    if (!nav) return;
    nav.innerHTML = PROGRAM_ORDER.map(key => {
      const p = PROGRAMS[key];
      const active = key === state.program.key ? ' active' : '';
      return `<button type="button" class="program-tab${active}" data-program="${key}">${p.nav}</button>`;
    }).join('');
  }

  function renderKpiCards() {
    const row = document.getElementById('kpi-row');
    if (!row) return;
    row.style.setProperty('--kpi-count', String(state.program.goals.length));
    row.innerHTML = state.program.goals.map(goalKey => {
      const goal = GOALS[goalKey];
      return `<div class="kpi-card-sm" data-kpi="${goalKey}">
        <div class="kpi-label"><span class="kpi-dot" style="background:${goal.color}"></span>${goal.kpiShort || goal.short}</div>
        <div class="kpi-value" id="kpi-${goalKey}-value">—</div>
        <div class="kpi-period" id="kpi-${goalKey}-period">—</div>
        <div class="kpi-deltas" id="kpi-${goalKey}-deltas"></div>
      </div>`;
    }).join('');
  }

  function renderTableTabs() {
    const tabs = document.getElementById('table-tabs');
    if (!tabs) return;
    state.currentTable = state.program.goals[0];
    tabs.innerHTML = state.program.goals.map((goalKey, idx) => (
      `<button class="table-tab${idx === 0 ? ' active' : ''}" data-table="${goalKey}">${GOALS[goalKey].short}</button>`
    )).join('');
  }

  function buildToolbar() {
    const controls = document.getElementById('toolbar-controls');
    const toolbar = document.querySelector('.chart-toolbar');
    if (!controls || !toolbar) return;

    const rangeGroup = document.createElement('div');
    rangeGroup.className = 'btn-group';
    rangeGroup.innerHTML = [
      ['1', '1 год'],
      ['3', '3 года'],
      ['5', '5 лет'],
      ['all', 'За все время'],
    ].map(([value, label]) => (
      `<button type="button" data-range="${value}" class="${value === 'all' ? 'active' : ''}">${label}</button>`
    )).join('');
    controls.appendChild(rangeGroup);

    const modeGroup = document.createElement('div');
    modeGroup.className = 'btn-group';
    modeGroup.innerHTML = [
      ['absolute', 'Значения'],
      ['yoy', 'Изм. г/г'],
      ['mom', 'Изм. м/м'],
    ].map(([value, label]) => (
      `<button type="button" data-mode="${value}" class="${value === 'absolute' ? 'active' : ''}">${label}</button>`
    )).join('');
    controls.appendChild(modeGroup);

    PeriodToggle.injectButtons(toolbar, {
      options: ['monthly', 'quarterly', 'annual'],
      defaultValue: 'monthly',
    }, periodicity => {
      state.currentPeriodicity = periodicity;
      const momBtn = document.querySelector('[data-mode="mom"]');
      if (momBtn) {
        const hide = periodicity !== 'monthly';
        momBtn.style.display = hide ? 'none' : '';
        if (hide && state.currentMode === 'mom') {
          state.currentMode = 'absolute';
          document.querySelectorAll('[data-mode]').forEach(btn => {
            btn.classList.toggle('active', btn.dataset.mode === 'absolute');
          });
        }
      }
      rebuild();
    });

    const metricGroup = document.createElement('div');
    metricGroup.className = 'btn-group';
    metricGroup.setAttribute('data-metric-toggle', 'true');
    metricGroup.innerHTML = Object.entries(METRICS).map(([key, metric]) => (
      `<button type="button" data-metric="${key}" class="${key === state.metric ? 'active' : ''}">${metric.label}</button>`
    )).join('');
    const periodGroup = controls.querySelector('[data-period-toggle]');
    if (periodGroup) periodGroup.insertAdjacentElement('afterend', metricGroup);
    else controls.appendChild(metricGroup);
  }

  function buildDropdown() {
    const dropdown = document.getElementById('series-dropdown');
    if (!dropdown) return;
    state.activeSeries = new Set(state.program.goals);
    dropdown.innerHTML = state.program.goals.map(goalKey => {
      const goal = GOALS[goalKey];
      return `<div class="filter-dropdown-item" data-key="${goalKey}">
        <input type="checkbox" id="cb-${goalKey}" checked>
        <span class="kpi-dot" style="background:${goal.color}"></span>
        <span>${goal.label}</span>
      </div>`;
    }).join('');
    updateFilterButton();
  }

  function updateMetricLabels() {
    const metric = metricConfig();
    setText('chart-unit', metric.unit);
    const thCells = document.querySelectorAll('.data-table thead th');
    if (thCells.length >= 2) thCells[1].textContent = `Значение, ${metric.unit}`;
  }

  function filteredSeries(goalKey) {
    const raw = state.allData[codeFor(goalKey)]?.series || [];

    if (state.currentPeriodicity !== 'monthly') {
      const agg = PeriodToggle.aggregate(raw, state.currentPeriodicity, 'sum');
      if (!state.currentRange) return agg;
      const cutoff = new Date();
      cutoff.setFullYear(cutoff.getFullYear() - state.currentRange);
      return agg.filter(point => new Date(point.date) >= cutoff);
    }

    if (!state.currentRange) return raw;
    const points = raw.filter(point => point.value != null);
    if (!points.length) return raw;
    const lastDate = new Date(points[points.length - 1].date);
    const cutoff = new Date(lastDate);
    cutoff.setFullYear(cutoff.getFullYear() - state.currentRange);
    cutoff.setDate(1);
    return raw.filter(point => new Date(point.date) >= cutoff);
  }

  function latestPoint(goalKey) {
    const series = filteredSeries(goalKey).filter(point => point.value != null);
    return series[series.length - 1] || null;
  }

  function deltaKpiHtml(value) {
    return value == null ? '<span class="delta-placeholder">—</span>' : deltaHtml(value);
  }

  function rebuildKpis() {
    const metric = metricConfig();
    state.program.goals.forEach(goalKey => {
      const point = latestPoint(goalKey);
      const valueEl = document.getElementById(`kpi-${goalKey}-value`);
      const periodEl = document.getElementById(`kpi-${goalKey}-period`);
      const deltasEl = document.getElementById(`kpi-${goalKey}-deltas`);

      if (!point) {
        if (valueEl) valueEl.textContent = '—';
        if (periodEl) periodEl.textContent = `${metric.unit} · —`;
        if (deltasEl) deltasEl.innerHTML =
          '<span>г/г: <span class="delta-placeholder">—</span></span>' +
          '<span>м/м: <span class="delta-placeholder">—</span></span>';
        return;
      }

      if (valueEl) valueEl.textContent = fmtNum(Number(point.value), metric.decimals);
      if (periodEl) periodEl.textContent = `${metric.unit} · ${point.label || fmtDateInline(point.date, state.currentPeriodicity)}`;
      if (deltasEl) {
        const secondLabel = state.currentPeriodicity === 'quarterly' ? 'к/к' : 'м/м';
        deltasEl.innerHTML =
          `<span>г/г: ${deltaKpiHtml(point.yoy_change_pct)}</span>` +
          `<span>${secondLabel}: ${deltaKpiHtml(point.mom_change_pct)}</span>`;
      }
    });
  }

  function rebuildChart() {
    const container = document.getElementById('main-chart');
    if (!container) return;
    if (!state.chart) {
      state.chart = echarts.init(container, null, { renderer: 'canvas' });
      window.addEventListener('resize', () => state.chart.resize());
    }

    const metric = metricConfig();
    const isDelta = state.currentMode !== 'absolute';
    const field = state.currentMode === 'yoy' ? 'yoy_change_pct' : 'mom_change_pct';
    const active = state.program.goals.filter(goalKey => state.activeSeries.has(goalKey));
    const allDates = [...new Set(active.flatMap(goalKey => filteredSeries(goalKey).map(point => point.date || point.label)))].sort();

    const maps = {};
    active.forEach(goalKey => {
      maps[goalKey] = {};
      filteredSeries(goalKey).forEach(point => {
        maps[goalKey][point.date || point.label] = point;
      });
    });

    const xData = allDates.map(dateKey => {
      for (const goalKey of active) {
        const point = maps[goalKey][dateKey];
        if (point?.label) return formatXAxisLabel(point.label, point.date || dateKey, state.currentPeriodicity);
      }
      return formatXAxisLabel('', dateKey, state.currentPeriodicity);
    });

    const xInterval = xAxisLabelInterval(xData.length, state.currentPeriodicity);

    const series = active.map(goalKey => {
      const goal = GOALS[goalKey];
      const data = allDates.map(dateKey => {
        const point = maps[goalKey][dateKey];
        if (!point || point.value == null) return null;
        return isDelta ? (point[field] != null ? Number(point[field]) : null) : Number(point.value);
      });

      if (!isDelta) {
        return {
          name: goal.short,
          type: 'bar',
          stack: 'total',
          data,
          itemStyle: { color: goal.color },
          emphasis: { focus: 'series' },
          barMaxWidth: state.currentPeriodicity !== 'monthly' ? 40 : 24,
        };
      }

      return {
        name: goal.short,
        type: 'line',
        data,
        lineStyle: { color: goal.color, width: 2.5 },
        itemStyle: { color: goal.color },
        symbol: allDates.length < 60 ? 'circle' : 'none',
        symbolSize: 4,
        connectNulls: false,
      };
    });

    const fmtDelta = value => value == null ? '—' : `${value > 0 ? '+' : ''}${fmtNum(value, 2)}%`;

    state.chart.setOption({
      animation: true,
      animationDuration: 200,
      legend: {
        data: active.map(goalKey => GOALS[goalKey].short),
        top: 0,
        left: 0,
        textStyle: { fontFamily: 'IBM Plex Sans', fontSize: 12, color: '#3D4F60' },
        icon: 'circle',
        itemWidth: 10,
        itemHeight: 10,
      },
      grid: { left: 70, right: 20, top: 40, bottom: 80 },
      dataZoom: [
        {
          type: 'slider',
          bottom: 8,
          height: 24,
          borderColor: '#DDE2E8',
          backgroundColor: '#F2F4F7',
          fillerColor: 'rgba(26,43,74,0.10)',
          handleStyle: { color: '#1A2B4A', borderColor: '#1A2B4A', borderWidth: 2 },
          textStyle: { fontFamily: 'IBM Plex Sans', fontSize: 10, color: '#7A8B9A' },
          brushSelect: false,
          throttle: 16,
        },
        { type: 'inside', throttle: 16 },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: !isDelta ? 'shadow' : 'line' },
        backgroundColor: '#0D1B2A',
        borderColor: '#0D1B2A',
        textStyle: { color: '#fff', fontFamily: 'IBM Plex Sans', fontSize: 13 },
        formatter: params => {
          let html = `<b>${cleanAxisLabel(params[0]?.axisValue)}</b><br/>`;
          let total = 0;
          params.forEach(param => {
            if (param.value == null) return;
            const val = isDelta
              ? fmtDelta(param.value)
              : `${fmtNum(param.value, metric.decimals)} ${metric.unit}`;
            html += `<span style="color:${param.color}">●</span> ${param.seriesName}: <b>${val}</b><br/>`;
            if (!isDelta) total += Number(param.value);
          });
          if (!isDelta && params.length > 1) {
            html += `<span style="color:#aaa">Итого: <b>${fmtNum(total, metric.decimals)} ${metric.unit}</b></span>`;
          }
          return html;
        },
      },
      xAxis: {
        type: 'category',
        data: xData,
        axisLabel: {
          fontFamily: 'IBM Plex Sans',
          fontSize: 11,
          color: '#7A8B9A',
          rotate: 0,
          interval: xInterval,
          lineHeight: 16,
          showMinLabel: false,
          showMaxLabel: true,
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
          formatter: value => isDelta ? fmtDelta(value) : fmtNum(value, metric.decimals),
        },
        splitLine: { lineStyle: { color: '#DDE2E8', type: 'dashed' } },
        axisLine: { show: false },
        axisTick: { show: false },
      },
      series,
    }, true);
  }

  function rebuildTable() {
    const body = document.getElementById('data-table-body');
    if (!body) return;

    const metric = metricConfig();
    const series = filteredSeries(state.currentTable).slice().reverse();
    body.innerHTML = series.map(point => {
      const value = point.value != null ? `${fmtNum(Number(point.value), metric.decimals)} ${metric.unit}` : '—';
      const mom = state.currentPeriodicity === 'monthly' ? deltaHtml(point.mom_change_pct) : '—';
      const label = point.label || (point.date ? fmtDateInline(point.date, state.currentPeriodicity) : '—');
      return `<tr>
        <td>${label}</td>
        <td class="num">${value}</td>
        <td class="num">${deltaHtml(point.yoy_change_pct)}</td>
        <td class="num">${mom}</td>
      </tr>`;
    }).join('') || '<tr><td colspan="4" style="text-align:center;color:var(--color-muted);padding:24px">Нет данных</td></tr>';
  }

  function rebuild() {
    updateMetricLabels();
    rebuildKpis();
    rebuildChart();
    rebuildTable();
  }

  function switchProgram(programKey) {
    const nextProgram = PROGRAMS[programKey];
    if (!nextProgram || nextProgram.key === state.program.key) return;

    state.program = nextProgram;
    state.currentTable = state.program.goals[0];
    syncProgramTitle();
    renderProgramNav();
    renderKpiCards();
    renderTableTabs();
    buildDropdown();
    rebuild();
  }

  function bindEvents() {
    document.addEventListener('click', event => {
      const programBtn = event.target.closest('[data-program]');
      if (programBtn) {
        switchProgram(programBtn.dataset.program);
        return;
      }

      const metricBtn = event.target.closest('[data-metric]');
      if (metricBtn) {
        state.metric = metricBtn.dataset.metric;
        document.querySelectorAll('[data-metric]').forEach(btn => btn.classList.toggle('active', btn === metricBtn));
        rebuild();
        return;
      }

      const rangeBtn = event.target.closest('[data-range]');
      if (rangeBtn) {
        state.currentRange = rangeBtn.dataset.range === 'all' ? null : Number(rangeBtn.dataset.range);
        document.querySelectorAll('[data-range]').forEach(btn => btn.classList.toggle('active', btn === rangeBtn));
        rebuild();
        return;
      }

      const modeBtn = event.target.closest('[data-mode]');
      if (modeBtn) {
        state.currentMode = modeBtn.dataset.mode;
        document.querySelectorAll('[data-mode]').forEach(btn => btn.classList.toggle('active', btn === modeBtn));
        rebuildChart();
        return;
      }

      const tableBtn = event.target.closest('[data-table]');
      if (tableBtn) {
        state.currentTable = tableBtn.dataset.table;
        document.querySelectorAll('[data-table]').forEach(btn => btn.classList.toggle('active', btn === tableBtn));
        rebuildTable();
        return;
      }

      const dropdownItem = event.target.closest('.filter-dropdown-item');
      if (dropdownItem) {
        const key = dropdownItem.dataset.key;
        const checkbox = dropdownItem.querySelector('input');
        if (event.target !== checkbox) checkbox.checked = !checkbox.checked;
        if (checkbox.checked) {
          state.activeSeries.add(key);
        } else {
          if (state.activeSeries.size <= 1) {
            checkbox.checked = true;
            return;
          }
          state.activeSeries.delete(key);
        }
        updateFilterButton();
        rebuildChart();
        return;
      }

      const filterBtn = event.target.closest('#btn-filter-series');
      if (filterBtn) {
        const dropdown = document.getElementById('series-dropdown');
        if (dropdown) dropdown.style.display = dropdown.style.display === 'none' ? 'block' : 'none';
        return;
      }

      const dropdown = document.getElementById('series-dropdown');
      if (dropdown) dropdown.style.display = 'none';
    });

    const resetBtn = document.getElementById('btn-reset-filters');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        state.activeSeries = new Set(state.program.goals);
        state.program.goals.forEach(goalKey => {
          const cb = document.getElementById(`cb-${goalKey}`);
          if (cb) cb.checked = true;
        });
        updateFilterButton();
        rebuildChart();
      });
    }

    const pngBtn = document.getElementById('btn-download-png');
    if (pngBtn) {
      pngBtn.addEventListener('click', () => {
        if (!state.chart) return;
        const link = document.createElement('a');
        link.href = state.chart.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' });
        link.download = `${state.program.file}-${state.metric}.png`;
        link.click();
      });
    }

    const xlsxBtn = document.getElementById('btn-download-xlsx');
    if (xlsxBtn) {
      xlsxBtn.addEventListener('click', () => {
        const codes = selectedCodes().join(',');
        const labels = encodeURIComponent(selectedLabels().join(','));
        const filename = `${state.program.file}-${state.metric}`;
        window.open(`${window.API_BASE}/multi/data.xlsx?codes=${codes}&labels=${labels}&filename=${filename}`);
      });
    }
  }

  function updateFilterButton() {
    const btn = document.getElementById('btn-filter-series');
    if (!btn) return;
    btn.classList.toggle('has-active', state.activeSeries.size !== state.program.goals.length);
  }

  async function init() {
    state.program = PROGRAMS.all;
    state.currentTable = state.program.goals[0];
    initStaticUi();
    bindEvents();

    const codes = [...new Set(PROGRAM_ORDER.flatMap(programKey => {
      const program = PROGRAMS[programKey];
      return Object.keys(METRICS).flatMap(metricKey => (
        program.goals.map(goalKey => codeForProgram(program, goalKey, metricKey))
      ));
    }))];
    state.allData = await api.multiIndicatorData(codes.join(','));

    const dates = Object.values(state.allData).map(entry => entry.indicator?.last_updated).filter(Boolean);
    if (dates.length) {
      setText('chart-updated', new Date(dates[0]).toLocaleDateString('ru-RU'));
    }

    rebuild();
  }

  init().catch(error => {
    console.error(error);
    const container = document.getElementById('main-chart');
    if (container) {
      container.innerHTML = `<div style="padding:24px;color:#dc2626">Ошибка загрузки данных: ${error.message}</div>`;
    }
  });
})();
