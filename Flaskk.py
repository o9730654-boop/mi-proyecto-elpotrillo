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

SECRET_KEY = os.environ.get('SECRET_KEY', 'tu_super_clave_secreta_12345')
DATABASE_URL = os.environ.get('DATABASE_URL')

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

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require', cursor_factory=RealDictCursor)

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

@app.route('/api/reporte/corte', methods=['GET'])
@login_required
def get_corte_reporte(current_user):
    conn = get_db_connection()
    hoy_sql = "date('now', 'localtime')"
    
    try:
        # Obtenemos la fecha actual para el reporte
        fecha_actual = conn.execute(f"SELECT {hoy_sql}").fetchone()[0]
        
        efectivo = conn.execute(f"SELECT SUM(precio * cantidad) FROM formulario WHERE date(fecha) = {hoy_sql} AND metodo_pago = 'Efectivo'").fetchone()[0] or 0
        tarjeta = conn.execute(f"SELECT SUM(precio * cantidad) FROM formulario WHERE date(fecha) = {hoy_sql} AND metodo_pago = 'Tarjeta'").fetchone()[0] or 0
        
        return jsonify({
            'fecha_corte': fecha_actual, # Esto es lo que lee tu document.getElementById('fecha-corte')
            'ventas_efectivo': float(efectivo),
            'ventas_tarjeta': float(tarjeta),
            'total_general': float(efectivo + tarjeta)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/menu', methods=['GET'])
def get_menu():
    conn = get_db_connection()
    try:
        menu_items = conn.execute('SELECT Mnu_nombre_plato, Mnu_descripcion, Mnu_precio FROM menu').fetchall()
        return jsonify([dict(row) for row in menu_items]), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500
    finally:
     conn.close()

@app.route('/api/cocina/pedidos', methods=['GET'])
@login_required
def get_pedidos_cocina(current_user):
    conn = get_db_connection()
    # Traemos solo los pendientes del día actual
    pedidos = conn.execute("""
        SELECT ticket_id, cliente, producto, cantidad, estado 
        FROM formulario 
        WHERE estado = 'Pendiente' 
          AND DATE(fecha) = DATE('now', 'localtime')
        ORDER BY ticket_id ASC
    """).fetchall()
    conn.close()
    return jsonify([dict(p) for p in pedidos])

@app.route('/api/checkout', methods=['POST'])
@login_required 
def register_sale(current_user):
    data = request.get_json()
    cliente = data.get('cliente', 'Mostrador')
    metodo = data.get('metodo_pago', 'Pendiente') 
    items = data.get('items', [])
    ahora = datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')

    conn = get_db_connection()
    try:
        # 1. Obtener el último ticket
        ultimo = conn.execute("SELECT MAX(ticket_id) FROM formulario").fetchone()[0]
        nuevo_ticket = (ultimo or 0) + 1

        for item in items:
            # 2. INSERT CORREGIDO: Cuenta bien las columnas (9) y los ? (9)
            conn.execute(
                """INSERT INTO formulario (cliente, telefono, producto, precio, cantidad, fecha, metodo_pago, estado, ticket_id) 
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (cliente, "", item['name'], item['price'], item['qty'], ahora, metodo, 'Pendiente', nuevo_ticket))
        
        conn.commit()
        return jsonify({'message': 'Venta registrada', 'ticket': nuevo_ticket}), 201
    except Exception as e:
        # Esto imprimirá el error real en tu terminal negra (Consola)
        print(f"ERROR EN BASE DE DATOS: {e}") 
        return jsonify({'message': f'Error al guardar: {str(e)}'}), 500
    finally:
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    # Definición de usuarios y sus permisos
    usuarios = {
        "admin":    {"pass": "12345",   "rol": "admin"},
        "cocina":   {"pass": "1", "rol": "cocinero"},
        "hoster":   {"pass": "2", "rol": "hoster"},
        "mesero":   {"pass": "3","rol": "mesero"},
        "cajero":   {"pass": "4",  "rol": "cajero"}
    }

    user_data = usuarios.get(username)
    if user_data and user_data['pass'] == password:
        token_payload = {
            'user_id': username,
            'rol': user_data['rol'], # Guardamos el rol en el token
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }
        token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")
        return jsonify({
            'message': 'Éxito', 
            'token': token, 
            'rol': user_data['rol'] 
        }), 200 
    return jsonify({'message': 'Credenciales incorrectas'}), 401

@app.route('/api/reporte/detallado', methods=['GET'])
@login_required
def get_reporte_detallado(current_user):
    conn = get_db_connection()
    try:
        # Agrupamos por ticket_id para mostrar una sola fila por venta
        ventas = conn.execute("""
            SELECT 
                ticket_id,
                cliente, 
                GROUP_CONCAT(producto || ' (' || cantidad || ')', '<br>') as productos, 
                SUM(cantidad) as total_items,
                SUM(precio * cantidad) as gran_total, 
                metodo_pago,
                fecha 
            FROM formulario 
            WHERE DATE(fecha) = DATE('now', 'localtime')
            GROUP BY ticket_id, cliente, fecha, metodo_pago
            ORDER BY ticket_id DESC
        """).fetchall()
        return jsonify([dict(row) for row in ventas]), 200
    finally:
        conn.close()

@app.route('/api/cocina/finalizar_ticket/<int:tid>', methods=['POST'])
@login_required
def finalizar_ticket(current_user, tid):
    conn = get_db_connection()
    try:
        # Marcamos todos los productos del ticket como Terminado
        conn.execute("UPDATE formulario SET estado = 'Terminado' WHERE ticket_id = ?", (tid,))
        conn.commit()
        return jsonify({'message': f'Ticket #{tid} listo'}), 200
    finally:
        conn.close()

@app.route('/api/cobrar/ticket/<int:tid>', methods=['PUT'])
@login_required
def cobrar_ticket_id(current_user, tid):
    data = request.get_json()
    metodo = data.get('metodo_pago')
    conn = get_db_connection()
    try:
        # Actualizamos el método de pago para todo el ticket
        conn.execute("UPDATE formulario SET metodo_pago = ? WHERE ticket_id = ?", (metodo, tid))
        conn.commit()
        return jsonify({'message': 'Cobro realizado con éxito'}), 200
    finally:
        conn.close()

@app.route('/api/notificaciones/listos', methods=['GET'])
@login_required
def obtener_notificaciones(current_user):
    conn = get_db_connection()
    # Buscamos tickets que pasaron a 'Terminado' en los últimos 2 minutos
    # y que sean del día de hoy
    pedidos_listos = conn.execute("""
        SELECT DISTINCT ticket_id, cliente 
        FROM formulario 
        WHERE estado = 'Terminado' 
        AND DATE(fecha) = DATE('now', 'localtime')
        LIMIT 5
    """).fetchall()
    conn.close()
    return jsonify([dict(p) for p in pedidos_listos])     
        
@app.route('/loaderio-02da15920fabcf6b26e0709c27fafdd9.txt')
def verify_loader_io():
    return "loaderio-02da15920fabcf6b26e0709c27fafdd9"
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)