FROM python:3.11.2-slim-bullseye

WORKDIR /test

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY test_*.py /test/

CMD ["python", "-m", "pytest", "-v", "--html=/output/report.html", "--self-contained-html", "/test"]