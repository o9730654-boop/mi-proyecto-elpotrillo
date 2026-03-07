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

SECRET_KEY   = os.environ.get('SECRET_KEY', 'tu_super_clave_secreta_12345')
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

# Crea las tablas de inventario y recetas si no existen
def init_db():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                CREATE TABLE IF NOT EXISTS inventario (
                    id         SERIAL PRIMARY KEY,
                    nombre     VARCHAR(100) NOT NULL,
                    categoria  VARCHAR(50)  DEFAULT 'Otros',
                    cantidad   NUMERIC(10,2) DEFAULT 0,
                    unidad     VARCHAR(30)  DEFAULT 'piezas',
                    stock_min  NUMERIC(10,2) DEFAULT 5
                )
            """)
            cur.execute("""
                CREATE TABLE IF NOT EXISTS recetas (
                    id              SERIAL PRIMARY KEY,
                    nombre_platillo VARCHAR(150) NOT NULL,
                    id_ingrediente  INTEGER REFERENCES inventario(id) ON DELETE CASCADE,
                    cantidad_usar   NUMERIC(10,2) NOT NULL
                )
            """)
        conn.commit()
    except Exception as e:
        conn.rollback()
        print(f"init_db error: {e}")
    finally:
        conn.close()

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

@app.route('/inventario')
def inventario_page():
    return render_template('inventario.html')

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
@app.route('/api/menu', methods=['GET'])
def get_menu():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT column_name FROM information_schema.columns
                WHERE lower(table_name) = 'menu' ORDER BY ordinal_position
            """)
            cols = [r['column_name'] for r in cur.fetchall()]
            nombre_col = next((c for c in cols if c.lower() == 'mnu_nombre_plato'), None)
            desc_col   = next((c for c in cols if c.lower() == 'mnu_descripcion'),  None)
            precio_col = next((c for c in cols if c.lower() == 'mnu_precio'),       None)
            if not nombre_col:
                return jsonify({'message': f'Columnas no encontradas: {cols}'}), 500
            cur.execute(f'''
                SELECT "{nombre_col}" AS "Mnu_nombre_plato",
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
                WHERE estado = 'Pendiente' AND DATE(fecha) = CURRENT_DATE
                ORDER BY ticket_id ASC
            """)
            rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    finally:
        conn.close()

# ─── API: CHECKOUT con descuento automático de inventario ─────────────────────
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
                # Guardar en formulario
                cur.execute(
                    """INSERT INTO formulario
                       (cliente, telefono, producto, precio, cantidad, fecha, metodo_pago, estado, ticket_id)
                       VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)""",
                    (cliente, "", item['name'], item['price'], item['qty'],
                     ahora, metodo, 'Pendiente', nuevo_ticket)
                )

                # Descontar ingredientes del inventario según receta
                cur.execute("""
                    SELECT r.id_ingrediente, r.cantidad_usar, i.cantidad
                    FROM recetas r
                    JOIN inventario i ON i.id = r.id_ingrediente
                    WHERE lower(r.nombre_platillo) = lower(%s)
                """, (item['name'],))
                for ing in cur.fetchall():
                    nuevo_stock = max(0, float(ing['cantidad']) - float(ing['cantidad_usar']) * item['qty'])
                    cur.execute(
                        "UPDATE inventario SET cantidad = %s WHERE id = %s",
                        (nuevo_stock, ing['id_ingrediente'])
                    )

        conn.commit()
        return jsonify({'message': 'Venta registrada', 'ticket': nuevo_ticket}), 201
    except Exception as e:
        conn.rollback()
        print(f"ERROR CHECKOUT: {e}")
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
                SELECT ticket_id, cliente,
                    STRING_AGG(producto || ' (' || cantidad || ')', '<br>' ORDER BY producto) AS productos,
                    SUM(cantidad) AS total_items, SUM(precio * cantidad) AS gran_total,
                    metodo_pago, MAX(fecha) AS fecha
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

# ─── API: CORTE DE CAJA ───────────────────────────────────────────────────────
@app.route('/api/reporte/corte', methods=['GET'])
@login_required
def get_corte_reporte(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT CURRENT_DATE AS hoy")
            fecha_actual = cur.fetchone()['hoy']
            cur.execute("""SELECT COALESCE(SUM(precio*cantidad),0) AS total
                FROM formulario WHERE DATE(fecha)=CURRENT_DATE AND metodo_pago='Efectivo'""")
            efectivo = float(cur.fetchone()['total'])
            cur.execute("""SELECT COALESCE(SUM(precio*cantidad),0) AS total
                FROM formulario WHERE DATE(fecha)=CURRENT_DATE AND metodo_pago='Tarjeta'""")
            tarjeta = float(cur.fetchone()['total'])
        return jsonify({'fecha_corte': str(fecha_actual), 'ventas_efectivo': efectivo,
                        'ventas_tarjeta': tarjeta, 'total_general': efectivo + tarjeta}), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ─── API: FINALIZAR / COBRAR TICKET ──────────────────────────────────────────
@app.route('/api/cocina/finalizar_ticket/<int:tid>', methods=['POST'])
@login_required
def finalizar_ticket(current_user, tid):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE formulario SET estado='Terminado' WHERE ticket_id=%s", (tid,))
        conn.commit()
        return jsonify({'message': f'Ticket #{tid} listo'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/cobrar/ticket/<int:tid>', methods=['PUT'])
@login_required
def cobrar_ticket_id(current_user, tid):
    data = request.get_json()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE formulario SET metodo_pago=%s WHERE ticket_id=%s",
                        (data.get('metodo_pago'), tid))
        conn.commit()
        return jsonify({'message': 'Cobro realizado'}), 200
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
            cur.execute("""SELECT DISTINCT ticket_id, cliente FROM formulario
                WHERE estado='Terminado' AND DATE(fecha)=CURRENT_DATE LIMIT 5""")
            rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    finally:
        conn.close()

# ─── API: INVENTARIO ──────────────────────────────────────────────────────────
@app.route('/api/inventario', methods=['GET'])
@login_required
def get_inventario(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT * FROM inventario ORDER BY categoria, nombre")
            rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/inventario', methods=['POST'])
@login_required
def crear_ingrediente(current_user):
    d = request.get_json()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO inventario (nombre, categoria, cantidad, unidad, stock_min)
                VALUES (%s,%s,%s,%s,%s) RETURNING *""",
                (d['nombre'], d.get('categoria','Otros'), d['cantidad'],
                 d.get('unidad','piezas'), d.get('stock_min',5)))
            row = dict(cur.fetchone())
        conn.commit()
        return jsonify(row), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/inventario/<int:iid>', methods=['PUT'])
@login_required
def actualizar_ingrediente(current_user, iid):
    d = request.get_json()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""UPDATE inventario
                SET nombre=%s, categoria=%s, cantidad=%s, unidad=%s, stock_min=%s
                WHERE id=%s RETURNING *""",
                (d['nombre'], d.get('categoria','Otros'), d['cantidad'],
                 d.get('unidad','piezas'), d.get('stock_min',5), iid))
            row = cur.fetchone()
        conn.commit()
        return jsonify(dict(row) if row else {}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/inventario/<int:iid>', methods=['DELETE'])
@login_required
def eliminar_ingrediente(current_user, iid):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM inventario WHERE id=%s", (iid,))
        conn.commit()
        return jsonify({'message': 'Eliminado'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/inventario/<int:iid>/ajustar', methods=['POST'])
@login_required
def ajustar_stock(current_user, iid):
    d    = request.get_json()
    tipo = d.get('tipo')
    cant = float(d.get('cantidad', 0))
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            if tipo == 'sumar':
                cur.execute("UPDATE inventario SET cantidad=cantidad+%s WHERE id=%s RETURNING cantidad", (cant, iid))
            elif tipo == 'restar':
                cur.execute("UPDATE inventario SET cantidad=GREATEST(0,cantidad-%s) WHERE id=%s RETURNING cantidad", (cant, iid))
            else:
                cur.execute("UPDATE inventario SET cantidad=%s WHERE id=%s RETURNING cantidad", (cant, iid))
            row = cur.fetchone()
        conn.commit()
        return jsonify({'cantidad': float(row['cantidad'])}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ─── API: RECETAS ─────────────────────────────────────────────────────────────
@app.route('/api/recetas', methods=['GET'])
@login_required
def get_recetas(current_user):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""
                SELECT r.id, r.nombre_platillo, r.id_ingrediente,
                       r.cantidad_usar, i.nombre AS ingrediente, i.unidad
                FROM recetas r JOIN inventario i ON i.id = r.id_ingrediente
                ORDER BY r.nombre_platillo, i.nombre
            """)
            rows = cur.fetchall()
        return jsonify([dict(r) for r in rows]), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/recetas', methods=['POST'])
@login_required
def crear_receta(current_user):
    d = request.get_json()
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("""INSERT INTO recetas (nombre_platillo, id_ingrediente, cantidad_usar)
                VALUES (%s,%s,%s) RETURNING *""",
                (d['nombre_platillo'], d['id_ingrediente'], d['cantidad_usar']))
            row = dict(cur.fetchone())
        conn.commit()
        return jsonify(row), 201
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/recetas/<int:rid>', methods=['DELETE'])
@login_required
def eliminar_receta(current_user, rid):
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM recetas WHERE id=%s", (rid,))
        conn.commit()
        return jsonify({'message': 'Eliminado'}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

# ─── DEBUG ────────────────────────────────────────────────────────────────────
@app.route('/api/debug/tablas', methods=['GET'])
def debug_tablas():
    conn = get_db_connection()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT table_name FROM information_schema.tables WHERE table_schema='public' ORDER BY table_name")
            tablas = [r['table_name'] for r in cur.fetchall()]
        return jsonify({'tablas': tablas}), 200
    except Exception as e:
        conn.rollback()
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/loaderio-02da15920fabcf6b26e0709c27fafdd9.txt')
def verify_loader_io():
    return "loaderio-02da15920fabcf6b26e0709c27fafdd9"

if __name__ == '__main__':
    init_db()
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)