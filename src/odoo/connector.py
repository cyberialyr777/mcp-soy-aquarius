import xmlrpc.client
import logging
from typing import Any

from src.config.settings import settings

logger = logging.getLogger(__name__)


class OdooConnectionError(Exception):
    pass


class OdooConnector:
    def __init__(self) -> None:
        settings.validate()
        self._url = settings.ODOO_URL
        self._db = settings.ODOO_DB
        self._username = settings.ODOO_USERNAME
        self._password = settings.ODOO_PASSWORD
        self._uid: int | None = None
        self._models: xmlrpc.client.ServerProxy | None = None

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def authenticate(self) -> int:
        if self._uid:
            return self._uid
        try:
            common = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/common")
            uid = common.authenticate(self._db, self._username, self._password, {})
        except Exception as exc:
            raise OdooConnectionError(f"No se pudo conectar a Odoo en {self._url}: {exc}") from exc

        if not uid:
            raise OdooConnectionError(
                "Autenticación fallida. Verifica ODOO_USERNAME y ODOO_PASSWORD en .env."
            )
        self._uid = uid
        self._models = xmlrpc.client.ServerProxy(f"{self._url}/xmlrpc/2/object")
        logger.info("Conectado a Odoo como uid=%s", uid)
        return uid

    @property
    def models(self) -> xmlrpc.client.ServerProxy:
        if self._models is None:
            self.authenticate()
        return self._models  # type: ignore[return-value]

    @property
    def uid(self) -> int:
        if self._uid is None:
            self.authenticate()
        return self._uid  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Core CRUD helpers
    # ------------------------------------------------------------------

    def execute(self, model: str, method: str, *args: Any, **kwargs: Any) -> Any:
        """Llama execute_kw(db, uid, password, model, method, [args], {kwargs}).

        args se pasa tal cual como lista posicional. kwargs como dict de keywords.
        Ejemplo: execute("res.partner", "search_read", domain, fields=fields, limit=5)
        → execute_kw(..., [domain], {fields: fields, limit: 5})
        """
        try:
            return self.models.execute_kw(
                self._db, self.uid, self._password,
                model, method, list(args), kwargs,
            )
        except xmlrpc.client.Fault as exc:
            raise OdooConnectionError(
                f"Error Odoo al ejecutar {model}.{method}: {exc.faultString}"
            ) from exc

    def search_read(
        self,
        model: str,
        domain: list,
        fields: list,
        limit: int = 0,
        order: str = "",
    ) -> list[dict]:
        # execute_kw espera: args=[domain], kwargs={fields, limit, order}
        # execute(*args) hace list(args), así que pasamos domain directamente (no [domain])
        kwargs: dict[str, Any] = {"fields": fields}
        if limit:
            kwargs["limit"] = limit
        if order:
            kwargs["order"] = order
        return self.execute(model, "search_read", domain, **kwargs)

    def search(self, model: str, domain: list, limit: int = 0) -> list[int]:
        kwargs: dict[str, Any] = {}
        if limit:
            kwargs["limit"] = limit
        return self.execute(model, "search", domain, **kwargs)

    def read(self, model: str, ids: list[int], fields: list) -> list[dict]:
        # execute_kw espera: args=[ids], kwargs={fields: fields}
        return self.execute(model, "read", ids, fields=fields)

    def create(self, model: str, values: dict) -> int:
        # XML-RPC no puede serializar None; Odoo usa False como valor vacío.
        values = {k: (False if v is None else v) for k, v in values.items()}
        return self.execute(model, "create", values)

    def write(self, model: str, ids: list[int], values: dict) -> bool:
        values = {k: (False if v is None else v) for k, v in values.items()}
        return self.execute(model, "write", ids, values)

    def unlink(self, model: str, ids: list[int]) -> bool:
        return self.execute(model, "unlink", ids)

    def call_method(self, model: str, method: str, ids: list[int], *args: Any) -> Any:
        return self.execute(model, method, ids, *args)

    def get_fields(self, model: str, attributes: list | None = None) -> dict:
        # fields_get(allfields=None, attributes=None) — sin args posicionales
        kwargs: dict[str, Any] = {}
        if attributes:
            kwargs["attributes"] = attributes
        return self.execute(model, "fields_get", **kwargs)

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def search_count(self, model: str, domain: list) -> int:
        return self.execute(model, "search_count", domain)

    def read_group(
        self,
        model: str,
        domain: list,
        fields: list,
        groupby: list,
        lazy: bool = False,
    ) -> list[dict]:
        """Agrega registros usando read_group de Odoo.

        Útil para obtener sumas por grupo sin traer cada registro individualmente.
        Ejemplo: ventas totales por producto en una tienda.
        """
        return self.execute(
            model, "read_group", domain, fields, groupby, lazy=lazy
        )
