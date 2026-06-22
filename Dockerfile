# Используем официальный готовый образ Python
FROM python:3.11-slim

# Устанавливаем рабочую папку в контейнере
WORKDIR /app

# Копируем файл с зависимостями
COPY requirements.txt .

# Устанавливаем библиотеки, отдавая приоритет уже готовым бинарникам
RUN pip install --no-cache-dir --prefer-binary -r requirements.txt

# Копируем весь остальной код
COPY . .

# Команда для запуска нашего бота
CMD ["python", "bot.py"]
