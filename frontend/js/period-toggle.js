/* period-toggle.js · v=4.0 */
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

// Маркер версии — позволяет проверить из консоли, какая версия загружена.
window.PeriodToggle.VERSION = '4.0';
// Если в консоли увидите этот лог — модуль точно свежий.
try { console.log('[PeriodToggle v4.0] loaded · methods:',
  Object.keys(window.PeriodToggle).filter(k => !k.startsWith('_')).join(', ')); } catch (_) {}
