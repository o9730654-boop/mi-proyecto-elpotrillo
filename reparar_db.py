import sqlite3
import os

def reparar_forzado():
    # Detecta la carpeta donde está este script para encontrar la DB
    ruta_db = os.path.join(os.path.dirname(__file__), 'PROYECTO ALMA1.db')
    
    if not os.path.exists(ruta_db):
        print(f"❌ No se encontró el archivo en: {ruta_db}")
        return

    try:
        conn = sqlite3.connect(ruta_db)
        cursor = conn.cursor()
        
        # Intentamos agregar la columna
        cursor.execute("ALTER TABLE formulario ADD COLUMN metodo_pago TEXT DEFAULT 'Efectivo'")
        conn.commit()
        print("✅ Columna 'metodo_pago' añadida con éxito.")
        
    except sqlite3.OperationalError as e:
        if "duplicate column name" in str(e):
            print("ℹ️ La columna ya existe, el problema es otro.")
        else:
            print(f"❌ Error de SQLite: {e}")
    finally:
        conn.close()

if __name__ == "__main__":
    reparar_forzado()