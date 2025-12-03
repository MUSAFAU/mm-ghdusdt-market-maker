FROM python:3.11-slim
WORKDIR /app
COPY mock_server.py /app/
RUN pip install aiohttp
CMD ["python3", "mock_server.py"]
