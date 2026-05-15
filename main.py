from fastapi import FastAPI, HTTPException
from graphs.incidente_graph import app as incident_app
from pydantic import BaseModel
from langchain_core.messages import HumanMessage
from loguru import logger
from service.conversation_service import create_conversation, get_latest_conversation

app = FastAPI()


class IncidentRequest(BaseModel):
    user_input: str


@app.post("/incident")
def handle_incident(request: IncidentRequest):
    try:

        # Crea una nueva conversación y obtiene su ID
        conversation_id = get_latest_conversation()
        if not conversation_id:
            conversation_id = create_conversation()

        # Prepara el estado inicial con el mensaje del usuario
        initial_state = {
            "messages": [
                HumanMessage(content=request.user_input)
            ]
        }
        config = {"configurable":{"thread_id": conversation_id}}
        result =  incident_app.invoke(initial_state, config=config)
        return {
            "response": result["messages"][-1].content
        }
    except Exception as e:
        logger.error(f"Hubo un error: {e}")
        raise HTTPException(status_code=500, detail=str(e))
