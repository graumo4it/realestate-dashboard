"""
Скрипт унификации ширины фильтра «Тип индикатора» на всех комбо-страницах.

Работает в два прохода:
  ПРОХОД 1 (анализ):
    - Для каждого файла из SOURCE_DIR извлекает все подписи серий из LABELS.
    - Дополнительно учитывает label «Тип индикатора» / «Тип динамики цен» в самой кнопке.
    - Считает длину каждой подписи в символах и находит самую длинную по всем файлам.
    - Вычисляет min-width в пикселях по формуле, основанной на шрифте IBM Plex Sans 0.83rem.

  ПРОХОД 2 (правка):
    - В каждом файле находит CSS `.filter-bar-btn { ... min-width: Npx; ... }`
      и `.filter-dropdown { ... min-width: Npx; ... }` и заменяет min-width на TARGET_WIDTH.

Формула ширины:
  - Каждый символ кириллицы в IBM Plex Sans 500 на размере 0.83rem (~13.3px) ≈ 7.8px ширины.
    Это эвристика, проверенная на средних значениях; для безопасности берём 8.5px/символ.
  - Внутренние отступы кнопки: 14px (left padding) + 6px (gap) + 13px (svg-иконка слева)
    + 6px (gap) + текст + 6px (gap) + 11px (svg-шеврон справа) + 14px (right padding)
    = ~70px не-текстовых элементов в кнопке.
  - Для пунктов дропдауна: 18px (left padding) + 15px (чекбокс) + 10px (gap)
    + 10px (точка) + 10px (gap) + текст + 18px (right padding) = ~81px не-текстовых.
  - Берём максимум двух (≈81), округлим до 90 для запаса.
  - Минимальное min-width: 200px (нижняя граница для эстетики, даже если все подписи короткие).

Использование:
  python3 unify_filter_width.py
Можно подкрутить:
  - SOURCE_DIR — откуда читать исходники
  - OUTPUT_DIR — куда писать результат (если None, перезаписываем in-place)
"""
import re
from pathlib import Path

# ── Конфигурация ────────────────────────────────────────────────────────────
SOURCE_DIR = Path('/Users/egor/Работа/data hub/realestate-dashboard/frontend')
OUTPUT_DIR = Path('/Users/egor/Работа/data hub/realestate-dashboard/frontend')

CHARS_TO_PX = 8.5      # ширина одного символа в IBM Plex Sans 500, ~13.3px size
NON_TEXT_PX = 90       # суммарная ширина не-текстовых элементов в строке дропдауна
MIN_WIDTH   = 220      # минимальный min-width
ROUND_TO    = 10       # округление вверх до кратного 10

# Названия меток для самой кнопки — учитываем тоже
BUTTON_LABELS_RE = re.compile(
    r'>\s*(Тип индикатора|Тип динамики цен|Тип жилья|Программа)\s*<',
    re.IGNORECASE,
)

# Все файлы, которые считаем «комбо-страницами»
COMBO_FILES = [
    "apartments-area.html",
    "apartments-count.html",
    "apartments-share.html",
    "combo-chart.html",
    "igs-count.html",
    "igs-payment.html",
    "igs-rate.html",
    "igs-size.html",
    "igs-term.html",
    "igs-volume.html",
    "ihh-chart.html",
    "mortgage-count.html",
    "mortgage-payment.html",
    "mortgage-rate.html",
    "mortgage-size.html",
    "mortgage-term.html",
    "mortgage-volume.html",
    "per-capita-chart.html",
    "prices-chart.html",
    "share-chart.html",
    "subsidy-count.html",
    "uc-absorption.html",
    "uc-area.html",
    "uc-new-vs-input.html",
    "uc-new-vs-sales.html",
    "uc-new.html",
    "uc-stock.html",
]


# ── Извлечение подписей ─────────────────────────────────────────────────────
def extract_labels(src: str) -> list[str]:
    """
    Извлекает все строковые значения из LABELS = { key: 'value', ... } или
    SERIES_CONFIG = { code: { color: ..., label: 'value', ... } }.
    Также возвращает текст метки самой кнопки (Тип индикатора и т.п.).
    """
    labels = []

    # 1) const LABELS = { key: 'value', key2: 'value2', ... }
    for m in re.finditer(r"const\s+LABELS\s*=\s*\{([^}]+)\}", src):
        body = m.group(1)
        # Извлекаем все 'string' или "string" значения после двоеточия
        for sm in re.finditer(r":\s*['\"]([^'\"]+)['\"]", body):
            labels.append(sm.group(1))

    # 2) SERIES_CONFIG = { '4.4': { color: '...', label: 'value', ... }, ... }
    for m in re.finditer(r"SERIES_CONFIG\s*=\s*\{[\s\S]*?\n\}", src):
        body = m.group(0)
        for sm in re.finditer(r"label:\s*['\"]([^'\"]+)['\"]", body):
            labels.append(sm.group(1))

    # 3) Метка кнопки в HTML (Тип индикатора и т.п.)
    btn_match = BUTTON_LABELS_RE.search(src)
    if btn_match:
        labels.append(btn_match.group(1))

    return labels


def compute_width(max_chars: int) -> int:
    """Вычисляет min-width по самой длинной подписи."""
    px = int(max_chars * CHARS_TO_PX + NON_TEXT_PX)
    # Округление вверх до кратного ROUND_TO
    px = ((px + ROUND_TO - 1) // ROUND_TO) * ROUND_TO
    return max(px, MIN_WIDTH)


# ── Замена в CSS ────────────────────────────────────────────────────────────
def apply_width(src: str, width: int) -> tuple[str, int]:
    """
    Заменяет min-width в правилах .filter-bar-btn и .filter-dropdown.
    Возвращает (новый_текст, количество_замен).
    """
    # Находим CSS-блоки .filter-bar-btn { ... } и .filter-dropdown { ... }
    # внутри них меняем min-width: Npx; → min-width: <width>px;
    pattern = re.compile(
        r"(\.filter-bar-btn\s*\{[^}]*?min-width:\s*)\d+(px;[^}]*?\})",
        re.DOTALL,
    )
    src, n1 = pattern.subn(rf"\g<1>{width}\g<2>", src)

    pattern = re.compile(
        r"(\.filter-dropdown\s*\{[^}]*?min-width:\s*)\d+(px;[^}]*?\})",
        re.DOTALL,
    )
    src, n2 = pattern.subn(rf"\g<1>{width}\g<2>", src)

    return src, n1 + n2


# ── Main ────────────────────────────────────────────────────────────────────
def main() -> None:
    # Проход 1: собрать длины подписей
    print("=" * 72)
    print("ПРОХОД 1 — анализ подписей")
    print("=" * 72)

    overall_max = 0
    overall_max_label = ""
    overall_max_file = ""
    per_file: list[tuple[str, list[str], int]] = []

    for fname in COMBO_FILES:
        path = SOURCE_DIR / fname
        if not path.exists():
            print(f"[SKIP] {fname}: файла нет в {SOURCE_DIR}")
            continue
        src = path.read_text(encoding="utf-8")
        labels = extract_labels(src)
        if not labels:
            print(f"[WARN] {fname}: подписи не найдены — пропуск")
            per_file.append((fname, [], 0))
            continue
        max_len = max(len(l) for l in labels)
        longest = next(l for l in labels if len(l) == max_len)
        per_file.append((fname, labels, max_len))
        if max_len > overall_max:
            overall_max = max_len
            overall_max_label = longest
            overall_max_file = fname

    print()
    print(f"{'Файл':<32} {'макс. длина':>12}   самая длинная подпись")
    print("-" * 90)
    for fname, labels, max_len in per_file:
        if not labels:
            print(f"{fname:<32} {'—':>12}   (LABELS не найдены — буду применять глобальную ширину)")
            continue
        longest = max(labels, key=len)
        marker = "  ←—" if fname == overall_max_file else ""
        print(f"{fname:<32} {max_len:>12}   {longest}{marker}")

    print()
    print(f"Глобально самая длинная подпись: «{overall_max_label}» ({overall_max} симв.) в {overall_max_file}")

    target_width = compute_width(overall_max)
    print(f"Расчёт ширины: {overall_max} симв. × {CHARS_TO_PX}px + {NON_TEXT_PX}px ≈ {int(overall_max*CHARS_TO_PX + NON_TEXT_PX)}px")
    print(f"Финальный min-width (округлено до {ROUND_TO}): {target_width}px")

    # Проход 2: применить
    print()
    print("=" * 72)
    print(f"ПРОХОД 2 — применяю min-width: {target_width}px ко всем файлам")
    print("=" * 72)

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    applied = 0
    skipped_no_css = []
    not_found = []
    for fname in COMBO_FILES:
        path = SOURCE_DIR / fname
        if not path.exists():
            not_found.append(fname)
            continue
        src = path.read_text(encoding="utf-8")
        new_src, n = apply_width(src, target_width)
        out_path = OUTPUT_DIR / fname
        out_path.write_text(new_src, encoding="utf-8")
        if n > 0:
            print(f"[OK]   {fname}: заменено правил {n}")
            applied += 1
        else:
            skipped_no_css.append(fname)
            print(f"[SKIP] {fname}: правила .filter-bar-btn/.filter-dropdown не найдены")

    print()
    print(f"Готово. Применено: {applied}/{len(COMBO_FILES) - len(not_found)} файлов.")
    print(f"Результаты: {OUTPUT_DIR}")

    if skipped_no_css:
        print()
        print("⚠  Пропущенные файлы (в них нет CSS .filter-bar-btn/.filter-dropdown):")
        for f in skipped_no_css:
            print(f"   • {f}")
        print()
        print("   Это значит, что файл в SOURCE_DIR — старого формата (с сайдбаром или")
        print("   ещё без блока .filter-bar). Замените исходник свежей версией")
        print("   и запустите скрипт повторно.")

    if not_found:
        print()
        print(f"⚠  Файлы не найдены в {SOURCE_DIR}:")
        for f in not_found:
            print(f"   • {f}")


if __name__ == "__main__":
    main()
