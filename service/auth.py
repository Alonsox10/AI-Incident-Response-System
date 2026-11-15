"""
Autenticación por API key por tenant, y derivación del `thread_id` del checkpointer.

Esto cierra el hallazgo B6 del plan, que eran dos problemas en uno:

1. **Ningún endpoint pedía credenciales.** `/documents/ingest/pdf` era público, así que
   cualquiera podía inyectar contenido arbitrario en la base RAG que el agente usa para
   recomendar: prompt injection persistente contra todos los usuarios.
2. **La cookie `session_id` era el `thread_id` del checkpointer**, sin firma y sin
   `HttpOnly`. Poner a mano el UUID de otro usuario devolvía su historial completo de
   incidentes por `GET /conversation`. Un IDOR directo, sobre contenido que incluye
   cuentas comprometidas y reglas de firewall mal configuradas.

El arreglo del punto 2 **no es firmar la cookie**: es que el `thread_id` deje de ser un
valor que el cliente controla. Ahora se deriva de `tenant_id` + el identificador de
conversación, así que la misma cookie en manos de otro tenant apunta a otro hilo. La
firma HMAC es una segunda capa —impide inventarse conversaciones ajenas dentro del
propio tenant— pero el aislamiento entre tenants no depende de ella.

La firma usa `hmac` de la biblioteca estándar en vez de `itsdangerous`: es una cookie
con un solo campo, y no vale una dependencia más.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import uuid
from dataclasses import dataclass

from fastapi import Header, Request, Response
from loguru import logger

from database.db import get_pool
from service.errors import ErrorDeBaseDeDatos, NoAutenticado, SinPermiso

COOKIE_CONVERSACION = "conversacion"

# Sin secreto no se puede firmar nada. En desarrollo se genera uno efímero para no
# obligar a configurar el entorno; en producción eso invalidaría todas las cookies en
# cada reinicio y con varias réplicas cada una firmaría distinto, así que el arranque
# avisa fuerte. `APP_ENTORNO=produccion` lo convierte en un fallo de arranque.
_SECRETO = os.getenv("SESSION_SECRET")
_ENTORNO = os.getenv("APP_ENTORNO", "desarrollo")

if not _SECRETO:
    if _ENTORNO == "produccion":
        raise RuntimeError(
            "SESSION_SECRET es obligatorio con APP_ENTORNO=produccion: sin él las cookies "
            "se invalidan en cada reinicio y cada réplica firma distinto."
        )
    _SECRETO = secrets.token_urlsafe(32)
    logger.warning(
        "[AUTH] SESSION_SECRET no configurado: se generó uno efímero. Las cookies de "
        "conversación no sobrevivirán a un reinicio. Configúralo antes de desplegar."
    )

# `Secure` exige HTTPS, lo que rompería el desarrollo en http://127.0.0.1. Se activa
# por entorno en vez de dejarlo fijo en un valor que obligue a desactivarlo a mano.
COOKIE_SECURE = _ENTORNO == "produccion"


@dataclass(frozen=True)
class Tenant:
    """Identidad autenticada que hizo la petición."""

    id: int
    nombre: str
    rol: str

    @property
    def es_admin(self) -> bool:
        return self.rol == "admin"


# ─── API keys ────────────────────────────────────────────────────────────────

def hash_api_key(api_key: str) -> str:
    """
    SHA-256 hexadecimal de la clave.

    No es bcrypt ni argon2 a propósito, y la diferencia importa: esos están diseñados
    para ser lentos porque protegen contraseñas elegidas por humanos, que son
    adivinables. Una API key de 32 bytes aleatorios no se adivina por fuerza bruta, y
    un hash lento acá sería un costo fijo en el camino crítico de cada petición.
    """
    return hashlib.sha256(api_key.encode("utf-8")).hexdigest()


def generar_api_key() -> str:
    """Clave nueva, con prefijo para que se reconozca en un log o en un commit."""
    return f"iras_{secrets.token_urlsafe(32)}"


async def _buscar_tenant(api_key: str) -> Tenant | None:
    try:
        pool = await get_pool()
        async with pool.connection() as conexion:
            cur = await conexion.execute(
                "SELECT id, nombre, rol FROM tenants WHERE api_key_hash = %s AND activo",
                (hash_api_key(api_key),),
            )
            fila = await cur.fetchone()
    except Exception as e:
        # Un fallo de base no es un fallo de credenciales: devolver 401 acá mandaría al
        # cliente a revisar su clave cuando el problema es nuestro.
        logger.error(f"[AUTH] No se pudo verificar la credencial: {e}")
        raise ErrorDeBaseDeDatos() from e

    if fila is None:
        return None
    return Tenant(id=fila[0], nombre=fila[1], rol=fila[2])


async def tenant_actual(x_api_key: str | None = Header(default=None)) -> Tenant:
    """Dependencia de FastAPI: exige una API key válida y devuelve el tenant."""
    if not x_api_key:
        raise NoAutenticado("Falta la cabecera X-API-Key.")

    tenant = await _buscar_tenant(x_api_key)
    if tenant is None:
        # No se registra la clave ni un fragmento de ella: un log con credenciales
        # parciales es una credencial parcial filtrada.
        logger.warning("[AUTH] Credencial rechazada")
        raise NoAutenticado("Credenciales ausentes o inválidas.")

    logger.info(f"[AUTH] Autenticado | tenant={tenant.nombre} | rol={tenant.rol}")
    return tenant


async def tenant_admin(x_api_key: str | None = Header(default=None)) -> Tenant:
    """Igual que `tenant_actual`, pero además exige rol de administrador."""
    tenant = await tenant_actual(x_api_key)
    if not tenant.es_admin:
        logger.warning(f"[AUTH] Operación de admin denegada | tenant={tenant.nombre}")
        raise SinPermiso("Esta operación requiere rol de administrador.")
    return tenant


# ─── Cookie de conversación e identificador del hilo ─────────────────────────

def _firmar(valor: str) -> str:
    firma = hmac.new(_SECRETO.encode(), valor.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{valor}.{firma}"


def _verificar(cookie: str) -> str | None:
    """Devuelve el valor si la firma es válida, o None si viene manipulada."""
    valor, _, firma = cookie.rpartition(".")
    if not valor or not firma:
        return None
    esperada = hmac.new(_SECRETO.encode(), valor.encode(), hashlib.sha256).hexdigest()[:32]
    # compare_digest y no `==`: la comparación normal corta en el primer byte distinto,
    # lo que filtra por tiempo cuántos bytes de la firma se acertaron.
    if not hmac.compare_digest(firma, esperada):
        return None
    return valor


def conversacion_de_cookie(cookie: str | None) -> str | None:
    """
    Identificador de conversación de una cookie firmada, o None si no sirve.

    La usan los endpoints que no deben crear nada si no hay conversación previa,
    como el GET del historial: un GET con efectos secundarios es una sorpresa.
    """
    if not cookie:
        return None
    return _verificar(cookie)


def thread_id_de(tenant: Tenant, conversacion_id: str) -> str:
    """
    `thread_id` del checkpointer, derivado de la identidad autenticada.

    Es el corazón del arreglo del IDOR. Antes el `thread_id` **era** el valor de la
    cookie, así que escribirla a mano con el UUID de otra persona abría su hilo. Ahora
    el tenant entra en el hash, de modo que la misma cookie en manos de otro tenant
    resuelve a un `thread_id` distinto: la conversación ajena no es inalcanzable por
    estar protegida, es inalcanzable porque no se puede nombrar.
    """
    return hashlib.sha256(f"{tenant.id}:{conversacion_id}".encode()).hexdigest()


def resolver_conversacion(request: Request, response: Response, tenant: Tenant) -> tuple[str, str]:
    """
    Devuelve `(conversacion_id, thread_id)`, creando la conversación si hace falta.

    Una cookie con firma inválida no es un error del cliente, es una cookie que no
    sirve: se descarta en silencio y se empieza una conversación nueva. Fallar con 400
    dejaría al usuario atascado sin forma de arreglarlo desde el navegador.
    """
    cookie = request.cookies.get(COOKIE_CONVERSACION)
    conversacion_id = _verificar(cookie) if cookie else None

    if conversacion_id is None:
        if cookie:
            logger.warning(f"[AUTH] Cookie de conversación inválida o manipulada | tenant={tenant.nombre}")
        conversacion_id = str(uuid.uuid4())
        establecer_cookie(response, conversacion_id)

    return conversacion_id, thread_id_de(tenant, conversacion_id)


def establecer_cookie(response: Response, conversacion_id: str) -> None:
    """Escribe la cookie firmada con los tres flags que antes no tenía."""
    response.set_cookie(
        key=COOKIE_CONVERSACION,
        value=_firmar(conversacion_id),
        httponly=True,       # inalcanzable desde JavaScript: un XSS no se la lleva
        secure=COOKIE_SECURE,
        samesite="lax",      # no viaja en peticiones cross-site de terceros
        max_age=60 * 60 * 24 * 30,
    )
