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

@app.route('/api/reporte/corte', methods=['GET'])
@login_required
def get_corte_reporte(current_user):
    conn = get_db_connection()
    cur = conn.cursor()
    fecha_actual = datetime.datetime.now().strftime('%d/%m/%Y')
    try:
        # Suma de efectivo
        cur.execute("SELECT SUM(precio * cantidad) as total FROM formulario WHERE fecha = CURRENT_DATE AND metodo_pago = 'Efectivo'")
        efectivo = cur.fetchone()['total'] or 0
        
        # Suma de tarjeta
        cur.execute("SELECT SUM(precio * cantidad) as total FROM formulario WHERE fecha = CURRENT_DATE AND metodo_pago = 'Tarjeta'")
        tarjeta = cur.fetchone()['total'] or 0
        
        # CAMBIO AQUÍ: Contar todos los registros del día en lugar de clientes distintos
        cur.execute("SELECT COUNT(DISTINCT cliente) as total FROM formulario WHERE fecha = CURRENT_DATE")
        transacciones = cur.fetchone()['total'] or 0
        
        return jsonify({
            'fecha_corte': fecha_actual,
            'ventas_efectivo': float(efectivo),
            'ventas_tarjeta': float(tarjeta),
            'total_general': float(efectivo + tarjeta),
            'num_transacciones': int(transacciones)
        }), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/menu', methods=['GET'])
def get_menu():
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        cur.execute('SELECT mnu_nombre_plato, mnu_descripcion, mnu_precio FROM menu')
        menu_items = cur.fetchall()
        return jsonify(menu_items), 200
    except Exception as e:
        return jsonify({'message': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/cocina/pedidos', methods=['GET'])
@login_required
def get_pedidos_cocina(current_user):
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # Importante: Asegúrate que tu tabla tenga columna 'id'
        cur.execute("SELECT id, cliente, producto, cantidad, estado FROM formulario WHERE estado != 'Terminado' ORDER BY id DESC")
        pedidos = cur.fetchall()
        return jsonify(pedidos), 200
    except Exception as e:
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/checkout', methods=['POST'])
@login_required 
def register_sale(current_user):
    data = request.get_json()
    items = data.get('items', [])
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        for item in items:
            cur.execute(
                "INSERT INTO formulario (cliente, telefono, producto, precio, cantidad, fecha, metodo_pago, estado) VALUES (%s, %s, %s, %s, %s, CURRENT_DATE, %s, %s)",
                (data.get('cliente', 'Mostrador'), "", item['name'], item['price'], item['qty'], data.get('metodo_pago', 'Efectivo'), 'Pendiente')
            )
        conn.commit()
        return jsonify({'message': 'Venta registrada'}), 201
    except Exception as e:
        return jsonify({'message': str(e)}), 500
    finally:
        cur.close()
        conn.close()

@app.route('/api/login', methods=['POST'])
def login():
    data = request.get_json()
    if data.get('username') == "admin" and data.get('password') == "12345":
        token = jwt.encode({'user_id': 1, 'exp': datetime.datetime.utcnow() + datetime.timedelta(hours=24)}, SECRET_KEY, algorithm="HS256")
        return jsonify({'message': 'Éxito', 'token': token}), 200 
    return jsonify({'message': 'Credenciales incorrectas'}), 401
@app.route('/api/cocina/actualizar/<int:pedido_id>', methods=['PUT'])
@login_required
def actualizar_estado_pedido(current_user, pedido_id):
    data = request.get_json()
    nuevo_estado = data.get('estado')
    
    conn = get_db_connection()
    cur = conn.cursor()
    try:
        # En Postgres usamos %s para el ID y el estado
        cur.execute(
            "UPDATE formulario SET estado = %s WHERE id = %s",
            (nuevo_estado, pedido_id)
        )
        conn.commit()
        return jsonify({'message': 'Estado actualizado'}), 200
    except Exception as e:
        print(f"Error actualizando pedido: {e}")
        return jsonify({'error': str(e)}), 500
    finally:
        cur.close()
        conn.close()
        
@app.route('/loaderio-02da15920fabcf6b26e0709c27fafdd9.txt')
def verify_loader_io():
    return "loaderio-02da15920fabcf6b26e0709c27fafdd9"
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(host='0.0.0.0', port=port, debug=True)