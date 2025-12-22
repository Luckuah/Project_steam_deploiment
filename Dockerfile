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
RUN mkdir -p src \
 && if [ ! -f src/.env ]; then \
      printf '%s\n' \
'API_BASE_IP=localhost' \
'API_BASE_PORT=27099' \
'DB_USER=User' \
'DB_PASSWORD=Pass' \
'DB_IP=mongo' \
'DB_PORT=27017' \
'DB_NAME=Steam_Project' > src/.env; \
    fi

# Create uv venv and install Python dependencies at build time
RUN uv venv .venv -p 3.13.7 && \
    uv pip install -r requirements.txt

# Expose app ports
EXPOSE 8501
EXPOSE 27099

# Entrypoint script (starts DB init + API + Streamlit)
COPY docker-entrypoint.sh /docker-entrypoint.sh
RUN chmod +x /docker-entrypoint.sh

ENTRYPOINT ["/bin/bash", "/docker-entrypoint.sh"]
