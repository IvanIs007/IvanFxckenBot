# Используем легкий образ Python
FROM python:3.11-slim

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Копируем файл зависимостей
COPY requirements.txt .

# Устанавливаем библиотеки
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код (включая твой main.py)
COPY . .

# Открываем порт наружу (Render использует его для пинга)
EXPOSE 10000

# Команда для запуска бота (замени main.py на имя своего файла, если оно другое)
CMD ["python", "main.py"]
