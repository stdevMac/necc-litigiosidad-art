"""Configuración central del sistema NECC.

Todas las rutas y parámetros se resuelven acá a partir de variables de entorno
(o un archivo `.env` en la raíz del MVP), para que cada módulo del pipeline
reciba la misma configuración.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

RAIZ = Path(__file__).resolve().parents[2]
load_dotenv(RAIZ / ".env")


def _ruta(var: str, defecto: Path) -> Path:
    """Ruta tomada del entorno; si es relativa, se resuelve respecto de la raíz del MVP
    (igual que el `.env`), no del directorio desde donde se ejecuta el comando."""
    valor = os.environ.get(var)
    if not valor:
        return defecto
    ruta = Path(valor).expanduser()
    return (ruta if ruta.is_absolute() else RAIZ / ruta).resolve()


@dataclass(frozen=True)
class Config:
    raiz: Path = RAIZ
    datos: Path = field(default_factory=lambda: _ruta("NECC_DATOS", RAIZ / "data"))
    config_dir: Path = field(default_factory=lambda: _ruta("NECC_CONFIG", RAIZ / "config"))

    # LLM (Gemini). Temperatura 0: tarea de extracción, no creativa.
    gemini_api_key: str | None = field(default_factory=lambda: os.environ.get("GEMINI_API_KEY"))
    modelo_llm: str = field(default_factory=lambda: os.environ.get("NECC_MODELO_LLM", "gemini-2.5-flash"))
    modelo_embeddings: str = field(
        default_factory=lambda: os.environ.get("NECC_MODELO_EMBEDDINGS", "gemini-embedding-001")
    )
    dimension_embeddings: int = 768

    # OCR: "gemini" (visión multimodal) o "tesseract" (local).
    motor_ocr: str = field(default_factory=lambda: os.environ.get("NECC_MOTOR_OCR", "gemini").strip().lower())

    # Notificaciones (módulo de acción). Sin configurar => solo bandeja local.
    slack_webhook_url: str | None = field(default_factory=lambda: os.environ.get("SLACK_WEBHOOK_URL"))
    smtp_host: str | None = field(default_factory=lambda: os.environ.get("SMTP_HOST"))
    smtp_puerto: int = field(default_factory=lambda: int(os.environ.get("SMTP_PORT", "587")))
    smtp_usuario: str | None = field(default_factory=lambda: os.environ.get("SMTP_USER"))
    smtp_clave: str | None = field(default_factory=lambda: os.environ.get("SMTP_PASSWORD"))
    smtp_remitente: str = field(default_factory=lambda: os.environ.get("SMTP_FROM", "necc-bot@localhost"))

    # Demo pública: la API queda de solo lectura (salvo la consulta en lenguaje natural).
    demo: bool = field(default_factory=lambda: os.environ.get("NECC_DEMO", "").strip().lower() in ("1", "true"))

    @property
    def inbox(self) -> Path:
        return self.datos / "inbox"

    @property
    def documentos(self) -> Path:
        return self.datos / "documentos"

    @property
    def bandeja_salida(self) -> Path:
        return self.datos / "bandeja_salida"

    @property
    def reportes(self) -> Path:
        return self.datos / "reportes"

    @property
    def base_datos(self) -> Path:
        return self.datos / "necc.db"

    @property
    def ontologia(self) -> Path:
        return self.config_dir / "ontologia.yaml"

    @property
    def responsables(self) -> Path:
        return self.config_dir / "responsables.yaml"

    def asegurar_directorios(self) -> None:
        for d in (self.inbox, self.documentos, self.bandeja_salida, self.reportes):
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def obtener_config() -> Config:
    cfg = Config()
    cfg.asegurar_directorios()
    return cfg
