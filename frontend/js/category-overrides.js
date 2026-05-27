// Rules for replacing raw indicators with user-facing combo cards.
// Used by both category.html and index.html so visible counters stay in sync.
const COMBO_OVERRIDES = {
  supply_volume: [
    { label: 'Объем ввода жилья', url: 'combo-chart.html', parentCode: '2.1', hideCodes: ['2.2', '2.3'], sparkCode: '2.1' },
    { label: 'Структура ввода жилья', url: 'share-chart.html', parentCode: null, hideCodes: [], sparkCode: '2.2' },
    { label: 'Ввод жилья на душу населения', url: 'per-capita-chart.html', parentCode: '2.6', hideCodes: ['2.7', '2.8'], sparkCode: '2.6' },
  ],
  concentration: [
    { label: 'Уровень концентрации рынка (HHI)', url: 'ihh-chart.html', parentCode: '3.17', hideCodes: ['3.18'] },
  ],
  apartments: [
    { label: 'Количество квартир по комнатности', url: 'apartments-count.html',
      parentCode: 'apartments_count_total',
      hideCodes: ['apartments_count_1k','apartments_count_2k','apartments_count_3k','apartments_count_4k'] },
    { label: 'Средняя площадь по комнатности', url: 'apartments-area.html',
      parentCode: 'apartments_area_total',
      hideCodes: ['apartments_area_1k','apartments_area_2k','apartments_area_3k','apartments_area_4k'] },
    { label: 'Структура по комнатности', url: 'apartments-share.html',
      parentCode: null, hideCodes: ['apartments_share_1k','apartments_share_2k','apartments_share_3k','apartments_share_4k'] },
  ],
  prices: [
    { label: 'Цены на жилье по типам квартир (Росстат)', url: 'prices-chart.html', parentCode: '4.4', hideCodes: ['4.5', '4.4.1', '4.4.2', '4.4.3', '4.5.1', '4.5.2', '4.5.3', '4.5.4'] },
  ],
  demand: [
    { label: 'Темп продаж квартир на первичном рынке', url: 'sales-pace-chart.html', parentCode: '5.9', hideCodes: ['5.9.ma12'] },
    { label: 'Темп продаж машиномест на первичном рынке', url: 'sales-pace-mm-chart.html', parentCode: '5.22', hideCodes: ['5.22.ma12'] },
    { label: 'Уровень потребности в жилье для достижения минимально приемлемых условий комфорта проживания', url: 'housing-need-chart.html', parentCode: null, hideCodes: [] },
    { label: 'Скорость удовлетворения потребности при текущем объеме ввода', url: 'housing-pace-chart.html', parentCode: null, hideCodes: [] },
    { label: 'Уровень реальной потребности в жилье для достижения минимально приемлемых условий комфорта проживания', url: 'housing-need-real-chart.html', parentCode: null, hideCodes: [] },
    { label: 'Скорость удовлетворения реальной потребности при текущем объеме ввода', url: 'housing-pace-real-chart.html', parentCode: null, hideCodes: [] },
  ],
  mortgage_base: [
    { label: 'Количество выданных ипотечных кредитов', url: 'mortgage-count.html', parentCode: '6.7', hideCodes: ['6.13'] },
    { label: 'Объем выданных ипотечных кредитов', url: 'mortgage-volume.html', parentCode: '6.8', hideCodes: ['6.14'] },
    { label: 'Средневзвешенная ставка по ипотечным кредитам', url: 'mortgage-rate.html', parentCode: '6.9', hideCodes: ['6.15'] },
    { label: 'Средневзвешенный срок ипотечного кредита', url: 'mortgage-term.html', parentCode: '6.10', hideCodes: ['6.16'] },
    { label: 'Средний размер ипотечного кредита', url: 'mortgage-size.html', parentCode: '6.11', hideCodes: ['6.17'] },
    { label: 'Средний ежемесячный платеж по ипотеке', url: 'mortgage-payment.html', parentCode: '6.12', hideCodes: ['6.18'] },
  ],
  mortgage_subsidy: [
    { label: 'Количество кредитов по программам господдержки', url: 'subsidy-count.html', parentCode: '6.36', hideCodes: ['6.37','6.38','6.39','6.40','6.41','6.42','6.43','6.44','6.45'] },
    { label: 'Объем кредитов по программам господдержки', url: 'subsidy-volume.html', parentCode: null, hideCodes: [] },
    { label: 'Ставки по программам господдержки', url: 'subsidy-rate.html', parentCode: null, hideCodes: [] },
    { label: 'Средний срок кредита', url: 'subsidy-term.html', parentCode: null, hideCodes: [] },
    { label: 'Средняя сумма кредита', url: 'subsidy-loan-amount.html', parentCode: null, hideCodes: [] },
    { label: 'Доля собственных средств (LTV)', url: 'subsidy-ltv.html', parentCode: null, hideCodes: [] },
    { label: 'Средняя стоимость жилья', url: 'subsidy-property-price.html', parentCode: null, hideCodes: [] },
    { label: 'Средняя площадь жилья', url: 'subsidy-area.html', parentCode: null, hideCodes: [] },
    { label: 'Средняя цена 1 м²', url: 'subsidy-price-per-sqm.html', parentCode: null, hideCodes: [] },
    { label: 'Цели кредитования по программам', url: 'subsidy-purpose-structure.html', parentCode: null, hideCodes: [] },
    { label: 'Семейная ипотека: типы семей', url: 'subsidy-family-types.html', parentCode: null, hideCodes: [] },
  ],
  mortgage_igs: [
    { label: 'Количество ипотечных кредитов на ИЖС', url: 'igs-count.html', parentCode: '6.70', hideCodes: ['6.76','6.82'] },
    { label: 'Объем ипотечных кредитов на ИЖС', url: 'igs-volume.html', parentCode: '6.71', hideCodes: ['6.77','6.83'] },
    { label: 'Средневзвешенная ставка по ипотечным кредитам на ИЖС', url: 'igs-rate.html', parentCode: '6.72', hideCodes: ['6.78','6.84'] },
    { label: 'Средневзвешенный срок ипотеки на ИЖС', url: 'igs-term.html', parentCode: '6.73', hideCodes: ['6.79','6.85'] },
    { label: 'Средний размер кредита по ипотеке на ИЖС', url: 'igs-size.html', parentCode: '6.74', hideCodes: ['6.80','6.86'] },
    { label: 'Средний ежемесячный платеж по ипотеке на ИЖС', url: 'igs-payment.html', parentCode: '6.75', hideCodes: ['6.81','6.87'] },
  ],
  mortgage_debt: [
    { label: 'Объем задолженности по ипотеке', url: 'debt-volume.html', parentCode: '6.19', hideCodes: ['6.22','6.25'] },
    { label: 'Объём просроченной задолженности по ипотеке', url: 'debt-overdue.html', parentCode: '6.20', hideCodes: ['6.23','6.26'] },
    { label: 'Доля просроченной задолженности по ипотеке', url: 'debt-overdue-share.html', parentCode: '6.21', hideCodes: ['6.24','6.27'] },
  ],
  under_construction_domrf: [
    { label: 'Жилая площадь МЖД: все vs активное строительство', url: 'uc-area.html',
      parentCode: 'uc_area_total', hideCodes: ['uc_area_active'] },
    { label: 'Новые проекты: все vs активные', url: 'uc-new.html',
      parentCode: 'uc_new_total', hideCodes: ['uc_new_active'] },
  ],
  market_balance: [
    { label: 'Новые проекты / ввод МЖС', url: 'uc-new-vs-input.html',
      parentCode: 'uc_new_vs_input_total', hideCodes: ['uc_new_vs_input_active'] },
    { label: 'Запасы строящегося жилья', url: 'uc-stock.html',
      parentCode: 'uc_stock_years_total', hideCodes: ['uc_stock_years_active'] },
    { label: 'Обеспеченность продаж новыми запусками', url: 'uc-new-vs-sales.html',
      parentCode: 'uc_new_vs_sales_total', hideCodes: ['uc_new_vs_sales_active'] },
    { label: 'Коэффициент поглощения', url: 'uc-absorption.html',
      parentCode: 'uc_absorption_total', hideCodes: ['uc_absorption_active'] },
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
      result.push({ ...ind, _comboUrl: rule.url, _comboLabel: rule.label,
        _sparkCode: rule.sparkCode || null,
        _sparkPeriodicity: rule.sparkPeriodicity || ind.periodicity || 'annual' });
    } else {
      result.push(ind);
    }
  }

  for (const rule of appendRules) {
    result.push({
      _isComboOnly: true,
      _comboUrl: rule.url,
      _comboLabel: rule.label,
      _sparkCode: rule.sparkCode || null,
      _sparkPeriodicity: rule.sparkPeriodicity || 'annual',
    });
  }

  return result;
}
