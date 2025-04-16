FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y \
    git \
    curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL https://download.docker.com/linux/static/stable/$(uname -m)/docker-25.0.2.tgz | tar xz && \
    mv docker/* /usr/local/bin/ && \
    rmdir docker

RUN curl -L "https://github.com/docker/compose/releases/download/v2.27.0/docker-compose-$(uname -s)-$(uname -m)" -o /usr/local/bin/docker-compose && \
chmod +x /usr/local/bin/docker-compose

COPY webhook-deployer.py .

RUN pip install flask

EXPOSE 5005
CMD ["python", "-u", "webhook-deployer.py"]