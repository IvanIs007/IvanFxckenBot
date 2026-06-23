FROM python:3.11-alpine

# Устанавливаем рабочую директорию в контейнере
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем библиотеки
RUN pip install --no-cache-dir -r requirements.txt

# Копируем остальной код приложения
COPY bot.py .

# Указываем переменную окружения для мгновенного вывода логов
ENV PYTHONUNBUFFERED=1

# Открываем порт наружу (Render автоматически свяжет его)
EXPOSE 10000

# Команда для запуска бота
CMD ["python", "bot.py"]
