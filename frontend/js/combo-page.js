/**
 * combo-page.js  — deep module for multi-series combo pages
 * Usage: ComboPage.init(config).catch(console.error)
 *
 * Config shape:
 *   codes      {Object}  { key: 'indicator-code' | { value, weight } }
 *   labels     {Object}  { key: 'Label' }
 *   keys       {Array}   display order for filter + table + chart
 *   colors     {Object}  optional; defaults to brand palette
 *   chartType  {string}  'bar' | 'line'   (default: 'bar')
 *   aggType    {string}  'sum' | 'avg' | 'wavg'  (default: 'sum')
 *   unit       {string}  display suffix  (default: '')
 *   decimals   {number}  decimal places  (default: 0)
 *   fileName   {string}  PNG/XLSX base name  (default: 'combo')
 *   stackBars  {boolean} stack bars (default: true); false = grouped side-by-side
 *   onData     {Function} (allData) => void — called after fetch + every rebuild
 *   onTableHeader {Function} (mode) => string — optional table column override
 *
 * Extra codes: keys in config.codes that are NOT in config.keys are still fetched
 * and appear in allData (useful for KPI-only series like a pre-computed total).
 */
window.ComboPage = (function () {

  const BRAND_PALETTE = [
    '#E8341C', '#1A2B4A', '#F4A336', '#2EC4B6',
    '#8B5CF6', '#16a34a', '#0ea5e9', '#f59e0b'
  ];

  // ── 1. _normalizeConfig ────────────────────────────────────────────────
  function _normalizeConfig(config) {
    const keys = config.keys;
    if (!keys || !keys.length) throw new Error('ComboPage: config.keys is required');
    if (!config.codes)         throw new Error('ComboPage: config.codes is required');
    if (!config.labels)        throw new Error('ComboPage: config.labels is required');

    // Separate value codes and weight codes.
    // Process ALL keys in config.codes (not just config.keys) so extra codes
    // (e.g. a pre-computed total used only in the KPI hook) are fetched too.
    const valueCode  = {};
    const weightCode = {};
    Object.keys(config.codes).forEach(k => {
      const c = config.codes[k];
      if (typeof c === 'object' && c.value) {
        valueCode[k]  = c.value;
        weightCode[k] = c.weight || null;
      } else {
        valueCode[k]  = c;
        weightCode[k] = null;
      }
    });
    // Validate that all chart keys have codes
    keys.forEach(k => {
      if (!valueCode[k]) throw new Error(`ComboPage: config.codes["${k}"] is missing`);
    });

    // Default colors from palette
    const colors = {};
    keys.forEach((k, i) => {
      colors[k] = (config.colors && config.colors[k]) || BRAND_PALETTE[i % BRAND_PALETTE.length];
    });

    const aggType    = config.aggType    || 'sum';
    const chartType  = config.chartType  || 'bar';
    const stackBars  = config.stackBars  !== false;   // default true
    const unit       = config.unit       != null ? config.unit : '';
    const decimals   = config.decimals   != null ? config.decimals : 0;
    const fileName   = config.fileName   || 'combo';
    // isPp: п.п. formatting for deltas. Auto-true for wavg (rates), but terms/months
    // use % change — allow explicit override via config.isPp
    const isPp = config.isPp !== undefined ? Boolean(config.isPp) : (aggType === 'wavg');
    const sfx        = unit ? ' ' + unit : '';

    return {
      keys, labels: config.labels, colors,
      valueCode, weightCode,
      aggType, chartType, stackBars, unit, decimals, fileName,
      isPp, sfx,
      onData:        typeof config.onData        === 'function' ? config.onData        : null,
      onTableHeader: typeof config.onTableHeader === 'function' ? config.onTableHeader : null,
    };
  }

  // ── 2. _extractCodes ──────────────────────────────────────────────────
  // Includes ALL codes from valueCode (not just chart keys) so extra KPI-only
  // codes also get fetched and appear in allData.
  function _extractCodes(cfg) {
    const all = [];
    Object.keys(cfg.valueCode).forEach(k => {
      all.push(cfg.valueCode[k]);
      if (cfg.weightCode[k]) all.push(cfg.weightCode[k]);
    });
    return [...new Set(all)];
  }

  // ── 3. _fetch ─────────────────────────────────────────────────────────
  async function _fetch(cfg, state) {
    const codes = _extractCodes(cfg);
    const data  = await api.multiIndicatorData(codes.join(','));
    // Assign to BOTH state and window — period-toggle.js shim mutates window.allData in-place
    state.allData = window.allData = data;

    const dates = Object.values(data).map(d => d.indicator?.last_updated).filter(Boolean);
    if (dates.length) {
      const el = document.getElementById('chart-updated');
      if (el) el.textContent = new Date(dates[0]).toLocaleDateString('ru-RU');
    }
  }

  // ── 4. _getFiltered ───────────────────────────────────────────────────
  function _getFiltered(key, cfg, state) {
    const raw    = state.allData[cfg.valueCode[key]]?.series || [];
    const wCode  = cfg.weightCode[key];
    const weight = wCode ? (state.allData[wCode]?.series || []) : [];

    if (state.isAnnual) {
      let agg;
      if (cfg.aggType === 'wavg') {
        agg = AnnualToggle.aggregateWavgSeries(raw, weight);
      } else if (cfg.aggType === 'avg') {
        agg = AnnualToggle.aggregateAnnualSeries(raw, 'avg');
      } else {
        agg = AnnualToggle.aggregateAnnualSeries(raw, 'sum');
      }
      if (!state.currentRange) return agg;
      const cutYear = new Date().getFullYear() - state.currentRange;
      return agg.filter(p => parseInt(p.label || p.date) >= cutYear);
    }

    if (!state.currentRange) return raw;
    const pts = raw.filter(p => p.value != null);
    if (!pts.length) return raw;
    const lastDate = new Date(pts[pts.length - 1].date);
    const cutoff   = new Date(lastDate);
    cutoff.setFullYear(cutoff.getFullYear() - state.currentRange);
    cutoff.setDate(1);
    return raw.filter(p => new Date(p.date) >= cutoff);
  }

  // ── 5. _buildDropdown ─────────────────────────────────────────────────
  // Called ONCE from init(). Never re-called (avoids double-listener accumulation).
  function _buildDropdown(cfg, state, onChartRebuild) {
    const dropdown = document.getElementById('series-dropdown');
    if (!dropdown) return;

    dropdown.innerHTML = '';
    cfg.keys.forEach(key => {
      const item = document.createElement('div');
      item.className = 'filter-dropdown-item';
      item.dataset.key = key;

      const cb  = document.createElement('input');
      cb.type   = 'checkbox';
      cb.id     = `cb-${key}`;
      cb.checked = state.activeSeries.has(key);

      const dot = document.createElement('span');
      dot.className  = 'kpi-dot';
      dot.style.background = cfg.colors[key];

      const lbl = document.createElement('span');
      lbl.textContent = cfg.labels[key];

      item.appendChild(cb);
      item.appendChild(dot);
      item.appendChild(lbl);
      dropdown.appendChild(item);
    });

    // One delegated listener — no per-item listeners
    dropdown.addEventListener('click', e => {
      e.stopPropagation();
      const item = e.target.closest('.filter-dropdown-item');
      if (!item) return;
      const key = item.dataset.key;
      const cb  = item.querySelector('input');
      if (e.target !== cb) cb.checked = !cb.checked;

      if (cb.checked) {
        state.activeSeries.add(key);
      } else {
        if (state.activeSeries.size <= 1) { cb.checked = true; return; }
        state.activeSeries.delete(key);
      }
      _updateFilterBtnState(cfg, state);
      _buildChart(cfg, state);
    });
  }

  // ── 6. _syncDropdown ──────────────────────────────────────────────────
  function _syncDropdown(cfg, state) {
    cfg.keys.forEach(k => {
      const cb = document.getElementById(`cb-${k}`);
      if (cb) cb.checked = state.activeSeries.has(k);
    });
  }

  // ── 7. _updateFilterBtnState ──────────────────────────────────────────
  function _updateFilterBtnState(cfg, state) {
    const btn = document.getElementById('btn-filter-series');
    if (!btn) return;
    const allActive = cfg.keys.every(k => state.activeSeries.has(k));
    btn.classList.toggle('has-active', !allActive);
  }

  // ── 8. _buildChart ────────────────────────────────────────────────────
  function _buildChart(cfg, state) {
    const container = document.getElementById('main-chart');
    if (!container) return;

    if (!state.chartInstance) {
      state.chartInstance = echarts.init(container, null, { renderer: 'canvas' });
      window.addEventListener('resize', () => state.chartInstance.resize());
    }

    const allDates = [...new Set(
      [...state.activeSeries].flatMap(k => _getFiltered(k, cfg, state).map(p => p.date || p.label))
    )].sort();

    const isDelta = state.currentMode !== 'absolute';
    const field   = state.currentMode === 'yoy' ? 'yoy_change_pct' : 'mom_change_pct';

    // Build per-key maps for fast lookup
    const maps = {};
    cfg.keys.forEach(k => {
      const m = {};
      _getFiltered(k, cfg, state).forEach(p => { m[p.date || p.label] = p; });
      maps[k] = m;
    });

    // x-axis labels (use first available label for each date)
    const xData = allDates.map(d => {
      for (const k of state.activeSeries) {
        const p = maps[k][d];
        if (p?.label) return p.label;
      }
      return d;
    });

    // x interval so labels don't overlap
    const total = xData.length;
    let xInterval = 'auto';
    if (total > 120)     xInterval = 11;
    else if (total > 60) xInterval = 5;
    else if (total > 24) xInterval = 2;

    // Series
    const seriesArr = [...state.activeSeries].map(key => {
      const data = allDates.map(d => {
        const p = maps[key][d];
        if (!p || p.value == null) return null;
        return isDelta ? (p[field] != null ? Number(p[field]) : null) : Number(p.value);
      });

      if (cfg.chartType === 'bar' && !isDelta) {
        return {
          name: cfg.labels[key], type: 'bar',
          ...(cfg.stackBars ? { stack: 'total' } : {}),
          data,
          itemStyle: { color: cfg.colors[key] },
          emphasis: { focus: 'series' },
          barMaxWidth: state.isAnnual ? 40 : 24,
        };
      }
      return {
        name: cfg.labels[key], type: 'line', data,
        lineStyle: { color: cfg.colors[key], width: 2.5 },
        itemStyle: { color: cfg.colors[key] },
        symbol: allDates.length < 60 ? 'circle' : 'none',
        symbolSize: 4, connectNulls: false,
      };
    });

    // Tooltip formatter
    const fmtDelta = (v) => {
      if (v == null) return '—';
      if (cfg.isPp) return (v > 0 ? '+' : '') + fmtNum(v, 2) + ' п.п.';
      return (v > 0 ? '+' : '') + fmtNum(v, 2) + '%';
    };

    state.chartInstance.setOption({
      animation: true, animationDuration: 200,
      legend: {
        data: [...state.activeSeries].map(k => cfg.labels[k]),
        top: 0, left: 0,
        textStyle: { fontFamily: 'IBM Plex Sans', fontSize: 12, color: '#3D4F60' },
        icon: 'circle', itemWidth: 10, itemHeight: 10,
      },
      grid: { left: 70, right: 20, top: 40, bottom: 80 },
      dataZoom: [
        {
          type: 'slider', bottom: 8, height: 24,
          borderColor: '#DDE2E8', backgroundColor: '#F2F4F7',
          fillerColor: 'rgba(26,43,74,0.10)',
          handleStyle: { color: '#1A2B4A', borderColor: '#1A2B4A', borderWidth: 2 },
          textStyle: { fontFamily: 'IBM Plex Sans', fontSize: 10, color: '#7A8B9A' },
          brushSelect: false, throttle: 16,
        },
        { type: 'inside', throttle: 16 },
      ],
      tooltip: {
        trigger: 'axis',
        axisPointer: { type: cfg.chartType === 'bar' && !isDelta ? 'shadow' : 'line' },
        backgroundColor: '#0D1B2A', borderColor: '#0D1B2A',
        textStyle: { color: '#fff', fontFamily: 'IBM Plex Sans', fontSize: 13 },
        formatter: params => {
          let html  = `<b>${params[0]?.axisValue}</b><br/>`;
          let stack = 0;
          params.forEach(p => {
            if (p.value == null) return;
            const val = isDelta
              ? fmtDelta(p.value)
              : fmtNum(p.value, cfg.decimals) + cfg.sfx;
            html += `<span style="color:${p.color}">●</span> ${p.seriesName}: <b>${val}</b><br/>`;
            if (!isDelta) stack += p.value;
          });
          if (!isDelta && cfg.stackBars && seriesArr.length > 1)
            html += `<span style="color:#aaa">Итого: <b>${fmtNum(stack, cfg.decimals)}${cfg.sfx}</b></span>`;
          return html;
        },
      },
      xAxis: {
        type: 'category', data: xData,
        axisLabel: { fontFamily: 'IBM Plex Sans', fontSize: 11, color: '#7A8B9A', interval: xInterval },
        axisLine: { lineStyle: { color: '#DDE2E8' } }, axisTick: { show: false },
      },
      yAxis: {
        type: 'value',
        axisLabel: {
          fontFamily: 'IBM Plex Mono', fontSize: 11, color: '#7A8B9A',
          formatter: v => isDelta ? fmtDelta(v) : fmtNum(v, cfg.decimals),
        },
        splitLine: { lineStyle: { color: '#DDE2E8', type: 'dashed' } },
        axisLine: { show: false }, axisTick: { show: false },
      },
      series: seriesArr,
    }, true);
  }

  // ── 9. _renderTable ───────────────────────────────────────────────────
  function _renderTable(cfg, state) {
    const body = document.getElementById('data-table-body');
    if (!body) return;

    const series = _getFiltered(state.currentTable, cfg, state).slice().reverse();

    // Optional table header override
    const valHeader = cfg.onTableHeader
      ? cfg.onTableHeader(state.currentMode)
      : `Значение${cfg.unit ? ', ' + cfg.unit : ''}`;

    // Update header cells if the table has them
    const thCells = document.querySelectorAll('.data-table thead th');
    if (thCells.length >= 2) thCells[1].textContent = valHeader;

    body.innerHTML = series.map(p => {
      const valStr = p.value != null
        ? fmtNum(Number(p.value), cfg.decimals) + cfg.sfx
        : '—';
      const yoyStr = deltaHtml(p.yoy_change_pct, cfg.isPp);
      const momStr = state.isAnnual ? '—' : deltaHtml(p.mom_change_pct, cfg.isPp);
      const label  = p.label || (p.date ? fmtDate(p.date, 'monthly') : '—');
      return `<tr>
        <td>${label}</td>
        <td class="num">${valStr}</td>
        <td class="num">${yoyStr}</td>
        <td class="num">${momStr}</td>
      </tr>`;
    }).join('') ||
      '<tr><td colspan="4" style="text-align:center;color:var(--color-muted);padding:24px">Нет данных</td></tr>';
  }

  // ── 10. _bindEvents ───────────────────────────────────────────────────
  function _bindEvents(cfg, state, rebuild) {
    // Range buttons
    document.addEventListener('click', e => {
      const btn = e.target.closest('[data-range]');
      if (!btn) return;
      document.querySelectorAll('[data-range]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.currentRange = btn.dataset.range === 'all' ? null : Number(btn.dataset.range);
      rebuild();
    });

    // Mode buttons — chart only, no table rebuild
    document.addEventListener('click', e => {
      const btn = e.target.closest('[data-mode]');
      if (!btn) return;
      document.querySelectorAll('[data-mode]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.currentMode = btn.dataset.mode;
      _buildChart(cfg, state);
    });

    // Table tab buttons — table only
    document.addEventListener('click', e => {
      const btn = e.target.closest('[data-table]');
      if (!btn) return;
      document.querySelectorAll('[data-table]').forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      state.currentTable = btn.dataset.table;
      _renderTable(cfg, state);
    });

    // Dropdown open / close
    const filterBtn = document.getElementById('btn-filter-series');
    if (filterBtn) {
      filterBtn.addEventListener('click', e => {
        e.stopPropagation();
        const dd = document.getElementById('series-dropdown');
        if (dd) dd.style.display = dd.style.display === 'none' ? 'block' : 'none';
      });
    }
    document.addEventListener('click', () => {
      const dd = document.getElementById('series-dropdown');
      if (dd) dd.style.display = 'none';
    });
    const dd = document.getElementById('series-dropdown');
    if (dd) dd.addEventListener('click', e => e.stopPropagation());

    // Reset button
    const resetBtn = document.getElementById('btn-reset-filters');
    if (resetBtn) {
      resetBtn.addEventListener('click', () => {
        state.activeSeries = new Set(cfg.keys);
        _syncDropdown(cfg, state);
        _updateFilterBtnState(cfg, state);
        _buildChart(cfg, state);
      });
    }

    // PNG download
    const pngBtn = document.getElementById('btn-download-png');
    if (pngBtn) {
      pngBtn.addEventListener('click', () => {
        if (!state.chartInstance) return;
        const a = document.createElement('a');
        a.href     = state.chartInstance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: '#fff' });
        a.download = cfg.fileName + '.png';
        a.click();
      });
    }

    // XLSX download — value codes only (no weight codes)
    const xlsxBtn = document.getElementById('btn-download-xlsx');
    if (xlsxBtn) {
      xlsxBtn.addEventListener('click', () => {
        const codes  = cfg.keys.map(k => cfg.valueCode[k]).join(',');
        const labels = encodeURIComponent(cfg.keys.map(k => cfg.labels[k]).join(','));
        window.open(`${window.API_BASE}/multi/data.xlsx?codes=${codes}&labels=${labels}&filename=${cfg.fileName}`);
      });
    }
  }

  // ── 11. _injectAnnualToggle ───────────────────────────────────────────
  function _injectAnnualToggle(cfg, state, rebuild) {
    const toolbar = document.querySelector('.chart-toolbar');
    if (!toolbar) return;

    AnnualToggle.injectAnnualBtn(toolbar, annual => {
      state.isAnnual = annual;
      const momBtn = document.querySelector('[data-mode="mom"]');
      if (momBtn) momBtn.style.display = annual ? 'none' : '';
      if (annual && state.currentMode === 'mom') {
        document.querySelectorAll('[data-mode]').forEach(b => b.classList.remove('active'));
        const ab = document.querySelector('[data-mode="absolute"]');
        if (ab) { ab.classList.add('active'); state.currentMode = 'absolute'; }
      }
      rebuild();
    });
  }

  // ── 12. init (public entry point) ────────────────────────────────────
  async function init(config) {
    const cfg = _normalizeConfig(config);

    const state = {
      allData:       {},
      chartInstance: null,
      activeSeries:  new Set(cfg.keys),
      currentRange:  null,
      currentMode:   'absolute',
      currentTable:  cfg.keys[0],
      isAnnual:      false,
    };

    // Rebuild: called on range change + annual toggle
    function rebuild() {
      _buildChart(cfg, state);
      _renderTable(cfg, state);
      if (cfg.onData) cfg.onData(state.allData);
    }

    try {
      await _fetch(cfg, state);
      _buildDropdown(cfg, state, rebuild);
      if (cfg.onData) cfg.onData(state.allData);
      _buildChart(cfg, state);
      _renderTable(cfg, state);
      _bindEvents(cfg, state, rebuild);
      _injectAnnualToggle(cfg, state, rebuild);
    } catch (err) {
      console.error('ComboPage init error:', err);
      const container = document.getElementById('main-chart');
      if (container) container.innerHTML = `<div style="padding:24px;color:#dc2626">Ошибка загрузки данных: ${err.message}</div>`;
      throw err;
    }
  }

  return { init };
})();
