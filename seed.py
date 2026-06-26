"""
Script de inicialización de datos para el sistema RAG.

Ejecutar una sola vez después de levantar el contenedor o configurar
el entorno por primera vez. Es seguro ejecutarlo varias veces
(operación idempotente: no duplica datos existentes).

Uso:
    python seed.py
"""
import sys
import os
import io

# Agrega la raíz del proyecto al path para importar módulos internos
sys.path.insert(0, os.path.dirname(__file__))

from dotenv import load_dotenv
load_dotenv(override=True)

from loguru import logger
from pypdf import PdfReader
from database.db import get_connection
from database.vector_db import (
    initialize_vector_tables,
    store_document_chunk,
    store_incident_embedding,
)
from service.embedding_service import get_embedding, chunk_text


# ─── Configuración ─────────────────────────────────────────────────────────────

# Carpeta donde se colocan los PDFs de conocimiento
CARPETA_KNOWLEDGE = os.path.join("docs", "knowledge")

# Incidentes históricos resueltos para poblar incident_embeddings
INCIDENTES_HISTORICOS = [
    {
        "description": "Toda la oficina perdió acceso a Internet. Los equipos tenían IP local pero sin respuesta a ping externo.",
        "category": "Redes",
        "priority": "Alta",
        "resolution": "Se identificó caída del enlace WAN del ISP. Se reinició el router perimetral (30s), se contactó al ISP con ticket de soporte y se activó el enlace 4G de respaldo. Servicio restaurado en 45 minutos.",
    },
    {
        "description": "Usuarios remotos no podían conectarse a la VPN corporativa. El cliente mostraba error de autenticación.",
        "category": "Redes",
        "priority": "Media",
        "resolution": "El certificado del cliente VPN había vencido. Se renovó el certificado, se verificaron credenciales en Active Directory y se confirmó que los puertos UDP 500 y 4500 estaban abiertos. VPN restaurada en 20 minutos.",
    },
    {
        "description": "Se detectaron inicios de sesión desde ubicaciones inusuales en la cuenta de un empleado de finanzas.",
        "category": "Seguridad",
        "priority": "Alta",
        "resolution": "Se deshabilitó la cuenta en Active Directory, se revocaron todos los tokens activos y se forzó restablecimiento de contraseña con MFA obligatorio. Revisión en SIEM sin exfiltración de datos detectada.",
    },
    {
        "description": "Archivos cifrados con extensión desconocida en tres estaciones de trabajo. Nota de rescate visible en el escritorio.",
        "category": "Seguridad",
        "priority": "Alta",
        "resolution": "Se aislaron los equipos desconectando el cable de red. Se restauró desde el último backup limpio, se aplicó el parche MS17-010 y se cambiaron todas las contraseñas del dominio. Incidente reportado al CERT.",
    },
    {
        "description": "El servidor de base de datos PostgreSQL no respondía. Los servicios backend generaban timeouts de conexión.",
        "category": "Infraestructura",
        "priority": "Alta",
        "resolution": "El disco llegó al 100% por acumulación de logs de auditoría. Se liberó espacio borrando logs de más de 30 días, se movieron backups al NAS y se configuró alerta al 80%. Servicio restaurado en 15 minutos.",
    },
    {
        "description": "CPU del servidor de aplicaciones sostenida al 98% durante 2 horas. Servicios con alta latencia.",
        "category": "Infraestructura",
        "priority": "Media",
        "resolution": "Un proceso de reindexación se ejecutó fuera de horario. Se reprogramó para las 2:00 AM, se aplicó renice para bajar su prioridad y la carga se normalizó en 10 minutos.",
    },
    {
        "description": "Usuarios reciben error HTTP 500 al acceder al portal web corporativo tras un deployment en producción.",
        "category": "Error backend",
        "priority": "Alta",
        "resolution": "El deployment introdujo una variable de entorno incorrecta en la cadena de conexión a la BD. Se hizo rollback en 5 minutos y se corrigió la variable en el pipeline de CI/CD.",
    },
]


# ─── Helpers de idempotencia ──────────────────────────────────────────────────

def _fuente_ya_existe(source: str) -> bool:
    """Retorna True si ya hay chunks de esa fuente en knowledge_base."""
    connection = get_connection()
    try:
        row = connection.execute(
            "SELECT COUNT(*) FROM knowledge_base WHERE source = %s", (source,)
        ).fetchone()
        return row[0] > 0
    finally:
        connection.close()


def _incidentes_ya_cargados() -> bool:
    """Retorna True si incident_embeddings ya tiene datos."""
    connection = get_connection()
    try:
        row = connection.execute("SELECT COUNT(*) FROM incident_embeddings").fetchone()
        return row[0] > 0
    finally:
        connection.close()


# ─── Ingesta de PDFs ──────────────────────────────────────────────────────────

def ingestar_pdf(ruta: str) -> None:
    """Lee un PDF, lo chunkea, lo vectoriza y lo almacena en knowledge_base."""
    source_name = os.path.basename(ruta)

    if _fuente_ya_existe(source_name):
        print(f"  [omitido] '{source_name}' ya está en la base de conocimiento.")
        return

    print(f"  Procesando '{source_name}'...")

    with open(ruta, "rb") as f:
        reader = PdfReader(io.BytesIO(f.read()))

    paginas = [
        p.extract_text().strip()
        for p in reader.pages
        if p.extract_text() and p.extract_text().strip()
    ]

    if not paginas:
        print(f"  [error] No se pudo extraer texto de '{source_name}'. ¿Es un PDF escaneado?")
        return

    texto_completo = "\n\n".join(paginas)
    chunks = chunk_text(texto_completo)

    for i, chunk in enumerate(chunks):
        embedding = get_embedding(chunk)
        store_document_chunk(content=chunk, embedding=embedding, source=source_name, chunk_index=i)
        print(f"    [{i + 1}/{len(chunks)}] fragmento vectorizado", end="\r")

    print(f"  [ok] '{source_name}' -> {len(paginas)} paginas, {len(chunks)} fragmentos almacenados.")


def ingestar_todos_los_pdfs() -> None:
    """Busca todos los PDFs en docs/knowledge/ y los ingesta."""
    if not os.path.isdir(CARPETA_KNOWLEDGE):
        print(f"  [aviso] Carpeta '{CARPETA_KNOWLEDGE}' no encontrada. Créala y coloca los PDFs ahí.")
        return

    pdfs = [
        os.path.join(CARPETA_KNOWLEDGE, f)
        for f in os.listdir(CARPETA_KNOWLEDGE)
        if f.lower().endswith(".pdf")
    ]

    if not pdfs:
        print(f"  [aviso] No hay PDFs en '{CARPETA_KNOWLEDGE}'.")
        return

    for pdf in pdfs:
        ingestar_pdf(pdf)


# ─── Ingesta de incidentes históricos ─────────────────────────────────────────

def ingestar_incidentes_historicos() -> None:
    """Carga los incidentes históricos en incident_embeddings."""
    if _incidentes_ya_cargados():
        print("  [omitido] Los incidentes históricos ya están cargados.")
        return

    print(f"  Cargando {len(INCIDENTES_HISTORICOS)} incidentes históricos...")

    for i, inc in enumerate(INCIDENTES_HISTORICOS):
        embedding = get_embedding(inc["description"])
        store_incident_embedding(
            description=inc["description"],
            category=inc["category"],
            priority=inc["priority"],
            resolution=inc["resolution"],
            embedding=embedding,
        )
        print(f"    [{i + 1}/{len(INCIDENTES_HISTORICOS)}] '{inc['description'][:60]}...'")

    print(f"  [ok] {len(INCIDENTES_HISTORICOS)} incidentes históricos almacenados.")


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    print("\n========================================")
    print("   Seed — Sistema de Respuesta a Incidentes")
    print("========================================\n")

    print("[1/3] Inicializando tablas vectoriales...")
    initialize_vector_tables()
    print("  [ok] Tablas listas.\n")

    print("[2/3] Ingestando PDFs de knowledge base...")
    ingestar_todos_los_pdfs()
    print()

    print("[3/3] Cargando incidentes históricos...")
    ingestar_incidentes_historicos()

    print("\n========================================")
    print("   Seed completado correctamente.")
    print("========================================\n")


if __name__ == "__main__":
    main()
