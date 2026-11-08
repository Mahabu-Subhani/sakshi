# SAKSHI review console in one container: Python, Tesseract OCR (English + Hindi) and fonts included.
#   docker build -t sakshi .
#   docker run --rm -p 8501:8501 sakshi                 # then open http://localhost:8501
#   docker run --rm -v "$PWD/in:/data" sakshi python -m sakshi run /data/a.pdf /data/b.jpg --out /data/out
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng tesseract-ocr-hin fonts-liberation libgl1 libglib2.0-0 \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install -r requirements.lock

COPY . .
RUN useradd --create-home sakshi && chown -R sakshi /app
USER sakshi

EXPOSE 8501
HEALTHCHECK CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8501/_stcore/health')" || exit 1
CMD ["streamlit", "run", "app.py", "--server.address=0.0.0.0", "--server.port=8501", "--server.headless=true"]
