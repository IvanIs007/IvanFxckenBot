FROM python:3.11-slim

WORKDIR /app

# Устанавливаем инструменты сборки (gcc и dev-пакеты), необходимые для компиляции зависимостей
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    python3-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .

# Обновляем pip и устанавливаем библиотеки
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Удаляем инструменты сборки, чтобы уменьшить вес контейнера
RUN apt-get purge -y --auto-remove build-essential python3-dev

COPY bot.py .

ENV PYTHONUNBUFFERED=1

EXPOSE 10000

CMD ["python", "bot.py"]
