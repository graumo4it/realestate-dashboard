"""
Парсер ДОМ.РФ — оркестратор migrate-скриптов.

API наш.дом.рф закрыт WAF (403 Forbidden).
Данные уже лежат локально в migration/domrf_data/.
Каждый migrate-скрипт читает файлы, пишет в БД и обновляет view.
Оркестратор запускает их последовательно и суммирует кол-во строк.
"""

import logging
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from base import BaseParser

log = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent


class DomRFParser(BaseParser):
    source_code = "domrf"

    # Скрипты запускаются последовательно в этом порядке.
    # Каждый должен выводить строку вида "Upserted: N rows" в stdout.
    SCRIPTS = [
        "migration/migrate_apartments.py",
        "migration/migrate_matrix_projects.py",
        "migration/migrate_sales_matrix.py",
        "migration/migrate_under_construction_domrf.py",
        "migration/calc_sales_pace.py",
        "migration/calc_sales_pace_mm.py",
        "migration/calc_developer_activity.py",
        "migration/calc_demand_activity.py",
        "migration/calc_avg_apt_area.py",
    ]

    def fetch_raw(self):
        return None

    def parse(self, raw):
        return []

    def run(self) -> dict:
        """Запускает migrate-скрипты последовательно, суммирует загруженные строки."""
        total = 0
        errors = []

        # Информация о файлах в domrf_data/
        domrf_data = PROJECT_ROOT / "migration" / "domrf_data"
        if domrf_data.exists():
            files = list(domrf_data.rglob("*.*"))
            log.info(f"[domrf] domrf_data/: {len(files)} файлов")
        else:
            log.warning(f"[domrf] Папка {domrf_data} не найдена — migrate-скрипты могут упасть")

        for script_rel in self.SCRIPTS:
            script_path = PROJECT_ROOT / script_rel
            if not script_path.exists():
                log.warning(f"[domrf] Скрипт не найден, пропускаем: {script_path}")
                continue

            log.info(f"[domrf] → {script_rel}")
            result = subprocess.run(
                [sys.executable, str(script_path)],
                capture_output=True,
                text=True,
                cwd=str(PROJECT_ROOT),
            )

            # Парсим "Upserted: N rows" из stdout
            m = re.search(r"Upserted:\s*(\d+)\s*rows", result.stdout or "")
            n = int(m.group(1)) if m else 0
            total += n

            if result.returncode != 0:
                msg = (
                    f"{script_rel}: returncode={result.returncode}, "
                    f"stderr={result.stderr[:300] if result.stderr else ''}"
                )
                log.error(f"[domrf] ОШИБКА — {msg}")
                errors.append(msg)
            else:
                log.info(f"[domrf] ✓ {script_rel}: {n} строк")

        status = "error" if errors else "success"
        error_str = "; ".join(errors) if errors else None

        log.info(f"[domrf] Завершено: status={status}, total_rows={total}")
        return {
            "status": status,
            "rows": total,
            "error": error_str,
        }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = DomRFParser().run()
    print(result)
