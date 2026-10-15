# Imagen del backend para la demo pública (Cloudflare Container, ver deploy/).
# Incluye la base ya procesada con las 6 notas de ejemplo y corre en modo demo (solo lectura).
FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY config ./config
RUN uv sync --frozen --no-dev

COPY data/necc.db ./data/necc.db
COPY data/documentos ./data/documentos

# La base guarda rutas absolutas de la máquina donde se procesó: se rebasan a /app.
RUN /app/.venv/bin/python - <<'EOF'
import sqlite3
con = sqlite3.connect("data/necc.db")
(ruta,) = con.execute("SELECT ruta FROM documentos LIMIT 1").fetchone()
anterior = ruta[: ruta.index("/data/documentos/")]
for tabla, columnas in {"documentos": ["ruta"], "acciones": ["destinatario", "cuerpo", "detalle"]}.items():
    for columna in columnas:
        con.execute(f"UPDATE {tabla} SET {columna} = replace({columna}, ?, '/app')", (anterior,))
con.commit()
EOF

ENV NECC_DEMO=1 PATH=/app/.venv/bin:$PATH
EXPOSE 8000
CMD ["necc", "ui", "--host", "0.0.0.0", "--puerto", "8000"]
