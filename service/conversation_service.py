import uuid
from database.db import get_connection

# Función para crear una nueva conversación y devolver su ID
def create_conversation():

    connection = get_connection()
    cursor = connection.cursor()

    try:

        # Genera un UUID único
        conversation_id = str(uuid.uuid4())

        query = """
        INSERT INTO conversations (id)
        VALUES (%s)
        """
        cursor.execute(query, (conversation_id,))
        connection.commit()

        return conversation_id

    except Exception as e:
        raise ValueError(f"Error al crear conversación: {e}")

    finally:
        cursor.close()
        connection.close()

# Función para obtener el ID de la última conversación creada
def get_latest_conversation():

    connection = get_connection()
    cursor = connection.cursor()

    try:
        query = """
        SELECT id
        FROM conversations
        ORDER BY created_at DESC
        LIMIT 1
        """
        cursor.execute(query)
        result = cursor.fetchone()

        if result:
            return result[0]

        return None

    except Exception as e:
        raise ValueError(f"Error al obtener conversación: {e}")

    finally:
        cursor.close()
        connection.close()