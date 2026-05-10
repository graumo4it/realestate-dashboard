/**
 * Утилиты форматирования чисел, дат, динамики
 */

const MONTHS_RU = ['янв','фев','мар','апр','май','июн','июл','авг','сен','окт','ноя','дек'];
const MONTHS_RU_CAP = ['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];
const MONTHS_FULL = ['Январь','Февраль','Март','Апрель','Май','Июнь',
                     'Июль','Август','Сентябрь','Октябрь','Ноябрь','Декабрь'];

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
  // monthly — двухстрочная метка: «янв.\n2024»
  return `${MONTHS_RU[d.getMonth()]}.\n${d.getFullYear()}`;
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
