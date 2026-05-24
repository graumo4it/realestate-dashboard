FROM python:3.11-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc && \
    rm -rf /var/lib/apt/lists/*

# Зависимости парсеров (включая pyxlsb для .xlsb-файлов ДОМ.РФ)
COPY parsers/requirements.txt parsers/requirements.txt
RUN pip install --no-cache-dir -r parsers/requirements.txt

# Код: парсеры + миграционные скрипты
COPY parsers/ parsers/
COPY migration/ migration/

# domrf_data монтируется снаружи как volume (пользователь кладёт файлы вручную)
VOLUME ["/app/migration/domrf_data"]

CMD ["python", "parsers/scheduler.py"]
