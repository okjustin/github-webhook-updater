FROM python:3.12-slim

WORKDIR /app
COPY webhook-deployer.py .

RUN pip install flask

EXPOSE 5005
CMD ["python", "webhook-deployer.py"]