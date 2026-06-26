from fastapi import FastAPI, HTTPException, Response, Request, UploadFile, File, Form
from graphs.incidente_graph import app as incident_app
from pydantic import BaseModel
from langchain_core.messages import HumanMessage, AIMessage
from loguru import logger
from service.embedding_service import get_embedding, chunk_text
from database.vector_db import store_document_chunk, store_incident_embedding
from pypdf import PdfReader
import io
import uuid

app = FastAPI()


# ─── Modelos de request / response ───────────────────────────────────────────

class IncidentRequest(BaseModel):
    user_input: str


class HistoricalIncidentRequest(BaseModel):
    description: str
    category: str
    priority: str
    resolution: str


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _get_config(session_id: str) -> dict:
    return {"configurable": {"thread_id": session_id}}


def _ensure_session(requests: Request, response: Response) -> str:
    """Retorna el session_id existente o crea uno nuevo y lo guarda en cookie."""
    session_id = requests.cookies.get("session_id")
    if not session_id:
        session_id = str(uuid.uuid4())
        response.set_cookie(key="session_id", value=session_id)
    return session_id


# ─── Endpoint de incidentes ───────────────────────────────────────────────────

@app.post("/incident")
def handle_incident(request: IncidentRequest, requests: Request, response: Response):
    try:
        session_id = _ensure_session(requests, response)
        config = _get_config(session_id)

        # Detectar si ya existe conversación previa para esta sesión
        estado_actual = incident_app.get_state(config)
        es_nueva_conversacion = not estado_actual.values

        if es_nueva_conversacion:
            # Primera vez: estado completo desde cero
            input_state = {
                "messages": [HumanMessage(content=request.user_input)],
                "category": None,
                "priority": None,
                "possible_causes": None,
                "recommendations": None,
                "current_step": None,
            }
        else:
            # Conversación existente: solo añade el nuevo mensaje al historial acumulado.
            # LangGraph aplica el reducer add_messages, que AGREGA (no reemplaza) el
            # nuevo HumanMessage a los mensajes ya guardados en el checkpoint.
            # Se reinicia current_step para que el orquestador vuelva a clasificar.
            input_state = {
                "messages": [HumanMessage(content=request.user_input)],
                "current_step": None,
            }

        result = incident_app.invoke(input_state, config=config)

        if not result:
            return {"error": "No se pudo procesar el incidente"}

        return {
            "session_id": session_id,
            "nueva_conversacion": es_nueva_conversacion,
            "category": result.get("category"),
            "priority": result.get("priority"),
            "possible_causes": result.get("possible_causes"),
            "recommendations": result.get("recommendations"),
            "current_step": result.get("current_step"),
        }
    except Exception as e:
        logger.error(f"Hubo un error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Endpoint de historial de conversación ────────────────────────────────────

@app.get("/conversation")
def get_conversation(requests: Request):
    """
    Retorna el historial de mensajes de la sesión actual.
    Solo muestra mensajes del usuario y respuestas finales del agente (con contenido).
    """
    session_id = requests.cookies.get("session_id")
    if not session_id:
        return {"session_id": None, "messages": []}

    config = _get_config(session_id)
    state = incident_app.get_state(config)

    if not state.values:
        return {"session_id": session_id, "messages": []}

    historial = []
    for msg in state.values.get("messages", []):
        if isinstance(msg, HumanMessage) and msg.content:
            historial.append({"role": "usuario", "content": msg.content})
        elif isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            historial.append({"role": "agente", "content": msg.content})

    return {"session_id": session_id, "messages": historial}


# ─── Endpoint para reiniciar conversación ─────────────────────────────────────

@app.delete("/conversation")
def reset_conversation(response: Response):
    """
    Reinicia la conversación generando un nuevo session_id.
    El historial anterior queda en la base de datos pero ya no se usará.
    """
    nuevo_session_id = str(uuid.uuid4())
    response.set_cookie(key="session_id", value=nuevo_session_id)
    return {
        "status": "success",
        "mensaje": "Conversación reiniciada correctamente.",
        "nuevo_session_id": nuevo_session_id,
    }


# ─── Endpoint de ingesta de PDF ───────────────────────────────────────────────

@app.post("/documents/ingest/pdf")
async def ingest_pdf(
    file: UploadFile = File(..., description="Archivo PDF a ingestar"),
    source: str = Form(None, description="Nombre o identificador del documento (opcional)"),
):
    """
    Ingesta un archivo PDF en la base de conocimiento RAG.

    El PDF se lee página por página, el texto extraído se divide en fragmentos
    solapados, cada fragmento se vectoriza con OpenAI text-embedding-3-small
    y se almacena en knowledge_base para que el agente de recomendación
    pueda recuperarlo durante el flujo RAG.

    Form data:
        file   – archivo PDF
        source – identificador opcional (por defecto usa el nombre del archivo)

    Retorna las páginas procesadas y los fragmentos almacenados.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Solo se aceptan archivos PDF.")

    source_name = source or file.filename

    try:
        contenido_bytes = await file.read()
        reader = PdfReader(io.BytesIO(contenido_bytes))

        texto_completo = []
        for pagina in reader.pages:
            texto = pagina.extract_text()
            if texto and texto.strip():
                texto_completo.append(texto.strip())

        if not texto_completo:
            raise HTTPException(status_code=422, detail="No se pudo extraer texto del PDF.")

        texto_unido = "\n\n".join(texto_completo)
        chunks = chunk_text(texto_unido)

        stored = 0
        for i, chunk in enumerate(chunks):
            embedding = get_embedding(chunk)
            store_document_chunk(
                content=chunk,
                embedding=embedding,
                source=source_name,
                chunk_index=i,
            )
            stored += 1

        logger.info(f"PDF '{source_name}' ingestado → {len(reader.pages)} páginas, {stored} fragmentos almacenados.")
        return {
            "status": "success",
            "source": source_name,
            "pages_processed": len(reader.pages),
            "chunks_stored": stored,
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error al ingestar el PDF '{source_name}': {e}")
        raise HTTPException(status_code=500, detail=str(e))


# ─── Endpoint de incidentes históricos ───────────────────────────────────────

@app.post("/incidents/historical")
def add_historical_incident(request: HistoricalIncidentRequest):
    """
    Agrega un incidente previamente resuelto a la base de conocimiento vectorial.

    La descripción del incidente se vectoriza y se almacena en incident_embeddings
    para que el agente de recomendación pueda recuperar resoluciones similares vía RAG.

    Body:
        description – qué ocurrió
        category    – p.ej. "Error backend"
        priority    – p.ej. "Alta"
        resolution  – cómo se resolvió
    """
    try:
        embedding = get_embedding(request.description)
        incident_id = store_incident_embedding(
            description=request.description,
            category=request.category,
            priority=request.priority,
            resolution=request.resolution,
            embedding=embedding,
        )
        logger.info(f"Incidente histórico almacenado con id={incident_id}.")
        return {
            "status": "success",
            "incident_id": incident_id,
        }
    except Exception as e:
        logger.error(f"Error al almacenar el incidente histórico: {e}")
        raise HTTPException(status_code=500, detail=str(e))
