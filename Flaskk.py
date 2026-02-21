import sqlite3
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS 
import jwt
import datetime
import os
from functools import wraps

app = Flask(__name__)
CORS(app) 

SECRET_KEY = os.environ.get('SECRET_KEY', 'tu_super_clave_secreta_12345')
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DB_NAME = os.path.join(BASE_DIR, 'karlaa.db')

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
        except Exception as e:
            print(f"Error de token: {e}")
            return jsonify({'message': 'Token inválido o expirado.'}), 401
        return f(current_user, *args, **kwargs) 
    return decorated

def get_db_connection():
    conn = sqlite3.connect(DB_NAME) 
    conn.row_factory = sqlite3.Row
    return conn

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

@app.route('/api/reporte/corte', methods=['GET'])
@login_required
def get_corte_reporte(current_user):
    conn = get_db_connection()
    fecha_actual = datetime.datetime.now().strftime('%d/%m/%Y')

    try:
        # Obtener fecha de hoy en formato YYYY-MM-DD
        hoy = datetime.datetime.now().strftime('%Y-%m-%d')
        
        efectivo = conn.execute(
            "SELECT SUM(precio * cantidad) FROM formulario WHERE DATE(fecha) = ? AND metodo_pago = 'Efectivo'",
            (hoy,)
        ).fetchone()[0] or 0
        
        tarjeta = conn.execute(
            "SELECT SUM(precio * cantidad) FROM formulario WHERE DATE(fecha) = ? AND metodo_pago = 'Tarjeta'",
            (hoy,)
        ).fetchone()[0] or 0
        
        transacciones = conn.execute(
            "SELECT COUNT(DISTINCT cliente) FROM formulario WHERE DATE(fecha) = ?",
            (hoy,)
        ).fetchone()[0] or 0

        return jsonify({
            'fecha_corte': fecha_actual,
            'ventas_efectivo': float(efectivo),
            'ventas_tarjeta': float(tarjeta),
            'total_general': float(efectivo + tarjeta),
            'num_transacciones': int(transacciones)
        }), 200
    except Exception as e:
        print(f"Error en reporte: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()


@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')

    ADMIN_USER = "admin"
    ADMIN_PASS = "12345"

    if username == ADMIN_USER and password == ADMIN_PASS:
        token_payload = {
            'user_id': 1, 
            'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)
        }
        token = jwt.encode(token_payload, SECRET_KEY, algorithm="HS256")
        return jsonify({'message': 'Éxito', 'token': token}), 200 
    return jsonify({'message': 'Credenciales incorrectas'}), 401

@app.route('/api/menu', methods=['GET'])
def get_menu():
    conn = get_db_connection()
    try:
        menu_items = conn.execute('SELECT Mnu_nombre_plato, Mnu_descripcion, Mnu_precio FROM menu').fetchall()
        return jsonify([dict(row) for row in menu_items]), 200
    except Exception as e:
        print(f"Error en menu: {e}")
        return jsonify({'message': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/cocina/pedidos', methods=['GET'])
@login_required
def get_pedidos_cocina(current_user):
    conn = get_db_connection()
    try:
        pedidos = conn.execute(
            "SELECT rowid, cliente, producto, cantidad, estado FROM formulario WHERE estado != 'Terminado' ORDER BY rowid DESC"
        ).fetchall()
        conn.close()
        return jsonify([dict(p) for p in pedidos]), 200
    except Exception as e:
        print(f"Error en pedidos cocina: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        conn.close()

@app.route('/api/cocina/actualizar/<int:rowid>', methods=['POST'])
@login_required
def actualizar_estado(current_user, rowid):
    try:
        nuevo_estado = request.json.get('estado')
        conn = get_db_connection()
        conn.execute("UPDATE formulario SET estado = ? WHERE rowid = ?", (nuevo_estado, rowid))
        conn.commit()
        conn.close()
        return jsonify({'message': 'Estado actualizado'}), 200
    except Exception as e:
        print(f"Error al actualizar estado: {e}")
        return jsonify({'error': str(e)}), 500


@app.route('/api/checkout', methods=['POST'])
@login_required 
def register_sale(current_user):
    data = request.get_json()
    cliente = data.get('cliente', 'Mostrador')
    metodo = data.get('metodo_pago', 'Efectivo') 
    items = data.get('items', [])

    conn = get_db_connection()
    try:
        for item in items:
            conn.execute(
                "INSERT INTO formulario (cliente, telefono, producto, precio, cantidad, fecha, metodo_pago, estado) VALUES (?, ?, ?, ?, ?, DATE('now', 'localtime'), ?, ?)",
                (cliente, "", item['name'], item['price'], item['qty'], metodo, 'Pendiente')
            )
        conn.commit()
        return jsonify({'message': 'Venta registrada'}), 201
    except Exception as e:
        print(f"Error en checkout: {e}")
        return jsonify({'message': str(e)}), 500
    finally:
        conn.close()

@app.errorhandler(500)
def internal_error(error):
    print(f"Error 500: {error}")
    return jsonify({'error': 'Error interno del servidor'}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)