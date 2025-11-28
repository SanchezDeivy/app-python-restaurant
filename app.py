from flask import (Flask, jsonify, render_template, request, redirect, url_for, 
                   flash, session, g)
import mysql.connector
from mysql.connector import Error
from datetime import date
from config import DB_CONFIG
# Recomendado para seguridad de contraseñas (ver nota en login)
# from werkzeug.security import check_password_hash, generate_password_hash 

# --- Configuración de la Aplicación ---
app = Flask(__name__)
LOGIN_TEMPLATE = 'login.html'

# IMPORTANTE: Mover esto a variables de entorno en producción
app.secret_key = 'una_clave_secreta_muy_fuerte_y_unica_y_larga_para_la_app'

MENU_DIA_TYPES = ['Entrada', 'Plato Principal', 'Plato Secundario', 'Postre', 'Bebida']

# ============================================================================
# Funciones de Conexión a DB
# ============================================================================

def get_db_connection():
    """Establece y retorna una conexión a la base de datos, usando g para el contexto."""
    if 'db' not in g:
        try:
            g.db = mysql.connector.connect(**DB_CONFIG)
        except Error as e:
            print(f"Error conectando a MySQL: {e}")
            return None
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    """Cierra la conexión a la base de datos al finalizar la solicitud."""
    db = g.pop('db', None)
    if db is not None and db.is_connected():
        db.close()

# ============================================================================
# Funciones de Consulta (Helpers)
# ============================================================================

def get_dashboard_stats():
    stats = {
        'reservas_hoy': 0,
        'reservas_pendientes': 0,
        'platos_activos': 0,
        'total_usuarios': 0,
    }
    db = get_db_connection()
    if db is None: return stats

    cursor = db.cursor()
    hoy = date.today().strftime('%Y-%m-%d')
    try:
        cursor.execute("SELECT COUNT(id) FROM reservas WHERE DATE(reserva_at) = %s AND status IN ('pendiente', 'confirmada')", (hoy,))
        stats['reservas_hoy'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(id) FROM reservas WHERE status = 'pendiente'")
        stats['reservas_pendientes'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(id) FROM platos WHERE status = 'disponible'")
        stats['platos_activos'] = cursor.fetchone()[0]

        cursor.execute("SELECT COUNT(id) FROM usuarios")
        stats['total_usuarios'] = cursor.fetchone()[0]
    except Error as e:
        print(f"Error stats: {e}")
    finally:
        cursor.close()
    return stats

def get_all_reservations_for_admin():
    db = get_db_connection()
    if db is None: return []
    
    cursor = db.cursor(dictionary=True)
    try:
        sql = """
        SELECT id, name, email, guests, notas, status,
            DATE_FORMAT(reserva_at, '%d-%m-%Y') AS fecha,
            DATE_FORMAT(reserva_at, '%H:%i') AS hora,
            mesa_asignada_id
        FROM reservas ORDER BY reserva_at ASC
        """
        cursor.execute(sql)
        return cursor.fetchall()
    except Error as e:
        print(f"Error admin reservas: {e}")
        return []
    finally:
        cursor.close()

def get_all_categorias():
    db = get_db_connection()
    if db is None: return []
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nombre FROM categorias_menu WHERE status = 'activo' ORDER BY orden ASC")
        return cursor.fetchall()
    except Error:
        return []
    finally:
        cursor.close()

def get_all_platos():
    db = get_db_connection()
    if db is None: return []
    cursor = db.cursor(dictionary=True)
    try:
        sql = """
        SELECT p.id, p.nombre, p.descripcion, p.precio, p.status, p.categoria_id, c.nombre AS categoria_nombre 
        FROM platos p JOIN categorias_menu c ON p.categoria_id = c.id
        ORDER BY c.orden, p.nombre ASC
        """
        cursor.execute(sql)
        return cursor.fetchall()
    except Error:
        return []
    finally:
        cursor.close()

def get_all_active_platos():
    db = get_db_connection()
    if db is None: return []
    cursor = db.cursor(dictionary=True)
    try:
        cursor.execute("SELECT id, nombre FROM platos WHERE status = 'disponible' ORDER BY nombre ASC")
        return cursor.fetchall()
    except Error:
        return []
    finally:
        cursor.close()

def get_menu_by_id(menu_id):
    db = get_db_connection()
    if db is None: return None
    cursor = db.cursor(dictionary=True)
    try:
        # 1. Cabecera
        cursor.execute("SELECT id, fecha, precio_fijo FROM menu_del_dia WHERE id = %s", (menu_id,))
        menu = cursor.fetchone()
        if not menu: return None
        
        # 2. Detalles (Platos)
        cursor.execute("SELECT plato_id, tipo_plato_dia FROM detalle_menu_dia WHERE menu_dia_id = %s", (menu_id,))
        detalles_rows = cursor.fetchall()
        
        # Formatear detalles en un diccionario {tipo_plato: [id_plato, ...]}
        detalles = {tipo: [] for tipo in MENU_DIA_TYPES}
        for row in detalles_rows:
            if row['tipo_plato_dia'] in detalles:
                detalles[row['tipo_plato_dia']].append(str(row['plato_id'])) # Convertir a string para JS
        
        menu['detalles'] = detalles
        
        # Formatear la fecha para el input type="date"
        menu['fecha'] = menu['fecha'].strftime('%Y-%m-%d')

        return menu
    except Error as e:
        print(f"Error al obtener menú: {e}")
        return None
    finally: cursor.close()

def create_or_update_menu_del_dia_db(data):
    """Lógica transaccional para guardar/actualizar el menú del día."""
    db = get_db_connection()
    if db is None: raise Error("No hay conexión BD")
    cursor = db.cursor()
    try:
        fecha = data['fecha']
        precio_fijo = data['precio_fijo']
        menu_id = data.get('id') # Puede ser None si es nuevo

        # 1. Cabecera (Crear o Actualizar)
        if menu_id:
            # Actualizar existente
            cursor.execute("UPDATE menu_del_dia SET fecha = %s, precio_fijo = %s, status = 'activo' WHERE id = %s", (fecha, precio_fijo, menu_id))
        else:
            # Insertar nuevo
            cursor.execute("INSERT INTO menu_del_dia (fecha, precio_fijo, status) VALUES (%s, %s, 'activo')", (fecha, precio_fijo))
            menu_id = cursor.lastrowid
            
        # 2. Limpiar detalles viejos
        cursor.execute("DELETE FROM detalle_menu_dia WHERE menu_dia_id = %s", (menu_id,))
            
        # 3. Insertar nuevos detalles
        for tipo in MENU_DIA_TYPES:
            plato_ids = data.get(tipo, [])
            # Asegurar que se manejan correctamente los arrays vacíos o valores simples
            if not isinstance(plato_ids, list): plato_ids = [plato_ids]
            
            for orden, pid_str in enumerate(plato_ids):
                if pid_str:
                    try:
                        sql_det = "INSERT INTO detalle_menu_dia (menu_dia_id, plato_id, tipo_plato_dia, orden) VALUES (%s, %s, %s, %s)"
                        cursor.execute(sql_det, (menu_id, int(pid_str), tipo, orden + 1))
                    except ValueError: continue
        db.commit()
        return menu_id
    except Error as e:
        db.rollback()
        raise e
    finally: cursor.close()

def get_recent_daily_menus():
    """Obtiene los menús del día de los últimos 30 días."""
    db = get_db_connection()
    if db is None: return []
    cursor = db.cursor(dictionary=True)
    try:
        sql = """
            SELECT 
                m.id, 
                DATE_FORMAT(m.fecha, '%d-%m-%Y') AS fecha_formateada,
                m.precio_fijo, 
                m.status,
                GROUP_CONCAT(CONCAT(d.tipo_plato_dia, ': ', p.nombre) ORDER BY d.orden SEPARATOR ' | ') AS detalles
            FROM menu_del_dia m
            LEFT JOIN detalle_menu_dia d ON m.id = d.menu_dia_id
            LEFT JOIN platos p ON d.plato_id = p.id
            WHERE m.fecha >= DATE_SUB(CURDATE(), INTERVAL 30 DAY)
            GROUP BY m.id, m.fecha, m.precio_fijo, m.status
            ORDER BY m.fecha DESC
        """
        cursor.execute(sql)
        return cursor.fetchall()
    except Error as e: 
        print(f"Error al obtener menús recientes: {e}")
        return []
    finally: cursor.close()

# ============================================================================
# Rutas de Autenticación y Vistas
# ============================================================================

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        
        db = get_db_connection()
        if not db:
            flash('Error de conexión a BD.', 'error')
            return render_template(LOGIN_TEMPLATE)

        cursor = db.cursor(dictionary=True)
        try:
            cursor.execute("SELECT id, email, password, nombres, rol FROM usuarios WHERE email = %s", (email,))
            user = cursor.fetchone()

            # NOTA: En producción, usar check_password_hash(user['password'], password)
            if user and user['password'] == password:
                session['user_id'] = user['id']
                session['email'] = user['email']
                session['rol'] = user['rol']
                flash(f'¡Bienvenido, {user["nombres"]}!', 'success')
                return redirect(url_for('admin_dashboard'))
            else:
                flash('Credenciales incorrectas.', 'error')
        except Error as e:
            flash(f'Error de sistema: {e}', 'error')
        finally:
            cursor.close()

    return render_template(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.clear()
    flash('Sesión cerrada exitosamente.', 'success')
    return redirect(url_for('login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('admin_dashboard.html', stats=get_dashboard_stats())

@app.route('/admin/menu')
def admin_menu():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('admin_menu.html', platos=get_all_platos(), categorias=get_all_categorias())

@app.route('/admin/reservas')
def admin_reservas():
    if 'user_id' not in session: return redirect(url_for('login'))
    return render_template('admin_reservas.html', reservations=get_all_reservations_for_admin())

@app.route('/admin/menu-del-dia')
def admin_menu_del_dia():
    if 'user_id' not in session: return redirect(url_for('login'))
    recent_menus = get_recent_daily_menus()
    return render_template(
        'admin_menu_del_dia.html', 
        platos_activos=get_all_active_platos(), 
        menu_types=MENU_DIA_TYPES,
        # PASAR LA LISTA A LA PLANTILLA
        recent_menus=recent_menus
    )

@app.route('/reservar')
def reservar():
    return render_template('reservas.html')

# ============================================================================
# API REST (Reservas)
# ============================================================================

@app.route('/api/menu-del-dia', methods=['POST'])
def api_create_or_update_menu_del_dia():
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    try:
        data = request.get_json()
        if not data or 'fecha' not in data or 'precio_fijo' not in data:
            return jsonify({"error": "Datos incompletos"}), 400
        
        menu_id = create_or_update_menu_del_dia_db(data)
        return jsonify({"message": "Menú guardado", "id": menu_id}), 201
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/api/menu-del-dia/<int:menu_id>', methods=['GET'])
def api_get_menu_del_dia(menu_id):
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    menu = get_menu_by_id(menu_id)
    if not menu:
        return jsonify({"error": "Menú no encontrado"}), 404
    return jsonify(menu)

@app.route('/api/menu-del-dia/<int:menu_id>', methods=['DELETE'])
def api_delete_menu_del_dia(menu_id):
    if 'user_id' not in session: return jsonify({"error": "No autorizado"}), 401
    db = get_db_connection()
    if not db: return jsonify({"error": "Error conexión BD"}), 500
    cursor = db.cursor()
    try:
        # Se recomienda INACTIVAR en lugar de eliminar, pero para simplificar, usaremos DELETE o UPDATE status
        # Opción 1: Eliminar (Desaconsejado)
        # cursor.execute("DELETE FROM menu_del_dia WHERE id=%s", (menu_id,))
        
        # Opción 2: Inactivar (Recomendado)
        cursor.execute("UPDATE menu_del_dia SET status='inactivo' WHERE id=%s", (menu_id,))
        
        db.commit()
        return jsonify({"message": "Menú inactivado correctamente."}), 200
    except Error as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally: cursor.close()
    
@app.route('/reservations', methods=['GET'])
def get_all_reservations():
    db = get_db_connection()
    if not db: return jsonify({"error": "Error BD"}), 500
    
    cursor = db.cursor(dictionary=True)
    try:
        sql = """SELECT id, name, email, guests, notas, status, mesa_asignada_id,
                 DATE_FORMAT(reserva_at, '%d-%m-%Y') AS fecha, DATE_FORMAT(reserva_at, '%H:%i') AS hora
                 FROM reservas ORDER BY reserva_at ASC"""
        cursor.execute(sql)
        return jsonify(cursor.fetchall())
    except Error as e:
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()

@app.route('/reservations', methods=['POST'])
def create_reservation(): 
    db = get_db_connection()
    if not db: return jsonify({"error": "Error BD"}), 500
    
    try:
        data = request.get_json() 
        if not data: return jsonify({"error": "JSON inválido"}), 400
        
        required = ['name', 'email', 'date', 'time', 'guests']
        if not all(k in data for k in required):
            return jsonify({"error": "Faltan campos"}), 400

        reserva_at = f"{data['date']} {data['time']}:00"
        
        cursor = db.cursor()
        sql = """INSERT INTO reservas (name, email, reserva_at, guests, notas, status) 
                 VALUES (%s, %s, %s, %s, %s, 'pendiente')"""
        cursor.execute(sql, (data['name'], data['email'], reserva_at, data['guests'], data.get('notes')))
        db.commit()
        return jsonify({"message": "Reserva creada", "id": cursor.lastrowid}), 201
    except Error as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        if 'cursor' in locals(): cursor.close()

@app.route('/reservations/<int:reservation_id>', methods=['GET'])
def get_reservation_by_id(reservation_id):
    db = get_db_connection()
    if not db: return jsonify({"error": "Error BD"}), 500
    
    cursor = db.cursor(dictionary=True)
    try:
        sql = """SELECT id, name, email, guests, notas, status, mesa_asignada_id,
                 DATE_FORMAT(reserva_at, '%Y-%m-%d') AS fecha, DATE_FORMAT(reserva_at, '%H:%i') AS hora
                 FROM reservas WHERE id = %s"""
        cursor.execute(sql, (reservation_id,))
        row = cursor.fetchone()
        return jsonify(row) if row else (jsonify({"error": "No encontrada"}), 404)
    finally:
        cursor.close()

@app.route('/reservations/<int:reservation_id>', methods=['PUT'])
def update_reservation_details(reservation_id):
    db = get_db_connection()
    if not db: return jsonify({"error": "Error BD"}), 500

    data = request.get_json()
    cursor = db.cursor()
    try:
        # Validación de campos y manejo de nulos para mesa_id
        mesa_id = data.get('mesa_asignada_id')
        if mesa_id == '' or mesa_id == 'null': mesa_id = None
        
        reserva_at = f"{data['fecha']} {data['hora']}:00"
        
        sql = """UPDATE reservas SET name=%s, email=%s, guests=%s, reserva_at=%s, 
                 notas=%s, status=%s, mesa_asignada_id=%s WHERE id=%s"""
        values = (data['name'], data['email'], data['guests'], reserva_at, 
                  data['notas'], data['status'], mesa_id, reservation_id)
        
        cursor.execute(sql, values)
        db.commit()
        
        if cursor.rowcount == 0:
            return jsonify({"message": "No se modificó nada o ID incorrecto"}), 404
        return jsonify({"message": "Actualizado"}), 200
    except Error as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()

@app.route('/reservations/status/<int:reservation_id>', methods=['POST'])
def update_reservation_status(reservation_id):
    db = get_db_connection()
    if not db: return jsonify({"error": "Error BD"}), 500

    data = request.get_json()
    new_status = data.get('status')
    mesa_id = data.get('mesa_id') or None
    
    if new_status not in ['confirmada', 'cancelada', 'pendiente']:
        return jsonify({"error": "Estado inválido"}), 400

    cursor = db.cursor()
    try:
        if new_status == 'confirmada' and mesa_id:
            sql = "UPDATE reservas SET status = %s, mesa_asignada_id = %s WHERE id = %s"
            cursor.execute(sql, (new_status, mesa_id, reservation_id))
        else:
            sql = "UPDATE reservas SET status = %s WHERE id = %s"
            cursor.execute(sql, (new_status, reservation_id))
            
        db.commit()
        return jsonify({"message": f"Estado cambiado a {new_status}"}), 200
    except Error as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()

@app.route('/reservations/<int:reservation_id>', methods=['DELETE'])
def delete_reservation(reservation_id):
    db = get_db_connection()
    if not db: return jsonify({"error": "Error BD"}), 500

    cursor = db.cursor()
    try:
        cursor.execute("DELETE FROM reservas WHERE id = %s", (reservation_id,))
        db.commit()
        return jsonify({"message": "Eliminada"}) if cursor.rowcount > 0 else (jsonify({"error": "No encontrada"}), 404)
    except Error as e:
        db.rollback()
        return jsonify({"error": str(e)}), 500
    finally:
        cursor.close()

if __name__ == '__main__':
    app.run(debug=True, port=5000)