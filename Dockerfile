FROM ubuntu:24.04

ENV DEBIAN_FRONTEND=noninteractive

# System deps
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        curl \
        ca-certificates \
        build-essential \
        netcat-openbsd \
        git && \
    rm -rf /var/lib/apt/lists/*

# Install uv
RUN curl -LsSf https://astral.sh/uv/install.sh | sh
# uv is installed into /root/.local/bin (and sometimes /root/.cargo/bin); add them to PATH
ENV PATH="/root/.local/bin:/root/.cargo/bin:${PATH}"

WORKDIR /app

# Copy project files into image
COPY . /app

# Ensure src/.env exists with container-friendly defaults (only if missing)

RUN printf 'API_BASE_IP=0.0.0.0\n\
API_BASE_PORT=27099\n\
DB_USER=User\n\
DB_PASSWORD=Pass\n\
DB_IP=mongo.steam.internal\n\
DB_PORT=27017\n\
DB_NAME=Steam_Project\n' > /app/.env

# Create uv venv and install Python dependencies at build time
RUN uv venv .venv -p 3.13.7 && \
    uv pip install -r requirements.txt
    
RUN uv pip install boto3 requests pymongo rich

# Expose app ports
EXPOSE 8080
EXPOSE 27099

# Entrypoint script (starts DB init + API + Streamlit)
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/bin/bash", "/docker-entrypoint.sh"]
