FROM python:3.11-slim

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Обновляем pip и устанавливаем библиотеки
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Копируем остальной код приложения
COPY bot.py .

# Указываем переменную окружения для мгновенного вывода логов в панель Render
ENV PYTHONUNBUFFERED=1

# Открываем стандартный порт Render
EXPOSE 10000

# Команда для запуска бота
CMD ["python", "bot.py"]
