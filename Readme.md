# 🚨 AI Incident Response System

Sistema inteligente de gestión de incidentes construido con **LangGraph**, **FastAPI** y **PostgreSQL**.

Este proyecto implementa un flujo agentic utilizando IA para:

- Analizar incidentes técnicos
- Clasificar prioridades automáticamente
- Generar recomendaciones técnicas
- Utilizar herramientas (`Tools`)
- Mantener memoria conversacional persistente

---

# 🧠 Tecnologías utilizadas

- Python
- FastAPI
- LangGraph
- LangChain
- OpenAI
- PostgreSQL
- Psycopg
- Pydantic
- Loguru

---


# Crear entorno virtual para windows

python -m venv venv
venv\Scripts\activate


# Crear entorno virtual para Linux/Mac
source venv/bin/activate


# Instalar dependencias
pip install -r requirements.txt


# Variables de entorno
Crear un .env en tu proyecto con la API de openai
y tu url de tu postgres


OPENAI_API_KEY=your_openai_api_key

POSTGRES_URL=postgresql://user:password@localhost:5432/database


# Ejecutar proyecto

uvicorn main:app --reload

# ✨ Características principales

✅ Clasificación automática de incidentes  
✅ Priorización inteligente  
✅ Recomendaciones técnicas generadas por IA  
✅ Persistencia de memoria con PostgreSQL  
✅ Arquitectura basada en agentes  
✅ Tool Calling con LangGraph  
✅ Workflow Agentic  
✅ Sistema modular y escalable  

---

# 🏗️ Arquitectura del sistema

```text
Usuario
   ↓
FastAPI API
   ↓
LangGraph Workflow
   ↓
Classifier Agent
   ↓
ToolNode
   ↓
PostgreSQL

