import sqlite3
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, "karlaa.db")

def corregir():
    conn = sqlite3.connect(DB_NAME)
    try:
        # Intentamos agregar la columna directamente al archivo que usa Flask
        conn.execute("ALTER TABLE formulario ADD COLUMN ticket_id INTEGER DEFAULT 0")
        conn.commit()
        print(f"✅ ÉXITO: Columna agregada en {DB_NAME}")
    except sqlite3.OperationalError:
        print("ℹ️ AVISO: La columna ya existe o el archivo está bloqueado.")
    finally:
        conn.close()

if __name__ == "__main__":
    corregir()