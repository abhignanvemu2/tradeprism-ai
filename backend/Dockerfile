FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY tradeprism ./tradeprism
RUN useradd --create-home researcher && mkdir /data && chown researcher:researcher /data
USER researcher
ENV DATA_DIR=/data
CMD ["uvicorn","tradeprism.api:app","--host","0.0.0.0","--port","8000"]
