"""
Tests de la API con el borde de seguridad puesto (Fase 2).

Los de `tests/unit/test_auth.py` verifican las piezas; estos verifican que estén
efectivamente conectadas a los endpoints, que es un fallo distinto y más probable:
una dependencia que se olvida en una ruta deja ese endpoint abierto sin que ninguna
prueba de unidad lo note.

El test que importa es `test_la_cookie_de_otro_tenant_no_abre_su_conversacion`: es el
IDOR del hallazgo B6 reproducido de punta a punta sobre la API real, con la cookie de
un tenant presentada por otro.

El grafo se sustituye por un doble que guarda estado por `thread_id`. Así el test mide
exactamente lo que debe —qué hilo resuelve cada petición— sin LLM, sin Postgres y sin
depender de que el grafo haga su trabajo.
"""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient

import main
from service.auth import COOKIE_CONVERSACION, Tenant, _firmar, thread_id_de

TENANT_A = Tenant(id=1, nombre="acme", rol="user")
TENANT_B = Tenant(id=2, nombre="globex", rol="user")
ADMIN = Tenant(id=3, nombre="soporte", rol="admin")

CONVERSACION = "11111111-1111-1111-1111-111111111111"


class EstadoFalso:
    def __init__(self, values):
        self.values = values


class GrafoFalso:
    """
    Doble del grafo compilado: guarda y devuelve estado por `thread_id`.

    Es la pieza que hace observable el aislamiento: si dos peticiones resuelven al
    mismo hilo, ven el mismo estado, y si resuelven a hilos distintos no se ven.
    """

    def __init__(self):
        self.hilos: dict[str, dict] = {}

    def sembrar(self, thread_id: str, values: dict) -> None:
        self.hilos[thread_id] = values

    async def aget_state(self, config):
        return EstadoFalso(self.hilos.get(config["configurable"]["thread_id"], {}))

    async def ainvoke(self, input_state, config):
        return {
            "category": "Redes",
            "priority": "Alta",
            "possible_causes": [],
            "recommendations": "respuesta",
            "current_step": "recommendation_done",
        }


@pytest.fixture
def grafo():
    falso = GrafoFalso()
    with patch("main.get_app", return_value=falso):
        yield falso


@pytest.fixture
def cliente():
    """
    Cliente de pruebas **sin** ejecutar el lifespan.

    Se construye sin `with`: el context manager dispararía el lifespan, que abre el
    pool y compila el grafo contra el Postgres real. La suite es hermética y debe
    seguir siéndolo.

    `raise_server_exceptions=False` porque Starlette reenvía la excepción después de
    que el handler de `Exception` responde, para que el servidor la registre. Sin esto
    un 500 legítimo haría fallar el test en vez de dejar inspeccionar la respuesta.
    """
    return TestClient(main.app, raise_server_exceptions=False)


def _autenticar_como(tenant: Tenant) -> None:
    """Sustituye la verificación de credenciales, que necesitaría Postgres."""
    from service.auth import tenant_actual, tenant_admin

    async def _actual():
        return tenant

    async def _admin():
        from service.errors import SinPermiso

        if not tenant.es_admin:
            raise SinPermiso("Esta operación requiere rol de administrador.")
        return tenant

    main.app.dependency_overrides[tenant_actual] = _actual
    main.app.dependency_overrides[tenant_admin] = _admin


@pytest.fixture(autouse=True)
def limpiar_overrides():
    yield
    main.app.dependency_overrides.clear()


@pytest.fixture
def auth_encendida():
    """
    Enciende la autenticación, que viene apagada de fábrica.

    Los tests de 401/403 la necesitan: con la bandera en su valor por defecto
    `tenant_actual` devuelve el tenant anónimo y esos endpoints responden 200, que es
    justamente el comportamiento que el repo quiere recién clonado.
    """
    with patch("service.auth.AUTH_HABILITADA", True):
        yield


# ─── Autenticación exigida ───────────────────────────────────────────────────

def test_sin_credencial_el_endpoint_de_incidentes_responde_401(cliente, auth_encendida):
    respuesta = cliente.post("/incident", json={"user_input": "se cayó el servidor"})

    assert respuesta.status_code == 401
    assert respuesta.json()["error"]["codigo"] == "no_autenticado"


def test_sin_credencial_la_ingesta_de_pdf_responde_401(cliente, auth_encendida):
    """Este endpoint era público: cualquiera inyectaba contenido en la base del RAG."""
    respuesta = cliente.post("/documents/ingest/pdf", files={"file": ("x.pdf", b"%PDF-1.4", "application/pdf")})

    assert respuesta.status_code == 401


def test_sin_credencial_el_alta_de_historicos_responde_401(cliente, auth_encendida):
    respuesta = cliente.post(
        "/incidents/historical",
        json={"description": "x", "category": "Redes", "priority": "Alta", "resolution": "y"},
    )

    assert respuesta.status_code == 401


def test_un_usuario_normal_no_puede_ingestar_documentos(cliente):
    _autenticar_como(TENANT_A)

    respuesta = cliente.post(
        "/incidents/historical",
        json={"description": "x", "category": "Redes", "priority": "Alta", "resolution": "y"},
    )

    assert respuesta.status_code == 403
    assert respuesta.json()["error"]["codigo"] == "sin_permiso"


def test_health_y_metrics_siguen_abiertos(cliente):
    """
    A propósito sin autenticación: los consulta el orquestador, no un cliente. Si
    `/health` pidiera credenciales, Kubernetes no podría comprobar el pod.
    """
    assert cliente.get("/health").status_code == 200
    assert cliente.get("/metrics").status_code == 200


# ─── El IDOR, de punta a punta ───────────────────────────────────────────────

def test_el_propio_tenant_si_ve_su_conversacion(cliente, grafo):
    """Control del test siguiente: sin esto, un 'no ve nada' no probaría nada."""
    from langchain_core.messages import HumanMessage

    _autenticar_como(TENANT_A)
    grafo.sembrar(
        thread_id_de(TENANT_A, CONVERSACION),
        {"messages": [HumanMessage(content="hola")]},
    )

    cliente.cookies.set(COOKIE_CONVERSACION, _firmar(CONVERSACION))
    respuesta = cliente.get("/conversation")

    assert respuesta.status_code == 200
    assert respuesta.json()["messages"] == [{"role": "usuario", "content": "hola"}]


def test_la_cookie_de_otro_tenant_no_abre_su_conversacion(cliente, grafo):
    """
    El hallazgo B6. Se presenta la cookie **válida y bien firmada** del tenant A
    autenticándose como el tenant B: antes eso devolvía el historial de A, porque el
    `thread_id` era el valor de la cookie. Ahora el hilo se deriva de la identidad,
    así que la misma cookie resuelve a otro hilo, que está vacío.
    """
    from langchain_core.messages import HumanMessage

    grafo.sembrar(
        thread_id_de(TENANT_A, CONVERSACION),
        {"messages": [HumanMessage(content="nuestra VPN usa la clave maestra 1234")]},
    )

    _autenticar_como(TENANT_B)
    cliente.cookies.set(COOKIE_CONVERSACION, _firmar(CONVERSACION))
    respuesta = cliente.get("/conversation")

    assert respuesta.status_code == 200
    assert respuesta.json()["messages"] == []


def test_una_cookie_manipulada_no_alcanza_ninguna_conversacion(cliente, grafo):
    """Dentro del mismo tenant, inventarse un identificador requiere la firma."""
    from langchain_core.messages import HumanMessage

    grafo.sembrar(thread_id_de(TENANT_A, CONVERSACION), {"messages": [HumanMessage(content="secreto")]})
    _autenticar_como(TENANT_A)

    # Identificador correcto, firma de otra cosa.
    cliente.cookies.set(COOKIE_CONVERSACION, f"{CONVERSACION}.{'0' * 32}")
    respuesta = cliente.get("/conversation")

    assert respuesta.json()["messages"] == []


def test_el_get_de_conversacion_no_crea_conversacion(cliente, grafo):
    """Un GET no debe tener efectos: sin cookie válida no emite una nueva."""
    _autenticar_como(TENANT_A)

    respuesta = cliente.get("/conversation")

    assert respuesta.json() == {"conversacion_id": None, "messages": []}
    assert "set-cookie" not in respuesta.headers


# ─── Cookie emitida por el endpoint de incidentes ────────────────────────────

def test_el_incidente_emite_la_cookie_con_los_flags(cliente, grafo):
    _autenticar_como(TENANT_A)

    respuesta = cliente.post("/incident", json={"user_input": "se cayó el enlace de la sucursal"})

    assert respuesta.status_code == 200
    cabecera = respuesta.headers["set-cookie"]
    assert "HttpOnly" in cabecera
    assert "SameSite=lax" in cabecera.replace("samesite", "SameSite")

    # La cookie lleva el identificador MÁS su firma, no el identificador a secas.
    valor = cabecera.split(";")[0].split("=", 1)[1]
    conversacion_id = respuesta.json()["conversacion_id"]
    assert valor != conversacion_id
    assert valor == f"{conversacion_id}.{valor.rpartition('.')[2]}"


# ─── Traducción de errores en la respuesta HTTP ──────────────────────────────

class RateLimitError(Exception):
    """Doble del error del SDK de OpenAI; `service/errors.py` lo reconoce por nombre."""


def _grafo_que_falla(causa: Exception):
    """Grafo cuyo `ainvoke` falla como falla un agente: envolviendo con `from e`."""
    from service.errors import ErrorDeRecomendacion

    class GrafoRoto(GrafoFalso):
        async def ainvoke(self, input_state, config):
            try:
                raise causa
            except Exception as e:
                raise ErrorDeRecomendacion("Ocurrió un error en el agente de recomendación.") from e

    return GrafoRoto()


def test_un_429_del_proveedor_llega_al_cliente_como_503_con_retry_after(cliente):
    """
    El criterio de aceptación de la fase, de punta a punta. Antes esto salía como
    500 con `detail` = el texto de la excepción, así que el cliente no tenía forma
    de distinguir "tu petición está mal" de "reintenta en 10 segundos".
    """
    _autenticar_como(TENANT_A)

    with patch("main.get_app", return_value=_grafo_que_falla(RateLimitError("429 rate_limit_exceeded"))):
        respuesta = cliente.post("/incident", json={"user_input": "se cayó el servidor"})

    assert respuesta.status_code == 503
    assert respuesta.headers["Retry-After"] == "10"
    assert respuesta.json()["error"]["codigo"] == "proveedor_no_disponible"


def test_el_error_que_ve_el_cliente_no_filtra_sql_ni_rutas(cliente):
    """
    El otro criterio: nada de texto de excepción, SQL ni rutas del filesystem. Lo que
    viaja es un `error_id` con el que encontrar la cadena completa en el log.
    """
    _autenticar_como(TENANT_A)
    fuga = r'relation "incidents" does not exist — C:\Users\leonr\app\database\db.py:42'

    with patch("main.get_app", return_value=_grafo_que_falla(Exception(fuga))):
        respuesta = cliente.post("/incident", json={"user_input": "se cayó el servidor"})

    cuerpo = respuesta.text
    assert respuesta.status_code == 500
    assert "incidents" not in cuerpo
    assert "db.py" not in cuerpo
    assert "C:\\" not in cuerpo
    assert len(respuesta.json()["error"]["error_id"]) == 12


def test_el_presupuesto_de_tiempo_corta_el_workflow(cliente):
    """
    Los timeouts por llamada no acotan el total: un workflow hace 5-6 llamadas al LLM
    más 3 de embeddings. Sin este tope el cliente espera minutos por algo que ya no va
    a llegar, y la corrutina sigue gastando cuota mientras tanto.
    """
    import asyncio

    _autenticar_como(TENANT_A)

    class GrafoLento(GrafoFalso):
        async def ainvoke(self, input_state, config):
            await asyncio.sleep(5)
            return {}

    with patch("main.get_app", return_value=GrafoLento()), \
         patch("main.GRAFO_PRESUPUESTO_S", 0.1):
        respuesta = cliente.post("/incident", json={"user_input": "se cayó el servidor"})

    assert respuesta.status_code == 503
    assert respuesta.json()["error"]["codigo"] == "presupuesto_agotado"
    assert respuesta.headers["Retry-After"] == "15"


# ─── Modo abierto: el default del repo ───────────────────────────────────────

def test_recien_clonado_el_incidente_funciona_sin_cabeceras(cliente, grafo):
    """
    El comportamiento que define el default: ningún `dependency_overrides`, ninguna
    cabecera, ninguna tabla `tenants` poblada. Quien clone el repo arranca y prueba.
    """
    respuesta = cliente.post("/incident", json={"user_input": "se cayó el enlace de la sucursal"})

    assert respuesta.status_code == 200
    assert respuesta.json()["category"] == "Redes"


def test_recien_clonado_la_ingesta_de_historicos_funciona_sin_cabeceras(cliente):
    """
    El tenant anónimo tiene rol de admin, así que la carga al RAG también está abierta.
    Es la mitad de B6 que la bandera reabre a cambio de poder probar sin configurar: por
    eso `AUTH_HABILITADA=false` es un fallo de arranque con `APP_ENTORNO=produccion`.
    """
    from unittest.mock import AsyncMock

    with patch("main.get_embedding", AsyncMock(return_value=[0.0] * 1536)), \
         patch("main.store_incident_embedding", AsyncMock(return_value=7)):
        respuesta = cliente.post(
            "/incidents/historical",
            json={"description": "x", "category": "Redes", "priority": "Alta", "resolution": "y"},
        )

    assert respuesta.status_code == 200
    assert respuesta.json()["incident_id"] == 7


def test_abierta_dos_navegadores_no_se_ven_la_conversacion(cliente, grafo):
    """
    Lo que la cookie firmada sigue protegiendo sin autenticación: el `thread_id` se
    deriva del tenant anónimo **más** el identificador de conversación, así que dos
    cookies distintas son dos hilos distintos.
    """
    from langchain_core.messages import HumanMessage

    from service.auth import TENANT_ANONIMO

    grafo.sembrar(
        thread_id_de(TENANT_ANONIMO, CONVERSACION),
        {"messages": [HumanMessage(content="lo que reportó el primer navegador")]},
    )

    # Otro navegador: misma instalación abierta, otra conversación.
    otra = "22222222-2222-2222-2222-222222222222"
    cliente.cookies.set(COOKIE_CONVERSACION, _firmar(otra))

    assert cliente.get("/conversation").json()["messages"] == []
