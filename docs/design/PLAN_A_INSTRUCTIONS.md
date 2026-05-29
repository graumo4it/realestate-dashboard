# Инструкция — реализация Плана A в Claude Design

«Claude Design» (claude.ai/design) — генерация UI-макетов из промптов в браузере.
Шаги по порядку. Промпты можно вставлять как есть.

## Шаг 1 — Контекст для промптов
Скопируй в заметку, вставляй в каждый промпт:
```
Бренд: MACON Real Estate Consultant. Продукт: статистический дашборд рынка
жилой недвижимости РФ. Аудитория: аналитики. Эталоны: FT Markets, OWID, Economist.

Цвета:
  Red #C8181A | Light-blue #C3D7E0 | Ink #0D1B2A | White #FFF
  BG #F2F4F7 | Border #DDE2E8 | Green #0E7C56 | Neg-red #C0392B
ВАЖНО: серый #3F4C50 из текущего сайта НЕ использовать — заменяем.

Шрифты (оставляем как есть): Playfair Display 700 — заголовки;
  IBM Plex Sans 400/500/600 — текст/UI; IBM Plex Mono 400/600 — числа.
```

## Шаг 2 — 3 варианта Hero/шапки (D5)

**Вариант A (рекомендуемый) — светлый + паттерн:**
```
Design a data dashboard homepage hero section for MACON DATA — a Russian real estate
statistics platform.
Style: white/light background (#F2F4F7), sticky header white bg with red bottom border
(#C8181A 2px). Logo "MACON DATA" in Playfair Display. Subtle geometric zigzag/chevron
pattern in brand light-blue (#C3D7E0, 5% opacity) as background texture.
Hero: eyebrow "Открытые данные · Россия" in red uppercase tracking, H1 "Статистика рынка
жилой недвижимости" Playfair Display 3rem, description, 3 stat counters in IBM Plex Mono.
Below: section title + grid of category cards (white surface, 12px radius, subtle shadow,
red icon square, title, count in red mono).
Fonts: Playfair (headings), IBM Plex Sans (body), IBM Plex Mono (numbers).
Do NOT use muddy gray (#3F4C50). Eyebrow must be high-contrast (red on light, not on dark).
Clean, editorial, trustworthy data product.
```

**Вариант B — красный блок-логотип:**
```
Design a MACON DATA homepage with bold brand identity. Header: solid red (#C8181A) left
panel with "MACON DATA" white bold condensed; right side white with navigation. Hero:
dark charcoal (#0D1B2A) banner, large white Playfair heading, brand light-blue (#C3D7E0)
geometric arrow/chevron decorative shape on the right. Category cards grid below on light bg.
Same fonts. More bold/agency feel. Do NOT use gray #3F4C50.
```

**Вариант C — тёмная тема (референс dark mode):**
```
Dark-mode MACON DATA homepage. bg #11161C, surface cards #1A222B, borders
rgba(255,255,255,.08), text #E8EDF2, muted #8A9BAD, accent #E8352A (brightened red),
brand-blue #A8C8D4. Sticky header #1A222B with red bottom border, white logo. Hero with
subtle blue-tinted geometric pattern. Same content/fonts. Bloomberg-terminal-meets-modern.
```

## Шаг 3 — Набор иконок разделов
```
Design a set of 18 line-style SVG icons for real estate statistics categories:
макроданные, ввод жилья, жилищный фонд, строящееся жильё, квартирография,
концентрация рынка, цены, спрос, сбалансированность рынка, ипотека (основная),
ипотека-задолженность, льготная ипотека, ипотека ИЖС, доходы, население, сделки,
доступность жилья, темп продаж.
Style: 2px stroke line icons, single color #C8181A, 24x24, consistent weight, geometric,
no fills. Like Lucide/Feather. Show all on a grid. Replaces current emoji icons.
```

## Шаг 4 — Палитра серий (критично)
```
Design a categorical color palette of EXACTLY 6 colors for multi-series charts, based on
MACON brand. Anchor colors: red #C8181A and brand light-blue #C3D7E0. Requirements:
harmonious, distinguishable, colorblind-safe, professional (FT/Economist). NO purple.
Show: 6 swatches in assignment order with hex; a sample stacked bar chart and a 4-line
chart using them; how they look on white AND on dark #11161C. Replaces current random
palette (red/gray/teal/purple/blue) where purple is off-brand and teal/blue collide.
```

## Шаг 5 — Страница `category` (D3)
```
Design a "category indicators" page for MACON DATA. Full-width, breadcrumb, section heading
+ count. Data table, 5 columns: Показатель (clickable name) | Последнее значение (large
IBM Plex Mono, right-aligned) + period·unit below muted | Изм. г/г (green/red delta pill
with arrow) | Динамика (sparkline 80px) | Источник (muted right). Optional gray uppercase
subsection headers. Subtle zebra, hover row highlight. Filter bar above: Месяц/Квартал/Год.
Same palette/fonts. Professional table like FT/Trading Economics.
Sparklines: ONE consistent style for ALL rows (all area-fill OR all line-only — pick one).
Series-toggle indicator must look clearly clickable (small pill/segmented control, not bare
dots). Show responsive <900px: navigation as horizontal tabs or dropdown select, NOT a tall
vertical list of 14 links above content.
```

## Шаг 6 — Карточка раздела с контентом
```
Design a category card for the homepage grid that is NOT empty. Each card: line-icon (red),
category name, indicator count, AND a small sparkline (or one headline number + delta badge)
of the section's key indicator. White surface, 12px radius, subtle shadow, hover lift.
Compact, not bloated — current cards waste space with only icon+title+count.
```

## Шаг 7 — Страница `chart` (D3 + D2)
```
Design a single-indicator chart page for MACON DATA. Full width. Breadcrumb; H1 in Playfair;
meta row (source + period type). KPI block: compact card, 3 fields (last value / period /
min-max or trend) — current 2-field block is too wide and empty; last value IBM Plex Mono
2rem, green delta badge. Toolbar: button groups [1г/3г/5л/всё] and [Значения/г-г/м-м], right
PNG+Excel outline buttons. Chart card 400px: line 2px #C8181A.
Line chart: visible (not faint) area fill OR clean line — decide and show. Add direct
end-label on last data point and an annotation callout on the largest peak. dataZoom scrubber
at bottom must be THIN and minimal (current red pill handles too bulky). Grid dashed #DDE2E8,
no Y axis line, mono tick labels. Data table below; related cards with sparklines.
Same palette/fonts. Professional data journalism aesthetic.
```

## Шаг 8 — Чарт-стайлгайд + состояния (D2 + D4)
```
Design a chart style guide page for MACON DATA showing 4 chart types:
1. Line+area time series (red #C8181A, direct end-label, dashed grid)
2. Bar chart for deltas (green positive / red negative, zero line)
3. Multi-series 4-line (palette from Step 4, distinct dash patterns for a11y)
4. Stacked bar (4 series in palette, total in tooltip)
For each: tooltip design (dark bg, white text, series color dot, RU number format), x/y axis
style (no Y axis line, dashed split lines, mono ticks), thin dataZoom scrubber.
Also: delta badge component, KPI card, AND empty state + error state for a chart card
(icon + message + retry) — not just loading skeleton.
Light bg, MACON palette.
```

## Шаг 9 — Dark mode (D1)
```
Dark version of the chart page (Step 7): bg #11161C, surface #1A222B,
border rgba(255,255,255,.08), text #E8EDF2, muted #8A9BAD, accent #E8352A,
brand-blue #A8C8D4, chart line #E8352A, grid rgba(255,255,255,.06).
KPI card #1A222B. Show theme toggle (sun/moon pill) in header.
Series palette from Step 4 on dark.
```

## Шаг 10 — Экспорт в План B
Сохрани скриншоты: финальный hero; `category` (desktop + <900px); карточка раздела;
`chart` (light + dark); стайлгайд; набор иконок; свотчи палитры.
Зафиксируй в `DESIGN_SPEC.md`:
- выбранный вариант hero (A/B/C);
- **6 hex палитры серий в порядке назначения**;
- dark-токены (hex);
- решение по area-fill (заметная / нет);
- формат карточки раздела;
- поведение адаптива `category` <900px.

→ передать скриншоты + `DESIGN_SPEC.md` в Claude Code, начать План B с C1.

**Минимальный результат Плана A:** ~9 групп скриншотов + `DESIGN_SPEC.md`.
