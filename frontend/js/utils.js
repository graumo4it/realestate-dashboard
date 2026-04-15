/**
 * Утилиты форматирования чисел, дат, динамики
 */

const MONTHS_RU = ['Янв','Фев','Мар','Апр','Май','Июн','Июл','Авг','Сен','Окт','Ноя','Дек'];
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
  return `${MONTHS_RU[d.getMonth()]} ${d.getFullYear()}`;
}

function fmtDateFull(dateStr) {
  if (!dateStr) return '';
  const d = new Date(dateStr);
  return `${MONTHS_FULL[d.getMonth()]} ${d.getFullYear()}`;
}

function deltaHtml(pct) {
  if (pct == null) return '';
  const n = Number(pct);
  if (Math.abs(n) < 0.05) {
    return `<span class="delta flat">0%</span>`;
  }
  const cls = n > 0 ? 'up' : 'down';
  const arrow = n > 0 ? '↑' : '↓';
  return `<span class="delta ${cls}">${arrow} ${fmtPct(Math.abs(n), false)}</span>`;
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
