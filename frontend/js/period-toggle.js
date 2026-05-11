/* period-toggle.js · v=3.1 · перехват AnnualToggle.injectAnnualBtn → btn-group */
/**
 * period-toggle.js — модуль селектора периодичности для комбо-страниц.
 *
 * Поддерживает три уровня периодичности:
 *   'monthly'    — сырой месячный ряд (как пришёл из API)
 *   'quarterly'  — агрегация месячных в кварталы
 *   'annual'     — агрегация месячных в годы
 *
 * Три типа агрегации (соответствуют логике годового расчёта):
 *   'sum'  — сумма значений за период (ввод жилья, выдачи ипотек)
 *   'avg'  — простое среднее за период (размер кредита, платёж)
 *   'wavg' — средневзвешенная по объёму (ставки, сроки)
 *
 * Неполные кварталы/годы исключаются: квартал считается полным, если в нём
 * 3 месяца с непустыми значениями; год — если 12 месяцев. Это поведение
 * аналогично существующей логике «Данные за год».
 *
 * Использование на странице:
 *   <script src="js/period-toggle.js"></script>
 *   PeriodToggle.injectSelector(toolbar, {
 *     options: ['monthly', 'quarterly', 'annual'],
 *     defaultValue: 'monthly',
 *     labels: { monthly: 'Месяц', quarterly: 'Квартал', annual: 'Год' }
 *   }, onChange);
 *
 *   const agg = PeriodToggle.aggregate(series, 'quarterly', 'sum');
 *   const wagg = PeriodToggle.aggregateWavg(valueSeries, weightSeries, 'quarterly');
 *
 * Обратная совместимость с annual-toggle.js:
 *   window.AnnualToggle.aggregateAnnualSeries(series, 'sum'|'avg')   — работает как раньше
 *   window.AnnualToggle.aggregateWavgSeries(valueSeries, weightSeries) — работает как раньше
 *   window.AnnualToggle.injectAnnualBtn(toolbar, onToggle)            — НЕ инжектит, но не падает
 */

window.PeriodToggle = (function () {

  // ─────────────────────────────────────────────────────────────────────
  // Утилиты для ключа группы
  // ─────────────────────────────────────────────────────────────────────

  /** Возвращает ключ группы для даты в формате YYYY-MM-DD. */
  function groupKey(dateStr, periodicity) {
    if (periodicity === 'annual') {
      return dateStr.slice(0, 4);
    }
    // quarterly
    const year = parseInt(dateStr.slice(0, 4), 10);
    const month = parseInt(dateStr.slice(5, 7), 10);
    const q = Math.floor((month - 1) / 3) + 1;
    return `${year}-Q${q}`;
  }

  /** Сколько месяцев должно быть в полном периоде. */
  function expectedMonths(periodicity) {
    return periodicity === 'annual' ? 12 : 3;
  }

  /** Дата начала периода (для оси X и сортировки). */
  function periodStartDate(groupKeyStr, periodicity) {
    if (periodicity === 'annual') {
      return `${groupKeyStr}-01-01`;
    }
    // YYYY-Qn
    const [year, qPart] = groupKeyStr.split('-Q');
    const q = parseInt(qPart, 10);
    const startMonth = (q - 1) * 3 + 1;
    return `${year}-${String(startMonth).padStart(2, '0')}-01`;
  }

  /** Подпись периода: 'Q1 2024' / '2024'. */
  function periodLabel(groupKeyStr, periodicity) {
    if (periodicity === 'annual') return groupKeyStr;
    const [year, qPart] = groupKeyStr.split('-Q');
    return `Q${qPart} ${year}`;
  }

  // ─────────────────────────────────────────────────────────────────────
  // Агрегация sum / avg
  // ─────────────────────────────────────────────────────────────────────

  /**
   * Агрегирует месячный ряд в квартальный или годовой.
   *
   * @param {Array}  series       — массив точек {date, value, label, ...}
   * @param {string} periodicity  — 'quarterly' | 'annual'
   * @param {string} aggType      — 'sum' | 'avg'
   * @returns {Array} агрегированный ряд {date, label, value, yoy_change_pct, mom_change_pct:null}
   *                 неполные периоды исключаются
   */
  function aggregate(series, periodicity, aggType) {
    if (!series || !series.length) return [];
    if (periodicity === 'monthly') return series.slice();

    // Группируем
    const groups = {}; // key -> [values]
    for (const p of series) {
      if (p.value == null || !p.date) continue;
      const k = groupKey(p.date, periodicity);
      if (!groups[k]) groups[k] = [];
      groups[k].push(Number(p.value));
    }

    const need = expectedMonths(periodicity);
    const keys = Object.keys(groups).sort();
    const result = [];

    for (const k of keys) {
      const vals = groups[k];
      // Скрываем неполные периоды
      if (vals.length < need) continue;

      let val;
      if (aggType === 'sum') {
        val = vals.reduce((a, b) => a + b, 0);
      } else {
        // avg
        val = vals.reduce((a, b) => a + b, 0) / vals.length;
      }
      result.push({
        date: periodStartDate(k, periodicity),
        label: periodLabel(k, periodicity),
        value: val,
        yoy_change_pct: null,
        mom_change_pct: null,
      });
    }

    // Считаем YoY: для года — предыдущий год; для квартала — тот же квартал год назад
    _computeYoy(result, periodicity);
    return result;
  }

  // ─────────────────────────────────────────────────────────────────────
  // Агрегация wavg (средневзвешенная по объёму)
  // ─────────────────────────────────────────────────────────────────────

  /**
   * Средневзвешенная агрегация месячного ряда.
   *
   * @param {Array}  valueSeries   — ряд значений (ставка/срок)
   * @param {Array}  weightSeries  — ряд весов (объём выдач)
   * @param {string} periodicity   — 'quarterly' | 'annual'
   * @returns {Array} агрегированный ряд
   */
  function aggregateWavg(valueSeries, weightSeries, periodicity) {
    if (!valueSeries || !valueSeries.length) return [];
    if (periodicity === 'monthly') return valueSeries.slice();

    // Карта весов по дате
    const weightMap = {};
    for (const p of (weightSeries || [])) {
      if (p.value != null && p.date) weightMap[p.date] = Number(p.value);
    }

    // Группируем: для каждой группы храним {wsum, wval, count}
    const groups = {};
    for (const p of valueSeries) {
      if (p.value == null || !p.date) continue;
      const k = groupKey(p.date, periodicity);
      const w = weightMap[p.date] ?? 1; // fallback — равный вес
      if (!groups[k]) groups[k] = { wsum: 0, wval: 0, count: 0 };
      groups[k].wsum += w;
      groups[k].wval += Number(p.value) * w;
      groups[k].count += 1;
    }

    const need = expectedMonths(periodicity);
    const keys = Object.keys(groups).sort();
    const result = [];

    for (const k of keys) {
      const g = groups[k];
      if (g.count < need) continue; // неполный период
      const val = g.wsum > 0 ? g.wval / g.wsum : null;
      result.push({
        date: periodStartDate(k, periodicity),
        label: periodLabel(k, periodicity),
        value: val,
        yoy_change_pct: null,
        mom_change_pct: null,
      });
    }

    _computeYoy(result, periodicity);
    return result;
  }

  // ─────────────────────────────────────────────────────────────────────
  // Расчёт YoY (год к году) и QoQ / MoM (к предыдущему периоду).
  //   Для годового ряда:    YoY = к предыдущей точке (она же предыдущий год);
  //                         «период к периоду» не считаем (бессмысленно).
  //   Для квартального ряда: YoY = к точке за 4 квартала назад;
  //                          QoQ = к предыдущей точке.
  // ─────────────────────────────────────────────────────────────────────

  function _computeYoy(result, periodicity) {
    const lag = periodicity === 'annual' ? 1 : 4;
    for (let i = lag; i < result.length; i++) {
      const cur = result[i].value;
      const prev = result[i - lag].value;
      if (prev != null && prev !== 0 && cur != null) {
        result[i].yoy_change_pct = (cur - prev) / Math.abs(prev) * 100;
      }
    }
    // Для квартального — считаем QoQ (как mom_change_pct для совместимости + qoq_change_pct)
    if (periodicity === 'quarterly') {
      for (let i = 1; i < result.length; i++) {
        const cur = result[i].value;
        const prev = result[i - 1].value;
        if (prev != null && prev !== 0 && cur != null) {
          const pct = (cur - prev) / Math.abs(prev) * 100;
          result[i].qoq_change_pct = pct;
          result[i].mom_change_pct = pct; // fallback для страниц, читающих только mom_change_pct
        } else {
          result[i].qoq_change_pct = null;
        }
      }
      if (result.length) {
        result[0].qoq_change_pct = null;
        result[0].mom_change_pct = null;
      }
    }
  }

  // ─────────────────────────────────────────────────────────────────────
  // UI: btn-group из трёх кнопок (Месяц / Квартал / Год)
  // ─────────────────────────────────────────────────────────────────────

  /**
   * Инжектирует btn-group переключателя периодичности в тулбар.
   * Кнопки рендерятся в едином стиле с уже существующими группами
   * `.btn-group` (1г/3г/5л/Всё, Значения/г-г/м-м).
   *
   * @param {HTMLElement} toolbar     — элемент .chart-toolbar
   * @param {Object}      opts
   *   - options:      Array<'monthly'|'quarterly'|'annual'> (порядок и состав)
   *   - defaultValue: string  ('monthly' | 'quarterly' | 'annual')
   *   - disabled:     Array<string> — кнопки, помеченные как недоступные
   *                                   (отрисуются с opacity и без cursor)
   *   - labels:       {monthly,quarterly,annual: string}
   * @param {Function}    onChange    — callback(periodicity: string)
   * @returns {HTMLDivElement} btn-group
   */
  function injectButtons(toolbar, opts, onChange) {
    if (!toolbar) return null;

    const options      = opts.options      || ['monthly', 'quarterly', 'annual'];
    const defaultValue = opts.defaultValue || options[0];
    const disabledSet  = new Set(opts.disabled || []);
    const labels = Object.assign({
      monthly:   'Месяц',
      quarterly: 'Квартал',
      annual:    'Год',
    }, opts.labels || {});

    // btn-group — тот же класс, что у соседних групп; не задаём inline-стили,
    // чтобы кнопки наследовали стили проекта.
    const group = document.createElement('div');
    group.className = 'btn-group';
    group.setAttribute('data-period-toggle', 'true');

    options.forEach(opt => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.setAttribute('data-period', opt);
      btn.textContent = labels[opt] || opt;

      if (opt === defaultValue) {
        btn.classList.add('active');
      }
      if (disabledSet.has(opt)) {
        btn.disabled = true;
        btn.style.opacity = '0.45';
        btn.style.cursor = 'not-allowed';
        btn.setAttribute(
          'title',
          opt === 'monthly'
            ? 'Доступно только для месячных данных'
            : 'Недоступно для этого показателя'
        );
      }

      btn.addEventListener('click', () => {
        if (btn.disabled) return;
        if (btn.classList.contains('active')) return; // уже активна
        // Перенастраиваем активность внутри своей группы
        group.querySelectorAll('button[data-period]').forEach(b => b.classList.remove('active'));
        btn.classList.add('active');
        if (typeof onChange === 'function') onChange(opt);
      });

      group.appendChild(btn);
    });

    // Вставляем группу в первый flex-ряд тулбара,
    // в конец — то есть «правее режимов Изм. г/г», как существующая кнопка.
    const firstRow = toolbar.querySelector('div[style]');
    if (firstRow) {
      firstRow.appendChild(group);
    } else {
      const actions = toolbar.querySelector('.toolbar-actions');
      if (actions) toolbar.insertBefore(group, actions);
      else toolbar.appendChild(group);
    }

    return group;
  }

  // Алиас сохраняем для обратной совместимости с уже мигрированными страницами,
  // если они вдруг успели уйти в репозиторий с PeriodToggle.injectSelector(...).
  const injectSelector = injectButtons;

  // ─────────────────────────────────────────────────────────────────────
  // Утилита: определить периодичность сырого ряда
  // ─────────────────────────────────────────────────────────────────────

  /**
   * Возвращает 'monthly' | 'quarterly' | 'annual' для уже загруженного ряда.
   * Использует медиану шагов между датами в днях.
   */
  function detectPeriodicity(series) {
    if (!series || series.length < 2) return 'monthly';
    const dates = series
      .filter(p => p.date)
      .map(p => new Date(p.date).getTime())
      .sort((a, b) => a - b);
    if (dates.length < 2) return 'monthly';
    const gaps = [];
    for (let i = 1; i < dates.length; i++) {
      gaps.push((dates[i] - dates[i - 1]) / (1000 * 60 * 60 * 24));
    }
    gaps.sort((a, b) => a - b);
    const median = gaps[Math.floor(gaps.length / 2)];
    if (median > 200) return 'annual';
    if (median > 60) return 'quarterly';
    return 'monthly';
  }

  return {
    aggregate,
    aggregateWavg,
    injectButtons,
    injectSelector,     // алиас injectButtons (обратная совместимость)
    detectPeriodicity,
    // утилиты — на случай если понадобятся
    _groupKey: groupKey,
    _periodLabel: periodLabel,
    _periodStartDate: periodStartDate,
  };
})();

// ─────────────────────────────────────────────────────────────────────
// Обратная совместимость со старым API annual-toggle.js
//
// На «ранних» комбо-страницах (combo-chart, mortgage-count, subsidy-count и т.п.)
// инициализация устроена так:
//
//    AnnualToggle.injectAnnualBtn(toolbar, (annual) => {
//      isAnnual = annual;
//      buildChart();
//    });
//
// Эти страницы НЕ переписываются скриптом миграции. Вместо этого здесь мы
// перехватываем вызов injectAnnualBtn и:
//   1) рисуем не одну кнопку «Год», а три «Месяц | Квартал | Год»;
//   2) при клике на «Год» вызываем original callback(true);
//   3) при клике на «Месяц» вызываем original callback(false);
//   4) при клике на «Квартал» — подменяем allData квартальной агрегацией,
//      вызываем original callback(false), затем восстанавливаем allData.
//
// Так страница продолжает работать со своей старой логикой `isAnnual`,
// и при этом получает переключатель периодичности — без переписывания.
// ─────────────────────────────────────────────────────────────────────

(function () {
  // Сохраняем ссылку на старый шим (no-op), если он уже был задан
  var existing = window.AnnualToggle || {};

  window.AnnualToggle = {
    aggregateAnnualSeries: function (series, aggType) {
      return window.PeriodToggle.aggregate(series, 'annual', aggType);
    },
    aggregateWavgSeries: function (valueSeries, weightSeries) {
      return window.PeriodToggle.aggregateWavg(valueSeries, weightSeries, 'annual');
    },
    isMonthly: function (series) {
      return window.PeriodToggle.detectPeriodicity(series) === 'monthly';
    },

    /**
     * Перехват старого API кнопки «Год».
     *
     * @param {HTMLElement} toolbar     элемент .chart-toolbar
     * @param {Function}    onToggle    callback(isAnnual: boolean)
     */
    injectAnnualBtn: function (toolbar, onToggle, options) {
      if (!toolbar || typeof onToggle !== 'function') return null;

      _injected = true;  // отмечаем, что страница сама вызвала шим

      options = options || {};
      // handleAnnualLocally=true означает, что страница не умеет сама
      // обрабатывать onToggle(true) — она вообще не имеет логики `isAnnual`.
      // Тогда «Год» обрабатываем мутацией allData (так же как «Квартал»),
      // только агрегируя в годовые периоды.
      var handleAnnualLocally = options.handleAnnualLocally === true;

      // ── Определяем AGG_TYPE и веса для квартальной агрегации ──────────
      var aggType = window.AGG_TYPE || _guessAggType();
      var weightMap = window._WEIGHT_CODES || {};

      // ── Рисуем btn-group из трёх кнопок (заменяет одну «Год») ─────────
      var group = window.PeriodToggle.injectButtons(toolbar, {
        options:      ['monthly', 'quarterly', 'annual'],
        defaultValue: 'monthly',
        labels: { monthly: 'Месяц', quarterly: 'Квартал', annual: 'Год' }
      }, function (period) {
        if (period === 'monthly') {
          _restoreAllData();
          onToggle(false);
        } else if (period === 'annual') {
          if (handleAnnualLocally) {
            // Страница не знает про isAnnual — агрегируем сами
            _patchAllDataByPeriod('annual', aggType, weightMap);
            onToggle(false);
          } else {
            // Страница умеет — переключаем её в годовой режим
            _restoreAllData();
            onToggle(true);
          }
        } else if (period === 'quarterly') {
          _patchAllDataByPeriod('quarterly', aggType, weightMap);
          onToggle(false);
        }
      });

      return group;
    },
  };

  // Сохраняем оригинальный allData, чтобы восстанавливать при переключении
  var _origAllData = null;
  // Флаг: страница сама вызвала AnnualToggle.injectAnnualBtn?
  var _injected = false;

  function _patchAllDataByPeriod(period, aggType, weightMap) {
    if (!window.allData) return;
    // period: 'quarterly' | 'annual'

    // Первый раз: сохраняем оригинальные series внутри каждого entry
    if (_origAllData == null) {
      _origAllData = {};
      Object.keys(window.allData).forEach(function (k) {
        var entry = window.allData[k];
        if (entry && entry.series) {
          _origAllData[k] = entry.series; // сохраняем ссылку на оригинальный массив
        }
      });
    }

    // Для каждого кода считаем агрегированный ряд и МУТИРУЕМ entry.series
    // Это ключевой момент: страницы хранят `let allData = window.allData = {}`,
    // обе ссылки указывают на ОДИН объект. Если мы делаем
    // `window.allData = newObject`, локальная `let allData` не обновится.
    // Поэтому меняем внутренности существующего объекта.
    Object.keys(window.allData).forEach(function (code) {
      var entry = window.allData[code];
      if (!entry || !entry.series) return;

      var raw = _origAllData[code] || entry.series;
      var agg;
      if (aggType === 'wavg') {
        var weightSeries = _findWeightSeries(code, weightMap);
        agg = window.PeriodToggle.aggregateWavg(raw, weightSeries, period);
      } else {
        agg = window.PeriodToggle.aggregate(raw, period, aggType || 'sum');
      }

      // Дублируем поля period_date / label, как ожидают страницы
      agg.forEach(function (p) {
        if (!p.period_date) p.period_date = p.date;
      });

      entry.series = agg;  // ← мутируем существующий entry
    });
  }

  function _restoreAllData() {
    if (_origAllData != null && window.allData) {
      // Возвращаем сохранённые оригинальные series обратно в каждый entry
      Object.keys(_origAllData).forEach(function (code) {
        var entry = window.allData[code];
        if (entry) entry.series = _origAllData[code];
      });
      _origAllData = null;
    }
  }

  /**
   * Пытается найти весовой ряд для wavg-агрегации.
   * Использует ОРИГИНАЛЬНЫЕ series из _origAllData (потому что текущие
   * могли быть уже подменены квартальной агрегацией предыдущего вызова).
   */
  function _findWeightSeries(code, weightMap) {
    if (!weightMap) return [];
    var wCode = weightMap[code];
    if (!wCode && window.CODES) {
      Object.keys(window.CODES).forEach(function (key) {
        if (window.CODES[key] === code) wCode = weightMap[key];
      });
    }
    if (!wCode) return [];
    // Если есть сохранённый оригинал — берём оттуда; иначе текущий
    if (_origAllData && _origAllData[wCode]) return _origAllData[wCode];
    return (window.allData[wCode] && window.allData[wCode].series) || [];
  }

  /**
   * Угадывает тип агрегации по URL страницы.
   * Используется только если страница не глобализовала window.AGG_TYPE.
   */
  function _guessAggType() {
    var url = (typeof location !== 'undefined') ? location.pathname : '';
    if (/rate|term/i.test(url))       return 'wavg';
    if (/size|payment|ihh|price/i.test(url)) return 'avg';
    return 'sum';   // count / volume / subsidy / igs-count / ...
  }

  // Подхватываем оставшиеся методы из existing (на всякий случай)
  Object.keys(existing).forEach(function (k) {
    if (!(k in window.AnnualToggle)) window.AnnualToggle[k] = existing[k];
  });

  // ── Авто-инжект для страниц, которые НЕ вызывают AnnualToggle.injectAnnualBtn ──
  //
  // Это страницы вроде share-chart.html, у которых до миграции не было
  // подключения annual-toggle.js. Признак — атрибут data-period-shim="auto"
  // на теге <script src="js/period-toggle.js?v=...">.
  //
  // На страницах с обычным подключением (период-toggle.js без этого атрибута)
  // авто-инжект НЕ срабатывает, чтобы не нарисовать дубликат поверх той
  // группы кнопок, которую страница поставит сама позже из своего init().
  function _autoInject() {
    if (_injected) return true;
    var toolbar = document.querySelector('.chart-toolbar');
    if (!toolbar) return false; // toolbar ещё не готов

    // Защита от двойного инжекта
    if (toolbar.querySelector('.btn-group[data-period-toggle]')) {
      _injected = true;
      return true;
    }

    window.AnnualToggle.injectAnnualBtn(toolbar, function (/* annual */) {
      if (typeof window.buildComputed === 'function' && window.allData) {
        var codes = window.CODES ? Object.values(window.CODES) : Object.keys(window.allData);
        var s1 = window.allData[codes[0]]?.series || [];
        var s2 = window.allData[codes[1]]?.series || [];
        var newComputed = window.buildComputed(s1, s2);

        // КРИТИЧНО: мутируем существующий массив, не подменяем ссылку.
        if (Array.isArray(window.computed)) {
          window.computed.length = 0;
          for (var i = 0; i < newComputed.length; i++) {
            window.computed.push(newComputed[i]);
          }
        } else {
          window.computed = newComputed;
        }
      }
      if (typeof window.buildChart  === 'function') window.buildChart();
      if (typeof window.renderTable === 'function') window.renderTable();
    }, { handleAnnualLocally: true });
    return true;
  }

  /**
   * Проверяет, должен ли модуль работать в авто-режиме.
   * Авто-режим включается, если на странице есть тег
   * <script src="js/period-toggle.js..." data-period-shim="auto">.
   */
  function _isAutoMode() {
    if (typeof document === 'undefined') return false;
    var scripts = document.querySelectorAll('script[data-period-shim="auto"]');
    return scripts.length > 0;
  }

  function _scheduleAutoInject() {
    if (typeof document === 'undefined') return; // Node-тесты
    if (!_isAutoMode()) return;                  // обычная страница — авто-инжект не нужен

    function tryInject() {
      if (_autoInject()) return;
      var attempts = 0;
      var timer = setInterval(function () {
        if (_injected || _autoInject()) { clearInterval(timer); return; }
        if (++attempts >= 20) clearInterval(timer); // 20 × 100ms = 2с максимум
      }, 100);
    }
    if (document.readyState === 'loading') {
      document.addEventListener('DOMContentLoaded', tryInject);
    } else {
      tryInject();
    }
  }
  _scheduleAutoInject();
})();

// Маркер версии — позволяет проверить из консоли, какая версия загружена.
window.PeriodToggle.VERSION = '3.1';
// Если в консоли увидите этот лог — модуль точно свежий.
try { console.log('[PeriodToggle v3.1] loaded · methods:',
  Object.keys(window.PeriodToggle).filter(k => !k.startsWith('_')).join(', ')); } catch (_) {}
