import logging
import sys

# Forzar UTF-8 en stdout y stderr cuando el proceso está en modo piped
# (en Windows, Python usa cp1252 por defecto, lo que rompe el proxy de Node.js)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", write_through=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(encoding="utf-8")

from mcp.server.fastmcp import FastMCP

from src.config.settings import settings
from src.odoo.connector import OdooConnector, OdooConnectionError
from src.tools import generic, compras, traspasos

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[logging.StreamHandler(sys.stderr)],
)
logger = logging.getLogger(__name__)

mcp = FastMCP("soyaquarius_mcp")


def _build_server() -> None:
    settings.validate()
    settings.ensure_output_dir()

    odoo = OdooConnector()

    generic.register(mcp, odoo)
    compras.register(mcp, odoo)
    traspasos.register(mcp, odoo)

    # Sprint 4+: descomentar a medida que se implementen
    # from src.tools import pedidos, reportes
    # pedidos.register(mcp, odoo)
    # reportes.register(mcp, odoo)

    logger.info("soyaquarius_mcp iniciado. Tools registrados: genericos, compras, traspasos.")


def main() -> None:
    _build_server()
    mcp.run()


if __name__ == "__main__":
    main()
