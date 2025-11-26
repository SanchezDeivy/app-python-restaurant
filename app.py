from flask import (Flask, jsonify, render_template, request, redirect, url_for, 
    flash, session, g)
import os
import time
from functools import wraps
from werkzeug.utils import secure_filename
import mysql.connector 
from mysql.connector import Error 
import hashlib 
from config import DB_CONFIG
import requests
import json
from datetime import date # Necesario para get_dashboard_stats

# --- Configuración de la Aplicación ---
app = Flask(__name__)
LOGIN_TEMPLATE = 'login.html'

app.secret_key = 'una_clave_secreta_muy_fuerte_y_unica_y_larga_para_la_app'

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
# Funciones de Consulta Específicas para Dashboard y Admin
# ============================================================================

def get_dashboard_stats():
    """
    Realiza las consultas necesarias para obtener el resumen del Dashboard.
    Retorna un diccionario con las estadísticas.
    """
    stats = {
        'reservas_hoy': 0,
        'reservas_pendientes': 0,
        'platos_activos': 0,
        'total_usuarios': 0,
    }

    db = get_db_connection()
    if db is None:
        return stats

    cursor = db.cursor()
    hoy = date.today().strftime('%Y-%m-%d')
    
    try:
        # 1. Reservas Hoy
        sql_hoy = "SELECT COUNT(id) FROM reservas WHERE DATE(reserva_at) = %s AND status IN ('pendiente', 'confirmada')"
        cursor.execute(sql_hoy, (hoy,))
        stats['reservas_hoy'] = cursor.fetchone()[0]

        # 2. Reservas Pendientes
        sql_pendientes = "SELECT COUNT(id) FROM reservas WHERE status = 'pendiente'"
        cursor.execute(sql_pendientes)
        stats['reservas_pendientes'] = cursor.fetchone()[0]

        # 3. Platos Activos
        sql_platos = "SELECT COUNT(id) FROM platos WHERE status = 'disponible'"
        cursor.execute(sql_platos)
        stats['platos_activos'] = cursor.fetchone()[0]

        # 4. Total Usuarios
        sql_usuarios = "SELECT COUNT(id) FROM usuarios"
        cursor.execute(sql_usuarios)
        stats['total_usuarios'] = cursor.fetchone()[0]

    except Error as e:
        print(f"Error al obtener estadísticas del dashboard: {e}")
    finally:
        cursor.close()
        
    return stats

def get_all_reservations_for_admin():
    """Obtiene todas las reservas con formato de fecha y hora para la vista de administrador."""
    db = get_db_connection()
    if db is None:
        return []

    cursor = db.cursor(dictionary=True)
    
    try:
        # Usamos %Y-%m-%d para la fecha y %H:%i para la hora
        sql = """
        SELECT 
            id, name, email, guests, notas, status,
            DATE_FORMAT(reserva_at, '%d-%m-%Y') AS fecha,
            DATE_FORMAT(reserva_at, '%H:%i') AS hora,
            mesa_asignada_id
        FROM reservas 
        ORDER BY reserva_at ASC
        """
        cursor.execute(sql)
        reservations = cursor.fetchall()
        return reservations
    except Error as e:
        print(f"Error al obtener reservas para admin: {e}")
        return []
    finally:
        cursor.close()

# ============================================================================
# Rutas de Autenticación y Vistas de Admin
# ============================================================================

@app.route('/')
def index():
    """Ruta principal vacía."""
    return render_template('index.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    # ... (Lógica de Login existente) ...
    if request.method == 'POST':
        username_input = request.form.get('email')
        password_input = request.form.get('password')
        db = get_db_connection()
        if db is None:
            flash('Error de conexión a la base de datos.', 'error')
            return render_template(LOGIN_TEMPLATE)

        cursor = db.cursor(dictionary=True)
        
        try:
            sql = "SELECT id, email, password, nombres, rol FROM usuarios WHERE email = %s"
            cursor.execute(sql, (username_input,))
            user = cursor.fetchone()

            if user:
                # Nota: Idealmente, usar hashing para las contraseñas
                if user['password'] == password_input:
                    
                    session['user_id'] = user['id']
                    session['email'] = user['email']
                    session['rol'] = user['rol'] # Guardar el rol en la sesión
                    
                    flash(f'¡Bienvenido, {user["nombres"]}!', 'success') 
                    
                    # Redirigir según el rol si es necesario, aquí redirige a admin
                    return redirect(url_for('admin_dashboard'))
                else:
                    flash('Contraseña incorrecta.', 'error')
            else:
                flash('Usuario no encontrado.', 'error')

        except Error as e:
            flash(f'Ocurrió un error al intentar iniciar sesión: {e}', 'error')
        finally:
            cursor.close()

    return render_template(LOGIN_TEMPLATE)

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    session.pop('email', None)
    session.pop('rol', None)
    flash('Sesión cerrada exitosamente.', 'success')
    return redirect(url_for('login'))

@app.route('/admin/dashboard')
def admin_dashboard():
    stats = get_dashboard_stats()
    return render_template('admin_dashboard.html', stats=stats)

@app.route('/admin/menu')
def admin_menu():
    return "<h1>Bienvenido al Menú</h1>"

@app.route('/admin/reservas')
def admin_reservas():
    reservations = get_all_reservations_for_admin()
    return render_template('admin_reservas.html', reservations=reservations)

# ------------------------------------
# A. RESERVA (Vista de Cliente)
# ------------------------------------
@app.route('/reservar')
def reservar():
    """Ruta principal de reservas para el cliente."""
    return render_template('reservas.html')


# ============================================================================
# Rutas API para Gestión de Reservas (CRUD y Estatus)
# ============================================================================

@app.route('/reservations', methods=['POST'])
def create_reservation(): 
    """Crea una nueva reserva, usando la tabla 'reservas' y campo 'reserva_at'."""
    
    db = get_db_connection()
    if db is None:
        return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
        
    cursor = db.cursor()
    
    try:
        data = request.get_json() 
        
        if data is None:
            return jsonify({"error": "No se recibieron datos JSON válidos."}), 400
            
        required_fields = ['name', 'email', 'date', 'time', 'guests']
        if not all(field in data for field in required_fields):
            return jsonify({"error": "Faltan campos obligatorios"}), 400

        reserva_at_combined = f"{data['date']} {data['time']}:00"
        
        # Usamos la tabla 'reservas' y los campos de la DB
        sql = "INSERT INTO reservas (name, email, reserva_at, guests, notas, status) VALUES (%s, %s, %s, %s, %s, %s)"
        values = (
            data['name'], 
            data['email'], 
            reserva_at_combined,      
            data['guests'], 
            data.get('notes', None),
            'pendiente' # Estado inicial
        )
        
        cursor.execute(sql, values)
        db.commit() 
        new_id = cursor.lastrowid
        
        return jsonify({"message": "Reserva creada exitosamente", "id": new_id}), 201

    except Exception as e:
        db.rollback()
        print(f"Error al crear reserva: {e}")
        return jsonify({"error": f"Error interno del servidor: {e}"}), 500
    finally:
        cursor.close()

# --- GET (Detalles) ---
@app.route('/reservations/<int:reservation_id>', methods=['GET'])
def get_reservation_by_id(reservation_id):
    """Obtiene y retorna una reserva específica por su ID. (Para Modal Ver/Editar)"""
    db = get_db_connection()
    if db is None:
        return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
        
    cursor = db.cursor(dictionary=True)
    
    try:
        sql = """
        SELECT 
            id, name, email, guests, notas, status, mesa_asignada_id,
            DATE_FORMAT(reserva_at, '%Y-%m-%d') AS fecha,
            DATE_FORMAT(reserva_at, '%H:%i') AS hora
        FROM reservas 
        WHERE id = %s
        """
        cursor.execute(sql, (reservation_id,))
        reservation = cursor.fetchone()
        
        if reservation:
            return jsonify(reservation), 200
        else:
            return jsonify({"error": "Reserva no encontrada"}), 404

    except Error as e:
        print(f"Error al obtener reserva: {e}")
        return jsonify({"error": "Error interno del servidor"}), 500
    finally:
        cursor.close()

# --- PUT (Edición Completa) ---
@app.route('/reservations/<int:reservation_id>', methods=['PUT'])
def update_reservation_details(reservation_id):
    """Actualiza una reserva existente con todos los campos editables. (Desde Modal Editar)"""
    db = get_db_connection()
    if db is None:
        return jsonify({"error": "Error de conexión a la base de datos"}), 500

    cursor = db.cursor()
    data = request.get_json()
    
    try:
        # Campos a actualizar
        name = data.get('name')
        email = data.get('email')
        guests = data.get('guests')
        fecha = data.get('fecha')
        hora = data.get('hora')
        notas = data.get('notas')
        status = data.get('status') 
        mesa_asignada_id = data.get('mesa_asignada_id') or None 

        # Combina la fecha y hora para el campo DATETIME
        reserva_at_combined = f"{fecha} {hora}:00"

        sql = """
            UPDATE reservas SET 
                name = %s, email = %s, guests = %s, 
                reserva_at = %s, notas = %s, 
                status = %s, mesa_asignada_id = %s
            WHERE id = %s
        """
        values = (name, email, guests, reserva_at_combined, notas, status, mesa_asignada_id, reservation_id)

        cursor.execute(sql, values)
        
        if cursor.rowcount == 0:
            db.rollback()
            return jsonify({"message": "Reserva no encontrada o no se realizaron cambios"}), 404
        
        db.commit() 
        return jsonify({"message": f"Reserva {reservation_id} actualizada exitosamente."}), 200

    except Error as e:
        db.rollback()
        print(f"Error al actualizar la reserva: {e}")
        return jsonify({"error": f"Error interno del servidor: {e}"}), 500
    except Exception as e:
        return jsonify({"error": f"Datos inválidos: {e}"}), 400
    finally:
        cursor.close()

# --- POST (Cambio de Estatus rápido Aprobar/Cancelar) ---
@app.route('/reservations/status/<int:reservation_id>', methods=['POST'])
def update_reservation_status(reservation_id):
    """Actualiza solo el estado (status) de una reserva específica."""
    db = get_db_connection()
    if db is None:
        return jsonify({"error": "Error de conexión a la base de datos"}), 500

    cursor = db.cursor()
    
    try:
        data = request.get_json()
        new_status = data.get('status')
        mesa_asignada_id = data.get('mesa_id') # Campo opcional
        
        if new_status not in ['confirmada', 'cancelada']:
            return jsonify({"error": "Estado no válido."}), 400

        if new_status == 'confirmada' and mesa_asignada_id:
            sql = "UPDATE reservas SET status = %s, mesa_asignada_id = %s WHERE id = %s"
            values = (new_status, mesa_asignada_id, reservation_id)
        else:
            sql = "UPDATE reservas SET status = %s WHERE id = %s"
            values = (new_status, reservation_id)

        cursor.execute(sql, values)
        
        if cursor.rowcount == 0:
            db.rollback()
            return jsonify({"message": "Reserva no encontrada o el estado es el mismo."}), 404
        
        db.commit() 
        return jsonify({"message": f"Reserva {reservation_id} actualizada a '{new_status}' exitosamente."}), 200

    except Error as e:
        db.rollback()
        print(f"Error al actualizar el estado de la reserva: {e}")
        return jsonify({"error": f"Error interno del servidor: {e}"}), 500
    finally:
        cursor.close()
        
# --- GET ALL (API) ---
@app.route('/reservations', methods=['GET'])
def get_all_reservations():
    """Obtiene y retorna todas las reservas para una API de cliente/uso general."""
    
    db = get_db_connection()
    if db is None:
        return jsonify({"error": "No se pudo conectar a la base de datos"}), 500
        
    cursor = db.cursor(dictionary=True)
    
    try:
        sql = """
        SELECT 
            id, name, email, guests, notas, status, mesa_asignada_id,
            DATE_FORMAT(reserva_at, '%d-%m-%Y') AS fecha,
            DATE_FORMAT(reserva_at, '%H:%i') AS hora
        FROM reservas 
        ORDER BY reserva_at ASC
        """
        cursor.execute(sql)
        reservations = cursor.fetchall()
        
        return jsonify(reservations)
    except Error as e:
        print(f"Error al obtener reservas: {e}")
        return jsonify({"error": "Error interno del servidor al consultar reservas"}), 500
    finally:
        cursor.close()

# --- DELETE ---
@app.route('/reservations/<int:reservation_id>', methods=['DELETE'])
def delete_reservation(reservation_id):
    """Elimina una reserva existente."""
    db = get_db_connection()
    if db is None:
        return jsonify({"error": "Error de conexión a la base de datos"}), 500

    cursor = db.cursor()
    
    try:
        sql = "DELETE FROM reservas WHERE id = %s"
        cursor.execute(sql, (reservation_id,))
        
        if cursor.rowcount == 0:
            db.rollback()
            return jsonify({"message": "Reserva no encontrada"}), 404
            
        db.commit()
        return jsonify({"message": f"Reserva con ID {reservation_id} eliminada exitosamente"})
    except Error as e:
        db.rollback()
        print(f"Error al eliminar la reserva: {e}")
        return jsonify({"error": f"Error interno del servidor: {e}"}), 500
    finally:
        cursor.close()


if __name__ == '__main__':
    app.run(debug=True, port=5000)