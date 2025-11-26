-- SCRIPT SQL FINAL: RESERVAS SIN SELECCIÓN DE MESA NI LOGIN REQUERIDO
DROP DATABASE IF EXISTS sumak_mikuy;
CREATE DATABASE sumak_mikuy CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE sumak_mikuy;

-- ------------------------------
-- TABLAS MAESTRAS OPTIMIZADAS
-- ------------------------------

-- TABLA: usuarios (Simplificada para Login/Rol)
CREATE TABLE usuarios (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombres VARCHAR(100) NOT NULL,
    apellidos VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL UNIQUE,
    password VARCHAR(255) NOT NULL,
    provider ENUM('local', 'google', 'facebook') DEFAULT 'local',
    rol ENUM('cliente', 'admin', 'mesero', 'cocina') DEFAULT 'cliente' NOT NULL,
    fecha_registro TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    status ENUM('activo', 'inactivo', 'suspendido') DEFAULT 'activo',
    INDEX idx_email(email),
    INDEX idx_rol(rol)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO usuarios (nombres, apellidos, email, password, rol) VALUES
('Juan', 'Pérez', 'juan.perez@gmail.com', 'hashed_pass', 'cliente'),
('María', 'González', 'maria.gonzalez@hotmail.com', 'hashed_pass', 'admin'),
('Pedro', 'Torres', 'pedro.torres@gmail.com', 'hashed_pass', 'mesero');

---

-- TABLA: mesas (Status simplificado)
CREATE TABLE mesas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    numero_mesa INT NOT NULL UNIQUE,
    capacidad INT NOT NULL,
    ubicacion ENUM('interior','exterior','terraza','vip') DEFAULT 'interior',
    descripcion VARCHAR(255),
    status ENUM('disponible','ocupada','mantenimiento') DEFAULT 'disponible', 
    INDEX idx_numero(numero_mesa)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO mesas (numero_mesa, capacidad, ubicacion, status) VALUES
(1,4,'interior','disponible'),
(2,2,'interior','disponible'),
(3,6,'exterior','disponible'),
(4,4,'interior','ocupada');

---

-- TABLA: categorias_menu
CREATE TABLE categorias_menu (
    id INT AUTO_INCREMENT PRIMARY KEY,
    nombre VARCHAR(100) NOT NULL,
    descripcion TEXT,
    orden INT DEFAULT 0,
    status ENUM('activo','inactivo') DEFAULT 'activo',
    INDEX idx_orden(orden)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO categorias_menu (nombre, descripcion, orden) VALUES
('Entradas','Entradas andinas',1),
('Platos Principales','Platos típicos peruanos',2),
('Bebidas','Bebidas típicas',5);

---

-- TABLA: platos (Campos simplificados)
CREATE TABLE platos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    categoria_id INT NOT NULL,
    nombre VARCHAR(150) NOT NULL,
    descripcion TEXT NOT NULL,
    precio DECIMAL(10,2) NOT NULL,
    tiempo_preparacion_min INT, 
    es_vegetariano BOOLEAN DEFAULT FALSE,
    status ENUM('disponible','agotado','descontinuado') DEFAULT 'disponible',
    FOREIGN KEY (categoria_id) REFERENCES categorias_menu(id) ON DELETE RESTRICT,
    INDEX idx_categoria(categoria_id),
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO platos (categoria_id, nombre, descripcion, precio, tiempo_preparacion_min, es_vegetariano, status) VALUES
(1,'Anticuchos','Corazón de res marinado',25.00,30,FALSE,'disponible'),
(2,'Lomo saltado','Carne de res, cebolla y papas fritas',35.00,25,FALSE,'disponible'),
(2,'Ensalada de quinua','Ensalada fresca de quinua',18.00,15,TRUE,'disponible');

-- ------------------------------
-- TABLAS TRANSACCIONALES OPTIMIZADAS
-- ------------------------------

-- TABLA: reservas (Mesa eliminada, usuario opcional)
CREATE TABLE reservas (
    id INT AUTO_INCREMENT PRIMARY KEY,
    -- mesa_id eliminada: la asignación la hace el administrador después.
    mesa_asignada_id INT, -- Nuevo campo, la mesa se asigna después. Puede ser NULL.
    usuario_id INT, -- NULL si es cliente anónimo (no logueado)
    
    -- Datos del cliente anónimo (requeridos por el formulario)
    name VARCHAR(100) NOT NULL,
    email VARCHAR(100) NOT NULL,
    guests INT NOT NULL, 
    
    reserva_at DATETIME NOT NULL, 
    fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    notas TEXT,
    
    -- Flujo de aprobación UX: pendiente (inicial) -> confirmada/cancelada
    status ENUM('pendiente','confirmada','completada','cancelada','no_asistio') DEFAULT 'pendiente',
    
    FOREIGN KEY (usuario_id) REFERENCES usuarios(id) ON DELETE SET NULL,
    FOREIGN KEY (mesa_asignada_id) REFERENCES mesas(id) ON DELETE SET NULL,
    INDEX idx_reserva_at(reserva_at),
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO reservas (name, email, guests, reserva_at, notas, status) VALUES
('Juan Pérez', 'juan.perez@gmail.com', 6, '2025-12-01 19:00:00', 'Cumpleaños', 'pendiente'), -- Pendiente
('Carlos López', 'carlos.anonimo@test.com', 2, '2025-12-01 20:30:00', 'Cena romántica', 'pendiente'), -- Pendiente
('Luisa Fernández', 'luisa.fernandez@web.com', 4, '2025-12-02 18:00:00', 'Reunión familiar', 'pendiente'); -- Pendiente

UPDATE reservas SET mesa_asignada_id = 3, status = 'confirmada' WHERE id = 1; -- Asignación y confirmación posterior

---

-- TABLA: pedidos (Solo vinculada a la mesa y al total)
CREATE TABLE pedidos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    mesa_id INT NOT NULL,
    fecha_pedido TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    total DECIMAL(10,2) NOT NULL,
    metodo_pago ENUM('efectivo','tarjeta','yape','plin','transferencia') DEFAULT 'efectivo',
    notas_especiales TEXT,
    status ENUM('pendiente','en_preparacion','listo','entregado','cancelado') DEFAULT 'pendiente',
    FOREIGN KEY (mesa_id) REFERENCES mesas(id) ON DELETE RESTRICT,
    INDEX idx_fecha(fecha_pedido),
    INDEX idx_status(status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO pedidos (mesa_id, total, metodo_pago, notas_especiales, status) VALUES
(4, 180.00, 'tarjeta', 'Sin cebolla', 'entregado'),
(1, 110.00, 'efectivo', 'Poco picante', 'en_preparacion'),
(2, 150.00, 'yape', 'Extra salsa', 'pendiente');

---

-- TABLA: detalle_pedidos
CREATE TABLE detalle_pedidos (
    id INT AUTO_INCREMENT PRIMARY KEY,
    pedido_id INT NOT NULL,
    plato_id INT NOT NULL,
    cantidad INT NOT NULL DEFAULT 1,
    precio_unitario DECIMAL(10,2) NOT NULL,
    subtotal DECIMAL(10,2) AS (cantidad * precio_unitario) STORED,
    notas VARCHAR(255), 
    status ENUM('pendiente','preparando','listo','entregado') DEFAULT 'pendiente',
    FOREIGN KEY (pedido_id) REFERENCES pedidos(id) ON DELETE CASCADE,
    FOREIGN KEY (plato_id) REFERENCES platos(id) ON DELETE RESTRICT,
    INDEX idx_pedido(pedido_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO detalle_pedidos (pedido_id, plato_id, cantidad, precio_unitario, notas, status) VALUES
(1, 1, 2, 25.00, 'Término medio', 'entregado'),
(1, 2, 2, 35.00, 'Sin sal', 'entregado'),
(2, 3, 1, 18.00, 'Caliente', 'preparando');

-- FIN DEL SCRIPT
SELECT 'Base de datos SUMAK MIKUY finalizada. Las reservas no requieren mesa ni login del cliente.' AS mensaje;