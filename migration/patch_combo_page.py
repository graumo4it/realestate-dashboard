#!/usr/bin/env python3
"""
patch_combo_page.py — v2 (универсальный шим)

Минимальная миграция комбо-страниц для поддержки переключателя
периодичности «Месяц | Квартал | Год».

Стратегия v2:
  Вся логика переключения реализована в frontend/js/period-toggle.js v3.1
  через перехват AnnualToggle.injectAnnualBtn(...). Поэтому этот скрипт
  делает только три простых вещи:

   1. Подмена скрипта:
        <script src="js/annual-toggle.js">  →
        <script src="js/period-toggle.js?v=4">

      Если annual-toggle.js не подключён, скрипт также вставляет
      подключение period-toggle.js перед </body>.

   2. Глобализация const _WEIGHT_CODES = {...}  →  window._WEIGHT_CODES = {...}
      (если такая const есть в скрипте страницы). Шим использует это,
      чтобы для wavg-агрегации находить весовые ряды.

   3. Глобализация const AGG_TYPE = '...'  →  window.AGG_TYPE = '...'
      (если такая const есть). Шим использует это, чтобы выбрать
      sum/avg/wavg для квартальной агрегации.

   4. Глобализация const CODES = {...}  →  window.CODES = {...}
      Для разрешения key → code в wavg-агрегации.

   5. Синхронизация allData с window.allData
      Чтобы шим мог подменить ряды для квартального режима.

Что НЕ трогает скрипт:
  • разметку filter-bar / chart-toolbar
  • переменные isAnnual, getFiltered, _initAnnualBtn
  • поведение кнопок «Изм. м/м», «Значения», «Изм. г/г»
  • CSS

Идемпотентность:
  Повторный запуск даёт SKIP — скрипт распознаёт уже мигрированный файл
  по подстроке "period-toggle.js" в content.

Использование:
   python3 migration/patch_combo_page.py frontend/combo-chart.html ...
"""

import re
import sys
from pathlib import Path


# ── Подмена 1: <script src> ─────────────────────────────────────────────

RE_ANNUAL_SCRIPT = re.compile(r'<script src="js/annual-toggle\.js"></script>')
NEW_SCRIPT_TAG   = '<script src="js/period-toggle.js?v=4"></script>'

# ── Подмена 2: const _WEIGHT_CODES → window._WEIGHT_CODES
#
# Сначала переименование WEIGHT_CODES → _WEIGHT_CODES делается отдельно
# (см. patch_file ниже). К этому моменту имя везде унифицировано.

RE_WEIGHT_CODES_CONST = re.compile(
    r'^const\s+_WEIGHT_CODES\s*=', re.MULTILINE
)
NEW_WEIGHT_CODES = 'window._WEIGHT_CODES ='

# ── Подмена 3: const AGG_TYPE → window.AGG_TYPE ────────────────────────

RE_AGG_TYPE_CONST = re.compile(
    r'^const\s+AGG_TYPE\s*=', re.MULTILINE
)
NEW_AGG_TYPE = 'window.AGG_TYPE ='

# ── Подмена 4: const CODES → window.CODES ──────────────────────────────

RE_CODES_CONST = re.compile(
    r'^const\s+CODES\s*=', re.MULTILINE
)
NEW_CODES = 'window.CODES ='


# ─────────────────────────────────────────────────────────────────────


def patch_file(path: str) -> dict:
    """Возвращает {'status': 'ok'|'skip'|'fail', 'changes': [...], 'errors': [...]}"""
    report = {'status': 'ok', 'changes': [], 'errors': []}

    if not Path(path).exists():
        report['status'] = 'fail'
        report['errors'].append('File does not exist')
        return report

    with open(path, 'r', encoding='utf-8') as f:
        content = f.read()
    original = content

    # ── SKIP/UPDATE: уже мигрировано ───────────────────────────────
    # Если страница уже подключает period-toggle.js — это могла быть
    # миграция предыдущей версии (?v=3). Проверяем версию и обновляем
    # cache-bust до ?v=4 если нужно.
    if 'period-toggle.js' in content:
        if '?v=4' in content:
            report['status'] = 'skip'
            report['changes'].append('Already at ?v=4, skipping')
            return report
        # Обновляем версию: ?v=3 → ?v=4 (и любые другие старые номера)
        updated = re.sub(
            r'(period-toggle\.js\?v=)\d+',
            r'\g<1>4',
            content,
        )
        if updated != content:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(updated)
            report['status'] = 'skip'  # формально не делаем full migrate
            report['changes'].append('Cache-bust bumped to ?v=4')
            return report
        # period-toggle.js без ?v= — добавим
        updated = content.replace(
            'period-toggle.js"',
            'period-toggle.js?v=4"',
        )
        if updated != content:
            with open(path, 'w', encoding='utf-8') as f:
                f.write(updated)
            report['status'] = 'skip'
            report['changes'].append('Added ?v=4 cache-bust')
            return report
        report['status'] = 'skip'
        report['changes'].append('Already at correct version')
        return report

    # ── Подмена 1: script src ─────────────────────────────────────
    if RE_ANNUAL_SCRIPT.search(content):
        content = RE_ANNUAL_SCRIPT.sub(NEW_SCRIPT_TAG, content)
        report['changes'].append('script src: annual-toggle.js → period-toggle.js?v=4')
    else:
        # Страница не подключает annual-toggle.js (share-chart, ihh-chart, prices-chart).
        # Вставляем подключение period-toggle.js перед </body>.
        # Атрибут data-period-shim="auto" говорит шиму, что страница НЕ будет
        # сама вызывать injectAnnualBtn — нужен авто-инжект переключателя.
        if '</body>' in content:
            content = content.replace(
                '</body>',
                '<script src="js/period-toggle.js?v=4" data-period-shim="auto"></script>\n</body>',
                1,
            )
            report['changes'].append('script добавлен перед </body> (auto-inject mode)')
        else:
            report['status'] = 'fail'
            report['errors'].append('Не найден ни <script src="js/annual-toggle.js">, ни </body>')
            return report

    # ── Подмена 2: глобализуем _WEIGHT_CODES (учитываем оба имени) ───
    # Сначала переименовываем все вхождения WEIGHT_CODES (без подчёркивания)
    # в _WEIGHT_CODES, чтобы получить единое имя по всему файлу.
    # Используем (?<!_) — не задеваем уже существующие _WEIGHT_CODES.
    renamed = re.subn(r'(?<!_)\bWEIGHT_CODES\b', '_WEIGHT_CODES', content)
    if renamed[1] > 0:
        content = renamed[0]
        report['changes'].append(f'WEIGHT_CODES → _WEIGHT_CODES ({renamed[1]} вхождений)')

    # Теперь глобализуем const _WEIGHT_CODES → window._WEIGHT_CODES
    if RE_WEIGHT_CODES_CONST.search(content):
        content = RE_WEIGHT_CODES_CONST.sub(NEW_WEIGHT_CODES, content)
        report['changes'].append('const _WEIGHT_CODES → window._WEIGHT_CODES')

    # ── Подмена 3: глобализуем AGG_TYPE ───────────────────────────
    if RE_AGG_TYPE_CONST.search(content):
        content = RE_AGG_TYPE_CONST.sub(NEW_AGG_TYPE, content)
        report['changes'].append('const AGG_TYPE → window.AGG_TYPE')

    # ── Подмена 4: глобализуем CODES ──────────────────────────────
    if RE_CODES_CONST.search(content):
        content = RE_CODES_CONST.sub(NEW_CODES, content, count=1)
        report['changes'].append('const CODES → window.CODES')

    # ── Подмена 5: синхронизация allData с window.allData ─────────
    # Минимальная безопасная замена: при объявлении `allData = {}`
    # делаем двойное присваивание `allData = window.allData = {}`.
    # Это сохраняет существующий тип объявления (let / в multi-let).
    new_content, n_alldata = re.subn(
        r'\ballData\s*=\s*\{\}',
        'allData = window.allData = {}',
        content,
        count=1,
    )
    if n_alldata == 1:
        # Также синхронизируем последующие присваивания allData = ...
        # (await api.multiIndicatorData(...) или allData = data)
        new_content = re.sub(
            r'(\n\s*)allData\s*=\s*(await\s+api\.[^\n;]+;)',
            r'\1allData = window.allData = \2',
            new_content,
        )
        new_content = re.sub(
            r'(\n\s*)allData\s*=\s*(data\s*;)',
            r'\1allData = window.allData = \2',
            new_content,
        )
        content = new_content
        report['changes'].append('allData синхронизирован с window.allData')

    # ── Подмена 6: синхронизация computed с window.computed ───────
    # На share-chart.html есть промежуточная переменная `computed`,
    # содержащая предвычисленные доли. Шим должен иметь возможность
    # обновить её при переключении периода.
    new_content, n_computed = re.subn(
        r'\blet\s+computed\s*=\s*\[\]',
        'let computed = window.computed = []',
        content,
        count=1,
    )
    if n_computed == 1:
        # Все последующие `computed = ...` тоже зеркалируем в window.computed
        new_content = re.sub(
            r'(\n\s*)computed\s*=\s*(buildComputed[^\n;]+;)',
            r'\1computed = window.computed = \2',
            new_content,
        )
        content = new_content
        report['changes'].append('computed синхронизирован с window.computed')

    # ── Подмена 7: глобализуем function buildComputed (если есть) ──
    # Чтобы шим мог её вызвать при смене периода.
    new_content, n_bc = re.subn(
        r'^function\s+buildComputed\s*\(',
        'window.buildComputed = function buildComputed(',
        content,
        count=1,
        flags=re.MULTILINE,
    )
    if n_bc == 1:
        # Закрываем выражение точкой с запятой — но это опционально,
        # function expression может быть и без неё. Оставляем как есть.
        content = new_content
        report['changes'].append('function buildComputed → window.buildComputed')

    # ── Запись ─────────────────────────────────────────────────────
    if content == original:
        report['changes'].append('Файл не изменился')
    else:
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)

    return report


def main():
    if len(sys.argv) < 2:
        print('Usage: patch_combo_page.py <file.html> [<file2.html> ...]')
        sys.exit(2)

    summary = {'ok': 0, 'skip': 0, 'fail': 0}
    for arg in sys.argv[1:]:
        paths = list(Path('.').glob(arg)) if '*' in arg else [Path(arg)]
        for path in paths:
            r = patch_file(str(path))
            print(f'\n=== {path} ===  [{r["status"].upper()}]')
            for c in r['changes']:
                print(f'  - {c}')
            for e in r['errors']:
                print(f'  ! {e}')
            summary[r['status']] += 1

    print(f'\nИтого: ok={summary["ok"]}, skip={summary["skip"]}, fail={summary["fail"]}')
    sys.exit(0 if summary['fail'] == 0 else 1)


if __name__ == '__main__':
    main()
