import os
from pathlib import Path
from dotenv import load_dotenv

# Busca .env relativo a la raíz del proyecto (dos niveles arriba de este archivo)
# Funciona sin importar el directorio de trabajo actual (CWD)
_PROJECT_ROOT = Path(__file__).parent.parent.parent
load_dotenv(_PROJECT_ROOT / ".env")


class Settings:
    ODOO_URL: str = os.getenv("ODOO_URL", "")
    ODOO_DB: str = os.getenv("ODOO_DB", "")
    ODOO_USERNAME: str = os.getenv("ODOO_USERNAME", "")
    ODOO_PASSWORD: str = os.getenv("ODOO_PASSWORD", "")
    _raw_output = Path(os.getenv("OUTPUT_DIR", str(_PROJECT_ROOT / "outputs")))
    OUTPUT_DIR: Path = _raw_output if _raw_output.is_absolute() else _PROJECT_ROOT / _raw_output

    # Transporte MCP. streamable-http = servidor remoto (default, detrás de reverse
    # proxy — ver DEPLOY_SERVIDOR.md). stdio = local (Claude Desktop misma máquina).
    MCP_TRANSPORT: str = os.getenv("MCP_TRANSPORT", "streamable-http")
    MCP_HOST: str = os.getenv("MCP_HOST", "127.0.0.1")
    MCP_PORT: int = int(os.getenv("MCP_PORT", "8080"))

    @classmethod
    def validate(cls) -> None:
        missing = [
            name for name in ("ODOO_URL", "ODOO_DB", "ODOO_USERNAME", "ODOO_PASSWORD")
            if not getattr(cls, name)
        ]
        if missing:
            raise EnvironmentError(
                f"Faltan variables de entorno requeridas: {', '.join(missing)}. "
                "Copia .env.example a .env y completa los valores."
            )

    @classmethod
    def ensure_output_dir(cls) -> None:
        cls.OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


settings = Settings()
