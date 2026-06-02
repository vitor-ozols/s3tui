FROM python:3.11-slim

# Impede a criação de arquivos .pyc e mantém o log sem buffer
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Instala o poetry
RUN pip install --no-cache-dir poetry

# Copia os arquivos de configuração de dependências
COPY pyproject.toml poetry.lock README.md ./

# Configura o poetry para não criar um virtualenv (desnecessário no Docker)
RUN poetry config virtualenvs.create false

# Instala as dependências (sem o próprio pacote e dependências de dev por enquanto)
RUN poetry install --only main --no-root --no-interaction --no-ansi

# Copia todo o código fonte para dentro do container
COPY . .

# Instala o projeto atual para liberar o comando `s3tui` globalmente
RUN poetry install --only main --no-interaction --no-ansi

# Comando padrão ao iniciar o container
CMD ["s3tui"]
