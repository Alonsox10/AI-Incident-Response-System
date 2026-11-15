"""
Tests de la autenticación y del cierre del IDOR (hallazgo B6 del plan).

El test central de este archivo es
`test_la_misma_cookie_en_otro_tenant_apunta_a_otro_hilo`: es el criterio de aceptación
de la fase escrito como código. Antes, el `thread_id` del checkpointer **era** el valor
de la cookie `session_id`, así que escribirla a mano con el UUID de otra persona
devolvía su historial completo de incidentes por `GET /conversation`.

Importa que esto se verifique sobre la derivación del `thread_id` y no sobre la firma
de la cookie: la firma impide falsificar conversaciones, pero el aislamiento entre
tenants no depende de ella. Aunque la firma se rompiera, la cookie de otro seguiría
resolviendo a un hilo distinto.
"""
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from service.auth import (
    COOKIE_CONVERSACION,
    Tenant,
    _firmar,
    conversacion_de_cookie,
    generar_api_key,
    hash_api_key,
    thread_id_de,
)
from service.errors import ErrorDeBaseDeDatos, NoAutenticado, SinPermiso

TENANT_A = Tenant(id=1, nombre="acme", rol="user")
TENANT_B = Tenant(id=2, nombre="globex", rol="user")
ADMIN = Tenant(id=3, nombre="soporte", rol="admin")


# ─── Derivación del thread_id: el arreglo del IDOR ───────────────────────────

def test_la_misma_cookie_en_otro_tenant_apunta_a_otro_hilo():
    """
    El criterio de la fase: cambiar la cookie a mano no da acceso a la conversación
    de otro. El `thread_id` incluye el tenant, así que la conversación ajena no es
    inalcanzable por estar protegida: es inalcanzable porque no se puede nombrar.
    """
    conversacion = str(uuid.uuid4())

    assert thread_id_de(TENANT_A, conversacion) != thread_id_de(TENANT_B, conversacion)


def test_el_thread_id_no_contiene_el_valor_que_manda_el_cliente():
    """
    Si el identificador de conversación apareciera dentro del `thread_id`, bastaría
    con reconstruirlo para alcanzar un hilo ajeno.
    """
    conversacion = str(uuid.uuid4())
    thread_id = thread_id_de(TENANT_A, conversacion)

    assert conversacion not in thread_id
    assert len(thread_id) == 64  # sha256 hexadecimal


def test_el_thread_id_es_estable_para_la_misma_pareja():
    """Sin esto la continuación de una conversación abriría un hilo nuevo cada vez."""
    conversacion = str(uuid.uuid4())

    assert thread_id_de(TENANT_A, conversacion) == thread_id_de(TENANT_A, conversacion)


# ─── Firma de la cookie ──────────────────────────────────────────────────────

def test_una_cookie_firmada_se_lee_de_vuelta():
    conversacion = str(uuid.uuid4())
    assert conversacion_de_cookie(_firmar(conversacion)) == conversacion


def test_una_cookie_manipulada_se_descarta():
    """
    Cambiar el identificador invalida la firma. Se descarta en silencio y se empieza
    una conversación nueva: fallar con 400 dejaría al usuario atascado sin forma de
    arreglarlo desde el navegador.
    """
    cookie = _firmar(str(uuid.uuid4()))
    manipulada = f"{uuid.uuid4()}.{cookie.rpartition('.')[2]}"

    assert conversacion_de_cookie(manipulada) is None


def test_una_cookie_sin_firma_se_descarta():
    assert conversacion_de_cookie(str(uuid.uuid4())) is None
    assert conversacion_de_cookie("") is None
    assert conversacion_de_cookie(None) is None


# ─── API keys ────────────────────────────────────────────────────────────────

def test_la_clave_generada_no_es_adivinable_y_se_reconoce():
    clave = generar_api_key()

    assert clave.startswith("iras_")   # reconocible en un log o en un commit
    assert len(clave) > 40
    assert clave != generar_api_key()


def test_el_hash_es_estable_y_no_reversible_a_simple_vista():
    clave = generar_api_key()
    digest = hash_api_key(clave)

    assert digest == hash_api_key(clave)
    assert len(digest) == 64
    assert clave not in digest


# ─── Dependencias de FastAPI ─────────────────────────────────────────────────

async def test_sin_cabecera_no_se_autentica():
    from service.auth import tenant_actual

    with pytest.raises(NoAutenticado):
        await tenant_actual(x_api_key=None)


async def test_una_clave_desconocida_no_se_autentica():
    from service.auth import tenant_actual

    with patch("service.auth._buscar_tenant", AsyncMock(return_value=None)):
        with pytest.raises(NoAutenticado):
            await tenant_actual(x_api_key="iras_inventada")


async def test_una_clave_valida_devuelve_el_tenant():
    from service.auth import tenant_actual

    with patch("service.auth._buscar_tenant", AsyncMock(return_value=TENANT_A)):
        assert await tenant_actual(x_api_key="iras_valida") == TENANT_A


async def test_un_fallo_de_base_no_se_confunde_con_credenciales_invalidas():
    """
    Devolver 401 cuando Postgres está caído mandaría al cliente a revisar su clave
    por un problema que es nuestro. `_buscar_tenant` traduce a `ErrorDeBaseDeDatos`,
    que el handler mapea a 503.
    """
    from service.auth import _buscar_tenant

    pool_roto = AsyncMock(side_effect=Exception("connection refused"))
    with patch("service.auth.get_pool", pool_roto):
        with pytest.raises(ErrorDeBaseDeDatos):
            await _buscar_tenant("iras_cualquiera")


async def test_un_usuario_normal_no_pasa_por_la_puerta_de_admin():
    from service.auth import tenant_admin

    with patch("service.auth._buscar_tenant", AsyncMock(return_value=TENANT_A)):
        with pytest.raises(SinPermiso):
            await tenant_admin(x_api_key="iras_valida")


async def test_un_admin_pasa_por_la_puerta_de_admin():
    from service.auth import tenant_admin

    with patch("service.auth._buscar_tenant", AsyncMock(return_value=ADMIN)):
        assert (await tenant_admin(x_api_key="iras_valida")).es_admin


# ─── Flags de la cookie ──────────────────────────────────────────────────────

def test_la_cookie_sale_con_httponly_y_samesite():
    """
    Los flags que no tenía. `HttpOnly` la vuelve inalcanzable desde JavaScript, así
    que un XSS no se la lleva; `SameSite=Lax` impide que viaje en peticiones
    cross-site de terceros.
    """
    from fastapi import Response

    from service.auth import establecer_cookie

    response = Response()
    establecer_cookie(response, str(uuid.uuid4()))
    cabecera = response.headers["set-cookie"].lower()

    assert f"{COOKIE_CONVERSACION}=" in cabecera
    assert "httponly" in cabecera
    assert "samesite=lax" in cabecera
