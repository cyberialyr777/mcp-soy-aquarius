FROM python:3.11-slim

WORKDIR /app

# Dependencias primero para aprovechar la cache de capas
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Código de la app
COPY . .

# El MCP escucha en este puerto DENTRO del contenedor.
# Ojo: en docker-compose NO se publica al host (solo lo alcanza nginx por la red interna).
EXPOSE 8080

CMD ["python", "server.py"]
