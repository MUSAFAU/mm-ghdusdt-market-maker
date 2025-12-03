FROM python:3.11-slim
WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir aiohttp websockets python-dotenv
CMD ["python3", "mm_bot.py"]
