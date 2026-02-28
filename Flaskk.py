from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import jwt
import datetime
import os
import psycopg2
from psycopg2.extras import RealDictCursor
from functools import wraps

app = Flask(__name__)
CORS(app)

SECRET_KEY  = os.environ.get('SECRET_KEY', 'tu_super_clave_secreta_12345')
DATABASE_URL = os.environ.get('DATABASE_URL')

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require', cursor_factory=RealDictCursor)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.headers.get('Authorization')
        if not token:
            return jsonify({'message': 'Token de autenticación faltante.'}), 401
        try:
            token = token.split()[1]
            data = jwt.decode(token, SECRET_KEY, algorithms=["HS256"])
            current_user = data['user_id']
        except Exception:
            return jsonify({'message': 'Token inválido o expirado.'}), 401
        return f(current_user, *args, **kwargs)
    return decorated

# ─── RUTAS HTML ───────────────────────────────────────────────────────────────
@app.route('/')
def index():
    return render_template('indexlogin.html')

@app.route('/menu')
def menu_page():
    return render_template('indexmenu.html')

@app.route('/mesas')
def mesas_page():
    return render_template('mesas.html')

@app.route('/reporte')
def reporte_page():
    return render_template('reporte.html.html')

@app.route('/cocina')
def view_cocina():
    return render_template('cocina.html')

@app.route('/reporte-ventas')
def reporte_ventas_page():
    return render_template('reportedeventas.html')

# ─── API: LOGIN ───────────────────────────────────────────────────────────────
@app.route('/api/login', methods=['POST'])
def login():
    data     = request.get_json()
    username = data.get('username')
    password = data.get('password')
    usuarios = {
        "admin":  {"pass": "12345", "rol": "admin"},
        "cocina": {"pass": "1",     "rol": "cocinero"},
        "hoster": {"pass": "2",     "rol": "hoster"},
        "mesero": {"pass": "3",     "rol": "mesero"},
        "cajero": {"pass": "4",     "rol": "cajero"}
    }
    user_data = usuarios.get(username)
    if user_data and user_data['pass'] == password:
        token_payload = {
            'user_id': username,
            'rol': user_data['rol'],
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }
        token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")
        return jsonify({'message': 'Éxito', 'token': token, 'rol': user_data['rol']}), 200
    return jsonify({'message': 'Credenciales incorrectas'}), 401

# ─── API: MENÚ ────────────────────────────────────────────────────────────────
# PostgreSQL convierte nombres de columna a minúsculas.
# Usamos alias explícitos para garantizar los nombres que espera el frontend.
@app.route('/api/menu', methods=['GET'])
def get_menu():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Detectamos los nombres reales de columnas para evitar errores de case
            cur.execute("""
                SELECT column_name 
                FROM information_schema.columns 
                WHERE lower(table_name) = 'menu'
                ORDER BY ordinal_position
            """)
            cols = [r['column_name'] for r in cur.fetchall()]

            nombre_col = next((c for c in cols if c.lower() == 'mnu_nombre_plato'), None)
            desc_col   = next((c for c in cols if c.lower() == 'mnu_descripcion'),  None)
            precio_col = next((c for c in cols if c.lower() == 'mnu_precio'),       None)

            if not nombre_col:
                return jsonify({'message': f'Columnas no encontradas. Disponibles: {cols}'}), 500

            cur.execute(f'''
                SELECT
                    "{nombre_col}" AS "Mnu_nombre_plato",
                    "{desc_col}"   AS "Mnu_descripcion",
                    "{precio_col}" AS "Mnu_precio"
                FROM menu
            ''')
            rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'message': str(e)}), 500
    finally:
        conn.close()

# ─── API: PEDIDOS DE COCINA ───────────────────────────────────────────────────
@app.route('/api/cocina/pedidos', methods=['GET'])
@login_required
def get_pedidos_cocina(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT ticket_id, cliente, producto, cantidad, estado
                FROM formulario
                WHERE estado = 'Pendiente'
                  AND DATE(fecha) = CURRENT_DATE
                ORDER BY ticket_id ASC
            """)
            rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    finally:
        conn.close()

# ─── API: CHECKOUT ────────────────────────────────────────────────────────────
@app.route('/api/checkout', methods=['POST'])
@login_required
def register_sale(current_user):
    data    = request.get_json()
    cliente = data.get('cliente', 'Mostrador')
    metodo  = data.get('metodo_pago', 'Pendiente')
    items   = data.get('items', [])
    ahora   = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT COALESCE(MAX(ticket_id), 0) AS max_id FROM formulario")
            nuevo_ticket = cur.fetchone()['max_id'] + 1
            for item in items:
                cur.execute(
                    """INSERT INTO formulario
                       (cliente, telefono, producto, precio, cantidad, fecha, metodo_pago, estado, ticket_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (cliente, "", item['name'], item['price'], item['qty'],
                     ahora, metodo, 'Pendiente', nuevo_ticket)
                )
        conn.commit()
        return jsonify({'message': 'Venta registrada', 'ticket': nuevo_ticket}), 201
    except Exception as e:
        conn.rollback()
        print(f"ERROR EN BASE DE DATOS: {e}")
        return jsonify({'message': f'Error al guardar: {str(e)}'}), 500
    finally:
        conn.close()

# ─── API: REPORTE DETALLADO ───────────────────────────────────────────────────
@app.route('/api/reporte/detallado', methods=['GET'])
@login_required
def get_reporte_detallado(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT
                    ticket_id,
                    cliente,
                    STRING_AGG(producto || ' (' || cantidad || ')', '<br>' ORDER BY producto) AS productos,
                    SUM(cantidad)          AS total_items,
                    SUM(precio * cantidad) AS gran_total,
                    metodo_pago,
                    MAX(fecha)             AS fecha
                FROM formulario
                WHERE DATE(fecha) = CURRENT_DATE
                GROUP BY ticket_id, cliente, metodo_pago
                ORDER BY ticket_id DESC
            """)
            rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ─── API: CORTE DE CAJA ────────────────────────────────────────────────────────
@app.route('/api/reporte/corte', methods=['GET'])
@login_required
def get_corte_reporte(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT CURRENT_DATE AS hoy")
            fecha_actual = cur.fetchone()['hoy']

            cur.execute("""
                SELECT COALESCE(SUM(precio * cantidad), 0) AS total
                FROM formulario
                WHERE DATE(fecha) = CURRENT_DATE AND metodo_pago = 'Efectivo'
            """)
            efectivo = float(cur.fetchone()['total'])

            cur.execute("""
                SELECT COALESCE(SUM(precio * cantidad), 0) AS total
                FROM formulario
                WHERE DATE(fecha) = CURRENT_DATE AND metodo_pago = 'Tarjeta'
            """)
            tarjeta = float(cur.fetchone()['total'])

        return jsonify({
            'fecha_corte':     str(fecha_actual),
            'ventas_efectivo': efectivo,
            'ventas_tarjeta':  tarjeta,
            'total_general':   efectivo + tarjeta
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ─── API: FINALIZAR TICKET ───────────────────────────────────────────────────
@app.route('/api/cocina/finalizar_ticket/<int:tid>', methods=['POST'])
@login_required
def finalizar_ticket(current_user, tid):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE formulario SET estado = 'Terminado' WHERE ticket_id = %s", (tid,)
            )
        conn.commit()
        return jsonify({'message': f'Ticket #{tid} listo'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ─── API: COBRAR TICKET ───────────────────────────────────────────────────────
@app.route('/api/cobrar/ticket/<int:tid>', methods=['PUT'])
@login_required
def cobrar_ticket_id(current_user, tid):
    data   = request.get_json()
    metodo = data.get('metodo_pago')
    conn   = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE formulario SET metodo_pago = %s WHERE ticket_id = %s", (metodo, tid)
            )
        conn.commit()
        return jsonify({'message': 'Cobro realizado con éxito'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ─── API: NOTIFICACIONES ──────────────────────────────────────────────────────
@app.route('/api/notificaciones/listos', methods=['GET'])
@login_required
def obtener_notificaciones(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT DISTINCT ticket_id, cliente
                FROM formulario
                WHERE estado = 'Terminado'
                  AND DATE(fecha) = CURRENT_DATE
                LIMIT 5
            """)
            rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    finally:
        conn.close()


# ─── RUTA DE DIAGNÓSTICO (temporal) ─────────────────────────────────────────
@app.route('/api/debug/tablas', methods=['GET'])
def debug_tablas():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            # Ver todas las tablas del schema public
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name
            """)
            tablas = [r['table_name'] for r in cur.fetchall()]

            # Ver columnas de la tabla menu (cualquier variante)
            cur.execute("""
                SELECT table_name, column_name 
                FROM information_schema.columns 
                WHERE table_schema = 'public'
                  AND lower(table_name) IN ('menu', 'formulario')
                ORDER BY table_name, ordinal_position
            """)
            columnas = [dict(r) for r in cur.fetchall()]

            # Intentar leer las primeras 2 filas de menu directamente
            muestra = []
            try:
                cur.execute("SELECT * FROM menu LIMIT 2")
                muestra = [dict(r) for r in cur.fetchall()]
            except Exception as e1:
                try:
                    conn.rollback()
                    cur.execute('SELECT * FROM "Menu" LIMIT 2')
                    muestra = [dict(r) for r in cur.fetchall()]
                except Exception as e2:
                    muestra = [f"error minusc: {e1}", f"error mayusc: {e2}"]

        return jsonify({
            'tablas_publicas': tablas,
            'columnas_menu_formulario': columnas,
            'muestra_datos': muestra
        }), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/loaderio-02da15920fabcf6b26e0709c27fafdd9.txt')
def verify_loader_io():
    return "loaderio-02da15920fabcf6b26e0709c27fafdd9"

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)