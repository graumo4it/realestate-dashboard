/**
 * Утилиты форматирования чисел, дат, динамики
 */

const MONTHS_RU = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
const MONTHS_RU_CAP = ['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];
const MONTHS_FULL = ['Январь','Февраль','Март','Апрель','Май','Июнь',
                     'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];
const MONTH_ABBR_DOT_RE = /(^|[\s\n])(янв|фев|мар|апр|май|июн|июл|авг|сен|окт|ноя|дек)\.(?=\s|\n|$)/gi;

function fmtNum(v, decimals = 0) {
  if (v == null || isNaN(v)) return '—';
  return Number(v).toLocaleString('ru-RU', {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
}

function fmtValue(v, unit = '') {
  if (v == null) return '—';
  const n = Number(v);
  let s;
  if (Math.abs(n) >= 1e9)       s = fmtNum(n / 1e9, 2) + ' млрд';
  else if (Math.abs(n) >= 1e6)  s = fmtNum(n / 1e6, 2) + ' млн';
  else if (Math.abs(n) >= 1e3)  s = fmtNum(n, 0);
  else                           s = fmtNum(n, 2);
  return unit ? `${s} ${unit}` : s;
}

function fmtPct(v, sign = true) {
  if (v == null || isNaN(v)) return '—';
  const n = Number(v);
  const prefix = sign && n > 0 ? '+' : '';
  return `${prefix}${fmtNum(n, 1)}%`;
}

function fmtDate(dateStr, periodicity = 'monthly') {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (periodicity === 'annual') return d.getFullYear().toString();
  if (periodicity === 'quarterly') {
    const q = Math.floor(d.getMonth() / 3) + 1;
    return `Q${q} ${d.getFullYear()}`;
  }
  // monthly — двухстрочная метка: «янв\n2024»
  return `${MONTHS_RU[d.getMonth()]}\n${d.getFullYear()}`;
}

// Однострочный вариант для мест где перенос не нужен (KPI, таблица)
function fmtDateInline(dateStr, periodicity = 'monthly') {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  if (periodicity === 'annual') return d.getFullYear().toString();
  if (periodicity === 'quarterly') {
    const q = Math.floor(d.getMonth() / 3) + 1;
    return `Q${q} ${d.getFullYear()}`;
  }
  return `${MONTHS_RU_CAP[d.getMonth()]} ${d.getFullYear()}`;
}

function fmtDateFull(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return `${MONTHS_FULL[d.getMonth()]} ${d.getFullYear()}`;
}

function stripMonthAbbrDots(label) {
  return String(label ?? '').replace(MONTH_ABBR_DOT_RE, (_, prefix, month) => `${prefix}${month}`);
}

function formatXAxisLabel(label, dateStr, periodicity = 'monthly') {
  const rawLabel = label != null ? String(label).trim() : '';
  const rawDate = dateStr != null ? String(dateStr) : '';

  if (periodicity === 'monthly') {
    if (rawLabel.includes('\n')) return stripMonthAbbrDots(rawLabel);
    if (/^\d{4}-\d{2}-\d{2}/.test(rawDate)) return fmtDate(rawDate, 'monthly');

    const parts = rawLabel.split(/\s+/);
    const year = parts.find(part => /^\d{4}$/.test(part));
    const mon = parts[0]?.replace('.', '').slice(0, 3).toLowerCase();
    if (year && mon && !rawLabel.startsWith('Q')) return `${mon}\n${year}`;
  }

  if (rawLabel) return rawLabel;
  if (/^\d{4}-\d{2}-\d{2}/.test(rawDate)) return fmtDate(rawDate, periodicity);
  return rawDate;
}

// Возвращает { interval, showMinLabel, showMaxLabel } для axisLabel ECharts.
// Главный принцип: между ВСЕМИ подписями — строго одинаковое расстояние (= шаг),
// последний период всегда подписан. Слева допустим небольшой отступ (первая
// подпись может оказаться на 1–N-м периоде) — это плата за идеально равные
// промежутки. showMinLabel/showMaxLabel вычисляются детерминированно, чтобы
// ECharts не форсировал «лишнюю» подпись на индексе 0 вне равномерной сетки.
function xAxisLabelInterval(total, periodicity = 'monthly') {
  if (total <= 1) return { interval: 0, showMinLabel: true, showMaxLabel: true };

  // Круглые шаги-кандидаты (от плотного к редкому) и комфортный максимум
  // числа подписей. Шаг выбираем как наименьший круглый, при котором подписей
  // не больше максимума — так они не слипаются, но и не разрежены сверх меры.
  let candidates, maxLabels;
  if (periodicity === 'quarterly') {
    candidates = [1, 2, 4, 8];
    maxLabels = 16;
  } else if (periodicity === 'annual') {
    candidates = [1, 2, 5, 10];
    maxLabels = 12;
  } else { // monthly
    candidates = [1, 2, 3, 6, 12];
    maxLabels = 20;
  }

  const lastIndex = total - 1;
  let step = candidates[candidates.length - 1];
  for (const s of candidates) {
    if (Math.floor(lastIndex / s) + 1 <= maxLabels) { step = s; break; }
  }

  if (step <= 1) {
    return { interval: 0, showMinLabel: true, showMaxLabel: true };
  }

  // Равномерная сетка с привязкой к правому краю: offset = lastIndex % step.
  // Метки на offset, offset+step, …, lastIndex — все промежутки равны step,
  // последняя точка подписана. offset (0..step-1) — отступ слева.
  const offset = lastIndex % step;
  const labels = new Set();
  for (let i = offset; i <= lastIndex; i += step) labels.add(i);

  // showMinLabel/showMaxLabel = true: иначе ECharts гасит первую/последнюю
  // ВЫБРАННУЮ interval-ом метку у края (даже если это не индекс 0/последний),
  // из-за чего слева образуется большая пустота. interval сам решает состав
  // меток — индекс 0 при offset>0 не форсируется.
  return {
    interval: index => labels.has(index),
    showMinLabel: true,
    showMaxLabel: true,
  };
}

function cleanAxisLabel(label) {
  return String(label ?? '').replace(/\n/g, ' ');
}

/**
 * Форматирует динамику показателя.
 * @param {number} val - значение динамики
 * @param {boolean} isPp - если true, показывает п.п. вместо %
 */
function deltaHtml(val, isPp = false) {
  if (val == null) return '';
  const n = Number(val);
  const threshold = isPp ? 0.001 : 0.05;
  if (Math.abs(n) < threshold) {
    return `<span class="delta flat">${isPp ? '0 п.п.' : '0%'}</span>`;
  }
  const cls = n > 0 ? 'up' : 'down';
  const arrow = n > 0 ? '↑' : '↓';
  const label = isPp
    ? `${fmtNum(Math.abs(n), 2)} п.п.`
    : fmtPct(Math.abs(n), false);
  return `<span class="delta ${cls}">${arrow} ${label}</span>`;
}

function dateFromStr(s) {
  return s ? new Date(s) : null;
}

// Возвращает ISO-дату (YYYY-MM-DD) для фильтра диапазона
function rangeStart(years) {
  if (!years) return null;
  const d = new Date();
  d.setFullYear(d.getFullYear() - years);
  return d.toISOString().slice(0, 10);
}

function periodTypeLabel(periodType) {
  switch (periodType) {
    case 'period_start': return 'на начало отчётного периода';
    case 'period_end':   return 'на конец отчётного периода';
    case 'on_date':      return 'на дату';
    case 'period':       return 'за период';
    default:             return '';
  }
}

// Убирает порядковый код и единицы из названия индикатора
function cleanName(name) {
  if (!name) return name;
  let s = name.replace(/^\d+\.\d+\s+/, '');
  s = s.replace(/,\s*[^,]+$/, v => {
    const unit = v.replace(/^,\s*/, '').trim();
    if (unit.length <= 20 && /^[\w\s\.\/]+$/.test(unit.replace(/[а-яеА-ЯЕ]/g, 'x'))) {
      return '';
    }
    return v;
  });
  return s.trim();
}
