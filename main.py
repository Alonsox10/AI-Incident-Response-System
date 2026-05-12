from fastapi import FastAPI, HTTPException
from graphs.incidente_graph import app as incident_app
from pydantic import BaseModel

app = FastAPI()

class IncidentRequest(BaseModel):
    user_input: str


@app.post("/incident")
async def handle_incident(request: IncidentRequest):
    try:

        initial_state = {
            "user_input": request.user_input
        }
        result = await incident_app.ainvoke(initial_state)
        return result
    except Exception as e:
        return {"error": str(e)}
        