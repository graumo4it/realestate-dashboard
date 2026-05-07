/**
 * annual-toggle.js — модуль кнопки «Год» для комбо-страниц
 *
 * Три типа агрегации:
 *   'sum'  — сумма значений за год (ввод жилья, выдачи ипотек)
 *   'avg'  — простое среднее за год (размер кредита, платёж)
 *   'wavg' — средневзвешенная по объёму (ставки, сроки)
 *
 * Использование:
 *   1. Подключить скрипт после api.js и utils.js
 *   2. Вызвать injectAnnualBtn(toolbarEl, onToggle) — вставляет кнопку
 *   3. В обработчике onToggle(isAnnual) перерисовать график/таблицу
 *   4. Использовать aggregateAnnualSeries / aggregateWavgSeries для агрегации
 */

window.AnnualToggle = (function () {

  /**
   * Агрегирует месячный ряд в годовой.
   *
   * @param {Array}  series   — массив точек {date, value, label, ...}
   * @param {string} aggType  — 'sum' | 'avg'
   * @returns {Array} годовой ряд {date, value, label, yoy_change_pct, mom_change_pct:null}
   */
  function aggregateAnnualSeries(series, aggType) {
    if (!series || !series.length) return [];

    // Группируем по году
    const byYear = {};
    for (const p of series) {
      if (p.value == null) continue;
      const year = p.date.slice(0, 4);
      if (!byYear[year]) byYear[year] = [];
      byYear[year].push(Number(p.value));
    }

    const years = Object.keys(byYear).sort();
    const result = [];
    const annualVals = {};

    for (const year of years) {
      const vals = byYear[year];
      if (!vals.length) continue;
      let val;
      if (aggType === 'sum') {
        val = vals.reduce((a, b) => a + b, 0);
      } else { // avg
        val = vals.reduce((a, b) => a + b, 0) / vals.length;
      }
      annualVals[year] = val;
      result.push({
        date: year + '-01-01',
        label: year,
        value: val,
        yoy_change_pct: null,
        mom_change_pct: null,
      });
    }

    // Считаем YoY
    for (let i = 1; i < result.length; i++) {
      const cur  = result[i].value;
      const prev = result[i - 1].value;
      if (prev != null && prev !== 0 && cur != null) {
        result[i].yoy_change_pct = (cur - prev) / Math.abs(prev) * 100;
      }
    }

    return result;
  }

  /**
   * Средневзвешенная агрегация по году.
   *
   * @param {Array} valueSeries  — ряд значений (ставка/срок)
   * @param {Array} weightSeries — ряд весов (объём)
   * @returns {Array} годовой ряд
   */
  function aggregateWavgSeries(valueSeries, weightSeries) {
    if (!valueSeries || !valueSeries.length) return [];

    // Строим карту весов по дате
    const weightMap = {};
    for (const p of (weightSeries || [])) {
      if (p.value != null) weightMap[p.date] = Number(p.value);
    }

    // Группируем по году: взвешенная сумма и сумма весов
    const byYear = {}; // year -> {wsum, wval}
    for (const p of valueSeries) {
      if (p.value == null) continue;
      const year = p.date.slice(0, 4);
      const w = weightMap[p.date] ?? 1; // fallback — равный вес
      if (!byYear[year]) byYear[year] = { wsum: 0, wval: 0 };
      byYear[year].wsum += w;
      byYear[year].wval += Number(p.value) * w;
    }

    const years = Object.keys(byYear).sort();
    const result = [];

    for (const year of years) {
      const { wsum, wval } = byYear[year];
      const val = wsum > 0 ? wval / wsum : null;
      result.push({
        date: year + '-01-01',
        label: year,
        value: val,
        yoy_change_pct: null,
        mom_change_pct: null,
      });
    }

    // Считаем YoY (для ставок — абсолютная разность, п.п.)
    // Возвращаем как есть; страница сама знает единицу измерения
    for (let i = 1; i < result.length; i++) {
      const cur  = result[i].value;
      const prev = result[i - 1].value;
      if (prev != null && prev !== 0 && cur != null) {
        result[i].yoy_change_pct = (cur - prev) / Math.abs(prev) * 100;
      }
    }

    return result;
  }

  /**
   * Вставляет кнопку «Год» в тулбар.
   *
   * @param {HTMLElement} toolbar   — элемент .chart-toolbar
   * @param {Function}    onToggle  — callback(isAnnual: boolean)
   * @returns {HTMLButtonElement} кнопка
   */
  function injectAnnualBtn(toolbar, onToggle) {
    // Находим первую группу btn-group (диапазоны)
    const btnGroups = toolbar.querySelectorAll('.btn-group');
    if (!btnGroups.length) return null;

    // Создаём отдельную btn-group для «Год»
    const group = document.createElement('div');
    group.className = 'btn-group';
    group.style.marginLeft = '0';

    const btn = document.createElement('button');
    btn.setAttribute('data-annual', 'true');
    btn.textContent = 'Данные за год';
    btn.style.minWidth = '48px';

    let active = false;

    btn.addEventListener('click', () => {
      active = !active;
      if (active) {
        btn.classList.add('active');
      } else {
        btn.classList.remove('active');
      }
      onToggle(active);
    });

    group.appendChild(btn);

    // Вставляем после последней btn-group в первом flex-контейнере
    const flexWrap = toolbar.querySelector('[style*="flex"]') || toolbar;
    // Ищем родительский div с gap/flex
    const firstRow = toolbar.querySelector('div[style]');
    if (firstRow) {
      firstRow.appendChild(group);
    } else {
      toolbar.insertBefore(group, toolbar.querySelector('.toolbar-actions'));
    }

    return btn;
  }

  /**
   * Возвращает true если ряд месячный (может агрегироваться в год).
   * Проверяем по наличию месячных дат.
   */
  function isMonthly(series) {
    if (!series || !series.length) return false;
    const sample = series.find(p => p.date);
    if (!sample) return false;
    // Дата вида YYYY-MM-DD, где MM != '01' в каком-то элементе
    return series.some(p => p.date && p.date.slice(5, 7) !== '01');
  }

  return {
    aggregateAnnualSeries,
    aggregateWavgSeries,
    injectAnnualBtn,
    isMonthly,
  };
})();
