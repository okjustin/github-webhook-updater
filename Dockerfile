FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y git && rm -rf /var/lib/apt/lists/*

COPY webhook-deployer.py .

RUN pip install flask

EXPOSE 5005
CMD ["python", "-u", "webhook-deployer.py"]