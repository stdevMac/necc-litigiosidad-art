"""Modo demo pública: la API es de solo lectura salvo la consulta en lenguaje natural."""

import pytest
from fastapi.testclient import TestClient

from necc.config import obtener_config
from necc.m6_visualizacion.api import app


@pytest.fixture
def cliente(tmp_path, monkeypatch):
    """Cliente sobre un directorio de datos temporal (no toca `data/`); `demo` se fija en cada prueba."""

    def crear(demo: bool) -> TestClient:
        monkeypatch.setenv("NECC_DATOS", str(tmp_path))
        monkeypatch.setenv("NECC_DEMO", "1" if demo else "0")
        obtener_config.cache_clear()
        return TestClient(app)

    yield crear
    obtener_config.cache_clear()


def test_demo_bloquea_escrituras_y_permite_lecturas(cliente):
    c = cliente(demo=True)
    assert c.get("/api/config").json() == {"demo": True}

    r = c.post("/api/descubrir")
    assert r.status_code == 403
    assert r.json() == {"detail": "Demo pública de solo lectura: esta acción está deshabilitada."}
    assert c.post("/api/documentos/1/valores/x/aprobar", json={"usuario": "a"}).status_code == 403

    assert c.get("/api/documentos").status_code == 200

    r = c.post("/api/consulta", json={"pregunta": "x" * 501})
    assert r.status_code == 400
    assert "500" in r.json()["detail"]


def test_sin_demo_las_escrituras_funcionan(cliente):
    c = cliente(demo=False)
    assert c.get("/api/config").json() == {"demo": False}
    r = c.post("/api/descubrir")
    assert r.status_code == 200
    assert r.json() == []
