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

function xAxisLabelInterval(total, periodicity = 'monthly') {
  let targetStep = 1;
  if (periodicity === 'monthly') {
    if (total >= 84) targetStep = 12;
    else if (total >= 60) targetStep = 6;
    else if (total > 24) targetStep = 3;
  } else if (periodicity === 'quarterly') {
    if (total > 20) targetStep = 4;
    else if (total > 8) targetStep = 2;
  } else if (periodicity === 'annual') {
    if (total > 40) targetStep = 5;
    else if (total > 24) targetStep = 3;
    else if (total > 12) targetStep = 2;
  }

  if (targetStep <= 1) return 0;

  const lastIndex = Math.max(0, total - 1);
  if (!lastIndex) return 0;

  const divisors = [];
  for (let step = 1; step <= lastIndex; step += 1) {
    if (lastIndex % step === 0) divisors.push(step);
  }

  const labels = new Set();
  const minStep = targetStep * 0.75;
  const maxStep = targetStep * 1.5;
  const candidates = divisors.filter(step => step >= minStep && step <= maxStep);

  if (candidates.length) {
    const step = candidates.reduce((best, candidate) => {
      const bestScore = Math.abs(best - targetStep);
      const candidateScore = Math.abs(candidate - targetStep);
      if (candidateScore === bestScore) return candidate > best ? candidate : best;
      return candidateScore < bestScore ? candidate : best;
    }, candidates[0]);

    for (let index = 0; index <= lastIndex; index += step) {
      labels.add(index);
    }
  } else {
    const labelCount = Math.max(2, Math.round(lastIndex / targetStep) + 1);
    for (let i = 0; i < labelCount; i += 1) {
      labels.add(Math.round((lastIndex * i) / (labelCount - 1)));
    }
  }
  labels.add(0);
  labels.add(lastIndex);

  return index => {
    return labels.has(index);
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
