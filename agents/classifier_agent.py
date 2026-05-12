from langgraph.graph import MessagesState
from models.llm import llm_bind_tools
from loguru import logger
from langchain_core.messages import SystemMessage


with open("prompts/classify_agent.md", "r") as f:
    prompt = f.read()


async def classify_agent(state: MessagesState):
    try:

        messages = [
                SystemMessage(content=prompt) + state["messages"]
        ]

        response = await llm_bind_tools.ainvoke(messages)
        
        return {
            "messages": [response]
        }
    
    except Exception as e:
        logger.error(f"Error en el agente de clasificación: {e}")
        raise ValueError("Ocurrió un error en el agente de clasificación.")


    
