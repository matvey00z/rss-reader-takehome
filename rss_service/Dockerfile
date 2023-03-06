FROM python:3.11.2-slim-bullseye

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/* ./

EXPOSE 8000

CMD ["uvicorn", "service:app", "--host", "0.0.0.0", "--port", "8000"]