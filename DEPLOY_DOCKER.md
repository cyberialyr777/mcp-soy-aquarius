# Despliegue con Docker — soyaquarius-mcp

Stack: **MCP** (contenedor interno, sin puerto expuesto) + **nginx** (única cara
pública, TLS + Bearer token) en la misma red de Docker.

```
Laptop (Claude Desktop) --stdio--> mcp-remote
   --HTTPS + Bearer token--> nginx :443  (contenedor)
   --HTTP red interna docker--> mcp :8080  (contenedor, NO publicado)
   --XML-RPC--> Odoo :8069
```

La imagen lleva **solo el código y las dependencias**. Las credenciales van en
`.env`, que se inyecta al arrancar (`env_file`), **nunca dentro de la imagen**.

---

## Pasos en el servidor

### 1. Configurar `.env`
```bash
cp .env.example .env
```
Llenar:
- `ODOO_URL`, `ODOO_DB`, `ODOO_USERNAME`, `ODOO_PASSWORD` (usuario dedicado, no admin).
- `MCP_TOKEN` — genera uno: `openssl rand -hex 32`.

**Odoo:** ¿corre nativo en el host? En `.env` pon `ODOO_URL=http://host.docker.internal:8069`
y descomenta el bloque `extra_hosts` del servicio `mcp` en `docker-compose.yml`.
¿Odoo también está en Docker? Conéctalo a la red `internal` y usa
`http://<servicio-odoo>:8069`.

### 2. Certificados TLS en `./nginx/certs/`
Necesita `fullchain.pem` y `privkey.pem`.

- Con dominio interno + CA: pon ahí los certs reales.
- Solo IP en LAN (self-signed):
  ```bash
  mkdir -p nginx/certs
  openssl req -x509 -newkey rsa:2048 -nodes -days 825 \
    -keyout nginx/certs/privkey.pem \
    -out   nginx/certs/fullchain.pem \
    -subj "/CN=<IP-o-hostname-del-servidor>"
  ```
  (mcp-remote en las laptops acepta self-signed con `NODE_TLS_REJECT_UNAUTHORIZED=0`
  o instalando el cert como confiable.)

### 3. Levantar
```bash
docker compose up -d --build
docker compose logs -f mcp     # debe decir "soyaquarius_mcp iniciado..."
```

### 4. Verificar
```bash
# Sin token -> 401
curl -k https://localhost/mcp -i

# Con token -> responde el MCP (no 401/404)
curl -k https://localhost/mcp -i -H "Authorization: Bearer <MCP_TOKEN>"
```

### 5. Firewall
Abrir el 443 **solo a la LAN o VPN**, nunca a internet.

## Notas

- El MCP no genera archivos para el usuario: los Excels los arma Claude Desktop
  directamente en el chat a partir de los datos. Lo único que se escribe en disco
  es la **bitácora JSONL** (auditoría interna, en `OUTPUT_DIR`). Si quieres que
  persista fuera del contenedor, monta un volumen en el servicio `mcp`:
  `volumes: ["./outputs:/app/outputs"]`. Para el MVP no es obligatorio.
- `restart: unless-stopped` reinicia el stack solo tras reiniciar el servidor.
- Nunca commitear `.env` ni `nginx/certs/` con valores reales.
