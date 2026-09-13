"""
Parseo de docs/knowledge/faqs.md hacia registros listos para vectorizar.

La convención del archivo está documentada en el propio faqs.md:
    ## categoría
    ### pregunta
    Severidad: <valor>
    **Respuesta:**
    <texto hasta el siguiente encabezado>

Es un formato controlado por el equipo, así que el parseo es estructural y exacto:
no usa heurísticas ni LLM. Las secciones de nivel 2 sin preguntas dentro
(por ejemplo la de convención) simplemente no producen registros.
"""
import os
import re
from loguru import logger


RUTA_FAQS = os.path.join("docs", "knowledge", "faqs.md")

_CATEGORIA_RE = re.compile(r"^##\s+(?!#)(.+?)\s*$")
_PREGUNTA_RE = re.compile(r"^###\s+(.+?)\s*$")
_SEVERIDAD_RE = re.compile(r"^Severidad:\s*(.+?)\s*$", re.IGNORECASE)
_RESPUESTA_RE = re.compile(r"^\*\*Respuesta:\*\*\s*$", re.IGNORECASE)


def _nuevo_registro(categoria: str, pregunta: str) -> dict:
    return {
        "category": categoria,
        "question": pregunta,
        "answer": "",
        "metadata": {"severity": None, "source": os.path.basename(RUTA_FAQS)},
        "_lineas_respuesta": [],
    }


def _cerrar_registro(registro: dict) -> dict:
    """Consolida las líneas acumuladas en el campo answer y descarta el buffer temporal."""
    lineas = registro.pop("_lineas_respuesta")
    # La regla horizontal que separa categorías queda dentro del último bloque capturado
    while lineas and lineas[-1].strip() in ("", "---"):
        lineas.pop()
    registro["answer"] = "\n".join(lineas).strip()
    return registro


def parse_faqs(ruta: str = RUTA_FAQS) -> list[dict]:
    """
    Lee el archivo de FAQs y retorna una lista de dicts con category, question,
    answer y metadata. Descarta los bloques sin respuesta redactada.
    """
    try:
        with open(ruta, "r", encoding="utf-8") as f:
            lineas = f.read().splitlines()

        registros = []
        categoria_actual = None
        registro_actual = None
        capturando_respuesta = False

        for linea in lineas:
            match_categoria = _CATEGORIA_RE.match(linea)
            if match_categoria:
                if registro_actual:
                    registros.append(_cerrar_registro(registro_actual))
                    registro_actual = None
                categoria_actual = match_categoria.group(1)
                capturando_respuesta = False
                continue

            match_pregunta = _PREGUNTA_RE.match(linea)
            if match_pregunta:
                if registro_actual:
                    registros.append(_cerrar_registro(registro_actual))
                registro_actual = _nuevo_registro(categoria_actual, match_pregunta.group(1))
                capturando_respuesta = False
                continue

            if registro_actual is None:
                continue

            match_severidad = _SEVERIDAD_RE.match(linea)
            if match_severidad and not capturando_respuesta:
                registro_actual["metadata"]["severity"] = match_severidad.group(1)
                continue

            if _RESPUESTA_RE.match(linea):
                capturando_respuesta = True
                continue

            if capturando_respuesta:
                registro_actual["_lineas_respuesta"].append(linea)

        if registro_actual:
            registros.append(_cerrar_registro(registro_actual))

        validos = [r for r in registros if r["answer"]]
        descartados = len(registros) - len(validos)
        if descartados:
            logger.warning(f"[FAQ-LOADER] {descartados} bloque(s) sin respuesta fueron descartados.")

        logger.info(f"[FAQ-LOADER] {len(validos)} FAQs parseadas desde '{ruta}'.")
        return validos

    except FileNotFoundError:
        logger.error(f"[FAQ-LOADER] No se encontró el archivo de FAQs en '{ruta}'.")
        raise
    except Exception as e:
        logger.error(f"[FAQ-LOADER] Error al parsear el archivo de FAQs: {e}")
        raise
