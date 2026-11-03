FROM mcr.microsoft.com/playwright/python:v1.64.1-noble
RUN pip install --no-cache-dir playwright==1.64.1
WORKDIR /worker
COPY worker/browser.py /worker/browser.py
ENV HOME=/tmp PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
USER 1000:1000
ENTRYPOINT ["python", "/worker/browser.py"]
