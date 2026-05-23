# 🚨 AI Incident Response System

Sistema inteligente de gestión de incidentes construido con **LangGraph**, **FastAPI** y **PostgreSQL**.

Este proyecto implementa un flujo agentic utilizando IA para:

- Analizar incidentes técnicos
- Clasificar prioridades automáticamente
- Generar recomendaciones técnicas
- Utilizar herramientas (`Tools`)
- Mantener memoria conversacional persistente

---

# 🧠 Arquitectura del Sistema

El sistema utiliza una arquitectura multi-agente basada en workflows dirigidos por estado (`state-driven workflows`).

## Agentes del sistema

### 🔹 Orchestrator Agent
Responsable de coordinar el flujo completo del sistema y decidir qué agente debe ejecutarse según el estado actual del workflow.

### 🔹 Classifier Agent
Clasifica incidentes y determina:
- categoría
- prioridad
- posibles causas

### 🔹 Recommendation Agent
Genera recomendaciones técnicas basadas en la clasificación del incidente.

### 🔹 Tools Node
Ejecuta acciones externas:
- búsqueda de incidentes similares
- inserción de incidentes en PostgreSQL

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

# 🧩 Características

- ✅ Arquitectura multi-agente
- ✅ Orquestación dinámica
- ✅ Structured Outputs
- ✅ State-driven workflows
- ✅ Tool Calling
- ✅ Persistencia con PostgreSQL
- ✅ Memory checkpointing
- ✅ Routing dinámico
- ✅ Agentes especializados

---

# 📂 Estructura del proyecto

project/
│
├── agents/
│   ├── orchestrator_agent.py
│   ├── classifier_agent.py
│   └── recommendation_agent.py
│
├── graphs/
│   ├── workflow.py
│   └── router.py
│
├── prompts/
│   ├── orchestrator.md
│   ├── classifier_agent.md
│   └── recommendation_agent.md
│
├── schemas/
│   └── models.py
│
├── state/
│   └── state.py
│
├── tools/
│   └── incidente_tools.py
│
├── database/
│   └── db.py
│
├── main.py
├── requirements.txt
└── README.md


START
↓
Orchestrator
↓
Classifier Agent
↓
Orchestrator
↓
Recommendation Agent
↓
Orchestrator
↓
Tools Node
↓
END

