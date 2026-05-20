# План: Миграция всех комбо-страниц + удаление AnnualToggle shim

## Контекст

Phase 1–3 перенесли 10 страниц на `ComboPage.init()`. Целевое состояние — **все комбо-страницы используют `ComboPage.init()`**, после чего можно безопасно удалить 230-строчный AnnualToggle shim из `period-toggle.js` и устаревший `annual-toggle.js`.

Аудит нашёл **37 комбо-страниц** (с `CODES`/`LABELS`). Из них 10 уже мигрированы, **27 требуют миграции**.

---

## Текущее состояние

### Уже мигрировано (10 страниц)
`igs-count`, `igs-rate`, `igs-term`, `igs-volume`, `mortgage-rate`, `mortgage-term`, `mortgage-volume`, `subsidy-count`, `subsidy-volume`, `uc-new`

### Требуют миграции (27 страниц) — по батчам

| Батч | Страницы | Характеристика |
|------|----------|---------------|
| **4a — Simple** (11) | `uc-absorption`, `uc-area`, `uc-new-vs-input`, `uc-new-vs-sales`, `uc-stock`, `debt-overdue`, `debt-overdue-share`, `debt-volume`, `apartments-area`, `apartments-count`, `per-capita-chart` | Стандартные CODES/LABELS, нет computed-рядов, чистый `sum`/`avg` |
| **4b — PeriodToggle-ready** (6) | `housing-need-chart`, `housing-need-real-chart`, `housing-pace-chart`, `housing-pace-real-chart`, `sales-pace-chart`, `sales-pace-mm-chart` | Уже используют `PeriodToggle.injectButtons()`, нужно обернуть в ComboPage |
| **4c — AnnualToggle** (6) | `combo-chart`, `igs-payment`, `igs-size`, `mortgage-count`, `mortgage-payment`, `mortgage-size` | Используют `AnnualToggle` — удалить + перенести на ComboPage |
| **4d — Complex** (4) | `apartments-share`, `ihh-chart`, `prices-chart`, `share-chart` | `buildComputed()`, нестандартные вычисления, требуют `onData` hook или расширения ComboPage |

---

## Подход к миграции по батчам

### Батч 4a: Simple pages
**Шаблон** (взять из `uc-new.html` как эталон):
```html
<script src="js/combo-page.js?v=1"></script>
<script>
  ComboPage.init({
    codes:  { key1: 'X.X', key2: 'X.X' },
    labels: { key1: 'Метка 1', key2: 'Метка 2' },
    keys:   ['key1', 'key2'],
    chartType: 'line',          // или 'bar'
    aggType: 'avg',             // или 'sum'
    unit: ' тыс. руб.',
    decimals: 1,
    fileName: 'page-name',
  });
</script>
```
Удалить: весь inline JS (`init()`, `buildChart()`, `renderKPI()`, `renderTable()`, `buildDropdown()`).

**Страницы-близнецы**: `uc-absorption/area/new-vs-input/new-vs-sales/stock` — одинаковая структура, только CODES разные.

### Батч 4b: PeriodToggle-ready pages
Эти страницы уже имеют корректные кнопки периода, но управляют ими вручную.

**Шаг миграции**:
1. Убрать ручные вызовы `PeriodToggle.injectButtons()` из `init()`
2. Убрать `window.AGG_TYPE`, `window._WEIGHT_CODES` глобалы (если есть)
3. Обернуть в `ComboPage.init()` с `aggType: 'avg'` / `'sum'`
4. Проверить, что ComboPage правильно обрабатывает `sales-pace` с MA12-рядом (через `onData` если нужно)

**Особенность `sales-pace-chart` / `sales-pace-mm-chart`**: содержат MA12-ряды (скользящее среднее). Если MA12 не является самостоятельным API-показателем, а вычисляется inline — перенести логику в `onData` hook.

### Батч 4c: AnnualToggle pages
Паттерн: страница использует `isAnnual` флаг внутри `buildChart()` и напрямую вызывает `AnnualToggle.aggregateAnnualSeries()`.

**Шаги**:
1. Убрать `isAnnual` переменную и все `if (isAnnual)` ветки
2. Убрать `AnnualToggle.injectAnnualBtn()` вызов
3. Убрать `AnnualToggle.aggregateAnnualSeries()` / `aggregateWavgSeries()` вызовы
4. Передать агрегацию в `ComboPage.init()` через `aggType` + `codes: { key: { value, weight } }` для wavg
5. `combo-chart.html` отдельно — у неё `buildMerged()` для total = sum(2.2, 2.3); перенести через `onData`

**combo-chart.html специфика** (МЖС + ИЖС):
- Вычисляет `total = v22 + v23` — реализовать через `onData: (data) => { data['total'] = ... }`
- Добавить `'total'` в `keys` с `labels['total'] = 'Всего'`
- Три вкладки таблицы (Всего / МЖС / ИЖС) — поддерживаются ComboPage через `[data-table]` вкладки

**igs-payment / igs-size**: `aggType: 'wavg'` с парами `{ value, weight }`.
**mortgage-count**: `aggType: 'sum'`.
**mortgage-payment / mortgage-size**: `aggType: 'wavg'`.

### Батч 4d: Complex pages
Требуют отдельного исследования перед миграцией.

| Страница | Сложность | Предварительный план |
|----------|-----------|---------------------|
| `apartments-share` | buildComputed (доли) | `onData` hook вычисляет доли, инжектирует в allData |
| `share-chart` | buildComputed (YoY/MoM в б.п.) | `onData` hook + `isPp: true` |
| `ihh-chart` | CODE_AVG/CODE_MED, 2 dropdown | Возможно, 2 вызова `ComboPage.init()` или расширение API |
| `prices-chart` | 9 серий, двухуровневые вкладки таблицы | `onTableHeader` + кастомные вкладки через `onData` |

⚠️ Если `ihh-chart` или `prices-chart` не поддаются ComboPage без значительного расширения модуля — оставить с кастомным `init()` и просто удалить AnnualToggle-зависимость (PeriodToggle напрямую).

---

## Phase 5: Удаление AnnualToggle shim

После миграции всех 27 страниц:

1. **`frontend/js/period-toggle.js`**: удалить IIFE-блок шима (строки 375–608)
2. **`frontend/js/annual-toggle.js`**: удалить файл
3. **Поиск по фронтенду**: убедиться, что нет `data-period-shim="auto"` атрибутов и ни одна страница не загружает `annual-toggle.js`
4. Уменьшение `period-toggle.js`: ~230 строк → файл станет чище

---

## Критические файлы

| Файл | Роль |
|------|------|
| `frontend/js/combo-page.js` | Модуль — добавить `onData` hook если не поддерживается |
| `frontend/js/period-toggle.js` | Содержит shim (строки 375–608) — удалить в Phase 5 |
| `frontend/js/annual-toggle.js` | Устаревший файл — удалить в Phase 5 |
| `frontend/*.html` (27 файлов) | По батчам выше |

**Эталон миграции**: `frontend/uc-new.html` (самый чистый мигрированный пример).

---

## Порядок работы

```
Phase 4a (11 страниц) → коммит
Phase 4b (6 страниц)  → коммит
Phase 4c (6 страниц)  → коммит
Phase 4d (4 страницы) → коммит
Phase 5  (shim removal) → коммит
```

Каждый батч: мигрировать → открыть все страницы батча в браузере (localhost:3000) → проверить KPI, график, таблицу, переключатели периода, PNG/XLSX.

---

## Верификация

После каждого батча — визуальная проверка в браузере:
- ✓ KPI-карточки показывают значения, дельты г/г и м/м
- ✓ Кнопки 1г/3г/5л/Всё фильтруют данные
- ✓ Кнопки Месяц/Квартал/Год агрегируют ряды (где применимо)
- ✓ Кнопки Значения/Изм. г-г/Изм. м-м переключают режим
- ✓ Дропдаун серий работает
- ✓ PNG и XLSX скачиваются

После Phase 5 — `grep -r "AnnualToggle" frontend/` должен возвращать пусто.
