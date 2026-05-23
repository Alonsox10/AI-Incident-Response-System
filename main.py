from fastapi import FastAPI, HTTPException, Response , Request
from graphs.incidente_graph import app as incident_app
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from loguru import logger
import uuid
app = FastAPI()


class IncidentRequest(BaseModel):
    user_input: str


@app.post("/incident")
def handle_incident(request: IncidentRequest, requests: Request , response: Response):
    try:

        # Busca la nueva seccion en la cooki
        session_id = requests.cookies.get("session_id")

        if not session_id:
            session_id = str(uuid.uuid4())

            response.set_cookie(key="session_id", value=session_id)

        # Prepara el estado inicial con el mensaje del usuario
        initial_state = {
            "messages": [
                HumanMessage(content=request.user_input)
                
            ],
            "category": None,
            "priority": None,
            "possible_causes": None,
            "recommendations": None,
            "current_step": None,
        }
        config = {"configurable":{"thread_id": session_id}}
        result =  incident_app.invoke(initial_state, config=config)
        
        if not result:
            return {
                "error": "No se pudo procesar el incidente"
            }
        return{
            "category": result.get("category"),
            "priority": result.get("priority"),
            "possible_causes": result.get("possible_causes"),
            "recommendations": result.get("recommendations"),
            "current_step": result.get("current_step")
        }
    except Exception as e:
        logger.error(f"Hubo un error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
