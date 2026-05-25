"""
Парсер Росстат — делегирующая обёртка над migration/fetch_fedstat.py.

fetch_fedstat.py работает только локально (fedstat.ru блокирует облачные IP).
Все данные, логика парсинга и обновление БД выполняются в подпроцессе.
"""

import logging
import re
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from base import BaseParser

log = logging.getLogger(__name__)

FETCH_FEDSTAT = Path(__file__).parent.parent / "migration" / "fetch_fedstat.py"


class RosstatParser(BaseParser):
    source_code = "rosstat"

    def __init__(self, codes: list[str] | None = None):
        """
        codes — список кодов индикаторов для обработки (передаётся в fetch_fedstat.py).
                None = все коды (поведение как раньше).
        Пример: RosstatParser(codes=["2.1", "2.2", "2.3"])
        """
        super().__init__()
        self.codes = codes

    def fetch_raw(self):
        return None

    def parse(self, raw):
        return []

    def run(self) -> dict:
        """Запускает migration/fetch_fedstat.py как subprocess.

        fetch_fedstat.py сам подключается к БД, делает upsert и обновляет view.
        Поддерживает позиционные аргументы с кодами: python fetch_fedstat.py [код ...]
        Мы только захватываем итоговое кол-во загруженных строк из вывода скрипта.
        """
        cmd = [sys.executable, str(FETCH_FEDSTAT)]
        if self.codes:
            cmd.extend(self.codes)
            log.info(f"[rosstat] Запуск {FETCH_FEDSTAT} с кодами: {self.codes}")
        else:
            log.info(f"[rosstat] Запуск {FETCH_FEDSTAT} (все коды)")
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
        )

        # fetch_fedstat.py использует logging.basicConfig → вывод идёт в stderr;
        # на всякий случай ищем паттерн в обоих потоках.
        combined = (result.stdout or "") + (result.stderr or "")

        m = re.search(r"Итого загружено:\s*(\d+)", combined)
        rows = int(m.group(1)) if m else 0

        status = "success" if result.returncode == 0 else "error"
        error = result.stderr.strip() if result.returncode != 0 else None

        log.info(f"[rosstat] Завершено: status={status}, rows={rows}")
        return {
            "status": status,
            "rows": rows,
            "error": error,
        }


if __name__ == "__main__":
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    result = RosstatParser().run()
    print(result)
