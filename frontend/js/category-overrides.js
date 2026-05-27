// Rules for replacing raw indicators with user-facing combo cards.
// Used by both category.html and index.html so visible counters stay in sync.
//
// series[] — массив серий для цикличного переключения значений в таблице категорий.
// Первый элемент — агрегат или главный ряд (он же _sparkCode по умолчанию).
// series: [] означает «нет осмысленного набора серий» (структурные/долевые графики).
const COMBO_OVERRIDES = {
  supply_volume: [
    { label: 'Объем ввода жилья', url: 'combo-chart.html', parentCode: '2.1', hideCodes: ['2.2', '2.3'], sparkCode: '2.1',
      series: [{ code: '2.1', label: 'Всего' }, { code: '2.2', label: 'МЖС' }, { code: '2.3', label: 'ИЖС' }] },
    { label: 'Структура ввода жилья', url: 'share-chart.html', parentCode: null, hideCodes: [], sparkCode: '2.2',
      series: [] },
    { label: 'Ввод жилья на душу населения', url: 'per-capita-chart.html', parentCode: '2.6', hideCodes: ['2.7', '2.8'], sparkCode: '2.6',
      series: [{ code: '2.6', label: 'Всего' }, { code: '2.7', label: 'МЖС' }, { code: '2.8', label: 'ИЖС' }] },
  ],
  concentration: [
    { label: 'Уровень концентрации рынка (HHI)', url: 'ihh-chart.html', parentCode: '3.17', hideCodes: ['3.18'],
      series: [{ code: '3.17', label: 'Групп' }, { code: '3.18', label: 'HHI' }] },
  ],
  apartments: [
    { label: 'Количество квартир по комнатности', url: 'apartments-count.html',
      parentCode: 'apartments_count_total',
      hideCodes: ['apartments_count_1k', 'apartments_count_2k', 'apartments_count_3k', 'apartments_count_4k'],
      series: [{ code: 'apartments_count_total', label: 'Всего' }, { code: 'apartments_count_1k', label: '1-комн.' }, { code: 'apartments_count_2k', label: '2-комн.' }, { code: 'apartments_count_3k', label: '3-комн.' }] },
    { label: 'Средняя площадь по комнатности', url: 'apartments-area.html',
      parentCode: 'apartments_area_total',
      hideCodes: ['apartments_area_1k', 'apartments_area_2k', 'apartments_area_3k', 'apartments_area_4k'],
      series: [{ code: 'apartments_area_total', label: 'Всего' }, { code: 'apartments_area_1k', label: '1-комн.' }, { code: 'apartments_area_2k', label: '2-комн.' }, { code: 'apartments_area_3k', label: '3-комн.' }] },
    { label: 'Структура по комнатности', url: 'apartments-share.html',
      parentCode: null, hideCodes: ['apartments_share_1k', 'apartments_share_2k', 'apartments_share_3k', 'apartments_share_4k'],
      series: [] },
  ],
  prices: [
    { label: 'Цены на жилье по типам квартир (Росстат)', url: 'prices-chart.html', parentCode: '4.4', hideCodes: ['4.5', '4.4.1', '4.4.2', '4.4.3', '4.5.1', '4.5.2', '4.5.3', '4.5.4'],
      series: [{ code: '4.4', label: 'Первичный' }, { code: '4.5', label: 'Вторичный' }] },
  ],
  demand: [
    { label: 'Темп продаж квартир на первичном рынке', url: 'sales-pace-chart.html', parentCode: '5.9', hideCodes: ['5.9.ma12'],
      series: [{ code: '5.9', label: 'Темп' }, { code: '5.9.ma12', label: 'МА-12' }] },
    { label: 'Темп продаж машиномест на первичном рынке', url: 'sales-pace-mm-chart.html', parentCode: '5.22', hideCodes: ['5.22.ma12'],
      series: [{ code: '5.22', label: 'Темп' }, { code: '5.22.ma12', label: 'МА-12' }] },
    { label: 'Уровень потребности в жилье для достижения минимально приемлемых условий комфорта проживания', url: 'housing-need-chart.html', parentCode: null, hideCodes: [],
      series: [] },
    { label: 'Скорость удовлетворения потребности при текущем объеме ввода', url: 'housing-pace-chart.html', parentCode: null, hideCodes: [],
      series: [] },
    { label: 'Уровень реальной потребности в жилье для достижения минимально приемлемых условий комфорта проживания', url: 'housing-need-real-chart.html', parentCode: null, hideCodes: [],
      series: [] },
    { label: 'Скорость удовлетворения реальной потребности при текущем объеме ввода', url: 'housing-pace-real-chart.html', parentCode: null, hideCodes: [],
      series: [] },
  ],
  mortgage_base: [
    // parentCode — первичный рынок (6.7–6.12); вторичный — 6.13–6.18
    { label: 'Количество выданных ипотечных кредитов', url: 'mortgage-count.html', parentCode: '6.7', hideCodes: ['6.13'],
      series: [{ code: '6.7', label: 'Первичный' }, { code: '6.13', label: 'Вторичный' }] },
    { label: 'Объем выданных ипотечных кредитов', url: 'mortgage-volume.html', parentCode: '6.8', hideCodes: ['6.14'],
      series: [{ code: '6.8', label: 'Первичный' }, { code: '6.14', label: 'Вторичный' }] },
    { label: 'Средневзвешенная ставка по ипотечным кредитам', url: 'mortgage-rate.html', parentCode: '6.9', hideCodes: ['6.15'],
      series: [{ code: '6.9', label: 'Первичный' }, { code: '6.15', label: 'Вторичный' }] },
    { label: 'Средневзвешенный срок ипотечного кредита', url: 'mortgage-term.html', parentCode: '6.10', hideCodes: ['6.16'],
      series: [{ code: '6.10', label: 'Первичный' }, { code: '6.16', label: 'Вторичный' }] },
    { label: 'Средний размер ипотечного кредита', url: 'mortgage-size.html', parentCode: '6.11', hideCodes: ['6.17'],
      series: [{ code: '6.11', label: 'Первичный' }, { code: '6.17', label: 'Вторичный' }] },
    { label: 'Средний ежемесячный платеж по ипотеке', url: 'mortgage-payment.html', parentCode: '6.12', hideCodes: ['6.18'],
      series: [{ code: '6.12', label: 'Первичный' }, { code: '6.18', label: 'Вторичный' }] },
  ],
  mortgage_subsidy: [
    // parentCode: 6.36 — Семейная (count); остальные программы: 6.38 Льготная, 6.40 ДВ, 6.42 IT, 6.44 Регионы
    { label: 'Количество кредитов по программам господдержки', url: 'subsidy-count.html', parentCode: '6.36', hideCodes: ['6.37', '6.38', '6.39', '6.40', '6.41', '6.42', '6.43', '6.44', '6.45'],
      series: [{ code: '6.36', label: 'Семейная' }, { code: '6.38', label: 'Льготная' }, { code: '6.40', label: 'ДВ' }, { code: '6.42', label: 'IT' }, { code: '6.44', label: 'Регионы' }] },
    // объём: 6.37 Семейная, 6.39 Льготная, 6.41 ДВ, 6.43 IT, 6.45 Регионы
    { label: 'Объем кредитов по программам господдержки', url: 'subsidy-volume.html', parentCode: null, hideCodes: [],
      series: [{ code: '6.37', label: 'Семейная' }, { code: '6.39', label: 'Льготная' }, { code: '6.41', label: 'ДВ' }, { code: '6.43', label: 'IT' }, { code: '6.45', label: 'Регионы' }] },
    // характеристики кредитов: 6.46.x Все, 6.47.x Льготная, 6.48.x Семейная, 6.49.x ДВ, 6.50.x IT, 6.51.x Регионы
    { label: 'Ставки по программам господдержки', url: 'subsidy-rate.html', parentCode: null, hideCodes: [],
      series: [{ code: '6.46.2', label: 'Все' }, { code: '6.48.2', label: 'Семейная' }, { code: '6.47.2', label: 'Льготная' }, { code: '6.49.2', label: 'ДВ' }, { code: '6.50.2', label: 'IT' }, { code: '6.51.2', label: 'Регионы' }] },
    { label: 'Средний срок кредита', url: 'subsidy-term.html', parentCode: null, hideCodes: [],
      series: [{ code: '6.46.4', label: 'Все' }, { code: '6.48.4', label: 'Семейная' }, { code: '6.47.4', label: 'Льготная' }, { code: '6.49.4', label: 'ДВ' }, { code: '6.50.4', label: 'IT' }, { code: '6.51.4', label: 'Регионы' }] },
    { label: 'Средняя сумма кредита', url: 'subsidy-loan-amount.html', parentCode: null, hideCodes: [],
      series: [{ code: '6.46.1', label: 'Все' }, { code: '6.48.1', label: 'Семейная' }, { code: '6.47.1', label: 'Льготная' }, { code: '6.49.1', label: 'ДВ' }, { code: '6.50.1', label: 'IT' }, { code: '6.51.1', label: 'Регионы' }] },
    { label: 'Доля собственных средств (LTV)', url: 'subsidy-ltv.html', parentCode: null, hideCodes: [],
      series: [{ code: '6.46.3', label: 'Все' }, { code: '6.48.3', label: 'Семейная' }, { code: '6.47.3', label: 'Льготная' }, { code: '6.49.3', label: 'ДВ' }, { code: '6.50.3', label: 'IT' }, { code: '6.51.3', label: 'Регионы' }] },
    { label: 'Средняя стоимость жилья', url: 'subsidy-property-price.html', parentCode: null, hideCodes: [],
      series: [{ code: '6.46.5', label: 'Все' }, { code: '6.48.5', label: 'Семейная' }, { code: '6.47.5', label: 'Льготная' }, { code: '6.49.5', label: 'ДВ' }, { code: '6.50.5', label: 'IT' }, { code: '6.51.5', label: 'Регионы' }] },
    { label: 'Средняя площадь жилья', url: 'subsidy-area.html', parentCode: null, hideCodes: [],
      series: [{ code: '6.46.6', label: 'Все' }, { code: '6.48.6', label: 'Семейная' }, { code: '6.47.6', label: 'Льготная' }, { code: '6.49.6', label: 'ДВ' }, { code: '6.50.6', label: 'IT' }, { code: '6.51.6', label: 'Регионы' }] },
    { label: 'Средняя цена 1 м²', url: 'subsidy-price-per-sqm.html', parentCode: null, hideCodes: [],
      series: [{ code: '6.46.7', label: 'Все' }, { code: '6.48.7', label: 'Семейная' }, { code: '6.47.7', label: 'Льготная' }, { code: '6.49.7', label: 'ДВ' }, { code: '6.50.7', label: 'IT' }, { code: '6.51.7', label: 'Регионы' }] },
    { label: 'Цели кредитования по программам', url: 'subsidy-purpose-structure.html', parentCode: null, hideCodes: [],
      series: [] },
    { label: 'Семейная ипотека: типы семей', url: 'subsidy-family-types.html', parentCode: null, hideCodes: [],
      series: [] },
  ],
  mortgage_igs: [
    // 6.70–6.75 всего; 6.76–6.81 строительство объектов ИЖС; 6.82–6.87 покупка готовых объектов ИЖС
    { label: 'Количество ипотечных кредитов на ИЖС', url: 'igs-count.html', parentCode: '6.70', hideCodes: ['6.76', '6.82'],
      series: [{ code: '6.70', label: 'Всего' }, { code: '6.76', label: 'Стр-во' }, { code: '6.82', label: 'Покупка' }] },
    { label: 'Объем ипотечных кредитов на ИЖС', url: 'igs-volume.html', parentCode: '6.71', hideCodes: ['6.77', '6.83'],
      series: [{ code: '6.71', label: 'Всего' }, { code: '6.77', label: 'Стр-во' }, { code: '6.83', label: 'Покупка' }] },
    { label: 'Средневзвешенная ставка по ипотечным кредитам на ИЖС', url: 'igs-rate.html', parentCode: '6.72', hideCodes: ['6.78', '6.84'],
      series: [{ code: '6.72', label: 'Всего' }, { code: '6.78', label: 'Стр-во' }, { code: '6.84', label: 'Покупка' }] },
    { label: 'Средневзвешенный срок ипотеки на ИЖС', url: 'igs-term.html', parentCode: '6.73', hideCodes: ['6.79', '6.85'],
      series: [{ code: '6.73', label: 'Всего' }, { code: '6.79', label: 'Стр-во' }, { code: '6.85', label: 'Покупка' }] },
    { label: 'Средний размер кредита по ипотеке на ИЖС', url: 'igs-size.html', parentCode: '6.74', hideCodes: ['6.80', '6.86'],
      series: [{ code: '6.74', label: 'Всего' }, { code: '6.80', label: 'Стр-во' }, { code: '6.86', label: 'Покупка' }] },
    { label: 'Средний ежемесячный платеж по ипотеке на ИЖС', url: 'igs-payment.html', parentCode: '6.75', hideCodes: ['6.81', '6.87'],
      series: [{ code: '6.75', label: 'Всего' }, { code: '6.81', label: 'Стр-во' }, { code: '6.87', label: 'Покупка' }] },
  ],
  mortgage_debt: [
    { label: 'Объем задолженности по ипотеке', url: 'debt-volume.html', parentCode: '6.19', hideCodes: ['6.22', '6.25'],
      series: [{ code: '6.19', label: 'Всего' }, { code: '6.22', label: 'Первичный' }, { code: '6.25', label: 'Вторичный' }] },
    { label: 'Объём просроченной задолженности по ипотеке', url: 'debt-overdue.html', parentCode: '6.20', hideCodes: ['6.23', '6.26'],
      series: [{ code: '6.20', label: 'Всего' }, { code: '6.23', label: 'Первичный' }, { code: '6.26', label: 'Вторичный' }] },
    { label: 'Доля просроченной задолженности по ипотеке', url: 'debt-overdue-share.html', parentCode: '6.21', hideCodes: ['6.24', '6.27'],
      series: [{ code: '6.21', label: 'Всего' }, { code: '6.24', label: 'Первичный' }, { code: '6.27', label: 'Вторичный' }] },
  ],
  under_construction_domrf: [
    { label: 'Жилая площадь МЖД: все vs активное строительство', url: 'uc-area.html',
      parentCode: 'uc_area_total', hideCodes: ['uc_area_active'],
      series: [{ code: 'uc_area_total', label: 'Всего' }, { code: 'uc_area_active', label: 'Активное' }] },
    { label: 'Новые проекты: все vs активные', url: 'uc-new.html',
      parentCode: 'uc_new_total', hideCodes: ['uc_new_active'],
      series: [{ code: 'uc_new_total', label: 'Всего' }, { code: 'uc_new_active', label: 'Активные' }] },
  ],
  market_balance: [
    { label: 'Новые проекты / ввод МЖС', url: 'uc-new-vs-input.html',
      parentCode: 'uc_new_vs_input_total', hideCodes: ['uc_new_vs_input_active'],
      series: [{ code: 'uc_new_vs_input_total', label: 'Все' }, { code: 'uc_new_vs_input_active', label: 'Активное' }] },
    { label: 'Запасы строящегося жилья', url: 'uc-stock.html',
      parentCode: 'uc_stock_years_total', hideCodes: ['uc_stock_years_active'],
      series: [{ code: 'uc_stock_years_total', label: 'Все' }, { code: 'uc_stock_years_active', label: 'Активное' }] },
    { label: 'Обеспеченность продаж новыми запусками', url: 'uc-new-vs-sales.html',
      parentCode: 'uc_new_vs_sales_total', hideCodes: ['uc_new_vs_sales_active'],
      series: [{ code: 'uc_new_vs_sales_total', label: 'Все' }, { code: 'uc_new_vs_sales_active', label: 'Активное' }] },
    { label: 'Коэффициент поглощения', url: 'uc-absorption.html',
      parentCode: 'uc_absorption_total', hideCodes: ['uc_absorption_active'],
      series: [{ code: 'uc_absorption_total', label: 'Все' }, { code: 'uc_absorption_active', label: 'Активное' }] },
  ],
};

function applyComboOverrides(catCode, indicators) {
  const rules = COMBO_OVERRIDES[catCode];
  if (!rules || !rules.length) return indicators;

  const hideCodes = new Set();
  const parentMap = {};
  const appendRules = [];

  for (const rule of rules) {
    rule.hideCodes.forEach(c => hideCodes.add(c));
    if (rule.parentCode !== null) {
      parentMap[rule.parentCode] = rule;
    } else {
      appendRules.push(rule);
    }
  }

  const result = [];
  for (const ind of indicators) {
    if (hideCodes.has(ind.code)) continue;

    if (parentMap[ind.code]) {
      const rule = parentMap[ind.code];
      const series = rule.series || [];
      const sparkCode = series.length ? series[0].code : (rule.sparkCode || null);
      result.push({
        ...ind,
        _comboUrl: rule.url,
        _comboLabel: rule.label,
        _sparkCode: sparkCode,
        _sparkPeriodicity: rule.sparkPeriodicity || ind.periodicity || 'annual',
        _series: series,
      });
    } else {
      result.push(ind);
    }
  }

  for (const rule of appendRules) {
    const series = rule.series || [];
    const sparkCode = series.length ? series[0].code : (rule.sparkCode || null);
    result.push({
      _isComboOnly: true,
      _comboUrl: rule.url,
      _comboLabel: rule.label,
      _sparkCode: sparkCode,
      _sparkPeriodicity: rule.sparkPeriodicity || 'annual',
      _series: series,
    });
  }

  return result;
}
