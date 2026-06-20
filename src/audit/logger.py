import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any

from src.config.settings import settings

logger = logging.getLogger(__name__)


class AuditLogger:
    """Registra cada corrida en un archivo JSONL de bitácora."""

    def __init__(self) -> None:
        self._log_dir = settings.OUTPUT_DIR / "audit_logs"
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _log_file(self) -> Path:
        today = datetime.now().strftime("%Y-%m-%d")
        return self._log_dir / f"audit_{today}.jsonl"

    def registrar(
        self,
        usuario: str,
        accion: str,
        proveedor: str = "",
        datos_consultados: dict | None = None,
        reglas_aplicadas: list | None = None,
        resultados: dict | None = None,
        archivos_generados: list | None = None,
        acciones_odoo: list | None = None,
        estado: str = "ok",
        error: str = "",
    ) -> dict:
        entrada: dict[str, Any] = {
            "timestamp": datetime.now().isoformat(),
            "usuario": usuario,
            "accion": accion,
            "proveedor": proveedor,
            "datos_consultados": datos_consultados or {},
            "reglas_aplicadas": reglas_aplicadas or [],
            "resultados": resultados or {},
            "archivos_generados": archivos_generados or [],
            "acciones_odoo": acciones_odoo or [],
            "estado": estado,
            "error": error,
        }
        try:
            with open(self._log_file(), "a", encoding="utf-8") as f:
                f.write(json.dumps(entrada, ensure_ascii=False) + "\n")
        except OSError as exc:
            logger.warning("No se pudo escribir en bitácora: %s", exc)
        return entrada

    def registrar_error(self, usuario: str, accion: str, error: str) -> dict:
        return self.registrar(usuario=usuario, accion=accion, estado="error", error=error)

    def leer_hoy(self) -> list[dict]:
        path = self._log_file()
        if not path.exists():
            return []
        with open(path, encoding="utf-8") as f:
            return [json.loads(line) for line in f if line.strip()]
