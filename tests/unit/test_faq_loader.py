"""
Tests unitarios para el parser de docs/knowledge/faqs.md.

`service/faq_loader.py` es un parser puro y determinístico (sin red ni LLM):
recorre el archivo línea por línea siguiendo una convención Markdown documentada
en el propio faqs.md (`##` categoría, `###` pregunta, `Severidad:`, `**Respuesta:**`).
Se testea tanto contra el archivo real (estructura y conteo) como contra
fixtures Markdown mínimas construidas en `tmp_path` para aislar casos borde.
"""
import pytest

from service.faq_loader import parse_faqs


# ---------------------------------------------------------------------------
# Contra el archivo real
# ---------------------------------------------------------------------------

def test_parsea_las_24_faqs_del_archivo_real():
    """El archivo real tiene 24 preguntas documentadas con respuesta."""
    registros = parse_faqs()

    assert len(registros) == 24


def test_todos_los_registros_tienen_la_estructura_esperada():
    """Cada registro debe traer category, question y answer no vacíos, y metadata con severity."""
    registros = parse_faqs()

    for r in registros:
        assert r["category"]
        assert r["question"]
        assert r["answer"]
        assert r["metadata"]["severity"]
        assert r["metadata"]["source"] == "faqs.md"
        assert "_lineas_respuesta" not in r


def test_las_categorias_agrupan_la_cantidad_correcta_de_preguntas():
    """Distribución real de preguntas por categoría según el archivo actual."""
    registros = parse_faqs()

    conteo_por_categoria = {}
    for r in registros:
        conteo_por_categoria[r["category"]] = conteo_por_categoria.get(r["category"], 0) + 1

    assert conteo_por_categoria == {
        "Red y conectividad": 4,
        "Seguridad": 4,
        "Servidores e infraestructura": 4,
        "Active Directory y usuarios": 3,
        "Aplicaciones y software": 4,
        "Equipos de usuario final": 3,
        "Cloud e infraestructura como código": 2,
    }


def test_la_seccion_de_convencion_no_produce_registros():
    """
    '## Convención del archivo' no tiene preguntas (`###`) debajo, solo una lista
    explicativa: no debe generar ningún registro.
    """
    registros = parse_faqs()

    categorias = {r["category"] for r in registros}
    assert "Convención del archivo" not in categorias


def test_la_regla_horizontal_no_queda_dentro_de_la_ultima_respuesta_de_cada_categoria():
    """
    El separador '---' entre categorías cae dentro del bloque de líneas capturado
    para la última pregunta de la categoría anterior; no debe colarse en el answer.
    Esto fue un bug real ya corregido en `_cerrar_registro`.
    """
    registros = parse_faqs()

    ultima_pregunta_red = next(
        r for r in registros
        if r["question"] == "¿Cómo soluciono que la VPN corporativa no conecte?"
    )

    assert "---" not in ultima_pregunta_red["answer"]
    assert not ultima_pregunta_red["answer"].endswith("\n")


# ---------------------------------------------------------------------------
# Casos borde con fixtures Markdown mínimas
# ---------------------------------------------------------------------------

def _escribir_faq_md(tmp_path, contenido):
    ruta = tmp_path / "faqs.md"
    ruta.write_text(contenido, encoding="utf-8")
    return str(ruta)


def test_bloque_sin_marcador_de_respuesta_se_descarta(tmp_path):
    """Una pregunta sin '**Respuesta:**' no debe producir un registro."""
    contenido = """\
## Categoría X

### ¿Pregunta sin respuesta?

Severidad: Baja

Este texto no cuenta como respuesta porque no hay marcador.
"""
    ruta = _escribir_faq_md(tmp_path, contenido)

    registros = parse_faqs(ruta)

    assert registros == []


def test_bloque_con_marcador_pero_sin_texto_se_descarta(tmp_path):
    """'**Respuesta:**' presente pero sin líneas de contenido debajo también se descarta."""
    contenido = """\
## Categoría X

### ¿Pregunta con respuesta vacía?

Severidad: Baja

**Respuesta:**

### ¿Otra pregunta con respuesta real?

Severidad: Media

**Respuesta:**

Esta sí tiene contenido.
"""
    ruta = _escribir_faq_md(tmp_path, contenido)

    registros = parse_faqs(ruta)

    assert len(registros) == 1
    assert registros[0]["question"] == "¿Otra pregunta con respuesta real?"


def test_mezcla_de_bloques_validos_e_invalidos_conserva_solo_los_validos(tmp_path):
    """Un archivo con preguntas válidas e inválidas intercaladas solo debe devolver las válidas."""
    contenido = """\
## Categoría A

### ¿Pregunta válida uno?

Severidad: Alta

**Respuesta:**

Respuesta uno.

### ¿Pregunta inválida sin respuesta?

Severidad: Baja

---

## Categoría B

### ¿Pregunta válida dos?

Severidad: Media

**Respuesta:**

Respuesta dos.
Segunda línea de la respuesta dos.
"""
    ruta = _escribir_faq_md(tmp_path, contenido)

    registros = parse_faqs(ruta)

    assert len(registros) == 2
    assert registros[0]["question"] == "¿Pregunta válida uno?"
    assert registros[0]["answer"] == "Respuesta uno."
    assert registros[1]["category"] == "Categoría B"
    assert registros[1]["answer"] == "Respuesta dos.\nSegunda línea de la respuesta dos."


def test_regla_horizontal_entre_categorias_no_se_filtra_en_fixture_minima(tmp_path):
    """Réplica mínima del bug real: el '---' que separa categorías no debe quedar en el answer."""
    contenido = """\
## Categoría A

### ¿Última pregunta de la categoría A?

Severidad: Alta

**Respuesta:**

Texto de la respuesta.

---

## Categoría B

### ¿Primera pregunta de la categoría B?

Severidad: Media

**Respuesta:**

Otra respuesta.
"""
    ruta = _escribir_faq_md(tmp_path, contenido)

    registros = parse_faqs(ruta)

    assert registros[0]["answer"] == "Texto de la respuesta."
    assert "---" not in registros[0]["answer"]


def test_severidad_declarada_dentro_del_texto_de_la_respuesta_no_se_reinterpreta(tmp_path):
    """
    Una línea 'Severidad:' que aparece DESPUÉS de '**Respuesta:**' es parte del
    contenido de la respuesta, no debe sobreescribir metadata['severity'].
    """
    contenido = """\
## Categoría A

### ¿Pregunta con severidad mencionada en la respuesta?

Severidad: Alta

**Respuesta:**

Nota interna: Severidad: Baja en casos excepcionales.
"""
    ruta = _escribir_faq_md(tmp_path, contenido)

    registros = parse_faqs(ruta)

    assert len(registros) == 1
    assert registros[0]["metadata"]["severity"] == "Alta"
    assert "Severidad: Baja" in registros[0]["answer"]


def test_archivo_inexistente_propaga_file_not_found_error(tmp_path):
    """Un path inexistente debe propagar FileNotFoundError, no fallar silenciosamente."""
    ruta_inexistente = str(tmp_path / "no_existe.md")

    with pytest.raises(FileNotFoundError):
        parse_faqs(ruta_inexistente)
