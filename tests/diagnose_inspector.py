"""
Simula exactamente lo que hace el MCP Inspector para diagnosticar
por qué la conexión falla.
"""
import subprocess
import json
import time
import sys

INIT_MSG = json.dumps({
    "jsonrpc": "2.0",
    "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "test-inspector", "version": "0.22.0"}
    },
    "id": 1
}) + "\n"

LIST_TOOLS_MSG = json.dumps({
    "jsonrpc": "2.0",
    "method": "tools/list",
    "params": {},
    "id": 2
}) + "\n"

INITIALIZED_NOTIF = json.dumps({
    "jsonrpc": "2.0",
    "method": "notifications/initialized",
    "params": {}
}) + "\n"

def main():
    print("Arrancando servidor MCP...")
    proc = subprocess.Popen(
        [sys.executable, "server.py"],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        errors="replace",
        bufsize=1,
    )
    time.sleep(1.0)  # esperar a que arranque

    try:
        # 1. Enviar initialize
        print("-> Enviando: initialize")
        proc.stdin.write(INIT_MSG)
        proc.stdin.flush()
        time.sleep(0.5)

        # 2. Leer respuesta
        resp_line = proc.stdout.readline()
        if resp_line:
            resp = json.loads(resp_line)
            print("<- Recibido initialize result OK")
            print(f"   protocolVersion: {resp.get('result', {}).get('protocolVersion')}")
            print(f"   serverInfo: {resp.get('result', {}).get('serverInfo')}")
        else:
            print("<- ERROR: no se recibio respuesta al initialize")
            return

        # 3. Enviar initialized notification
        print("-> Enviando: notifications/initialized")
        proc.stdin.write(INITIALIZED_NOTIF)
        proc.stdin.flush()
        time.sleep(0.2)

        # 4. Pedir lista de tools
        print("-> Enviando: tools/list")
        proc.stdin.write(LIST_TOOLS_MSG)
        proc.stdin.flush()
        time.sleep(0.5)

        # 5. Leer respuesta tools/list
        resp_line2 = proc.stdout.readline()
        if resp_line2:
            resp2 = json.loads(resp_line2)
            tools = resp2.get("result", {}).get("tools", [])
            print(f"<- Tools ({len(tools)}):")
            for t in tools:
                print(f"    - {t['name']}")
        else:
            print("<- ERROR: no se recibio respuesta al tools/list")

    finally:
        proc.terminate()
        stderr = proc.stderr.read(errors="replace")
        if stderr:
            print(f"\nSTDERR del servidor:\n{stderr}")

if __name__ == "__main__":
    main()
