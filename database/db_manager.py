"""
Gestión de la base de datos SQLite para el sistema de facturación.
"""
import sqlite3
import json
import datetime
from typing import List, Dict, Any, Optional, Tuple

from config.settings import DB_PATH
from config.logging_config import logger
from database.models import Invoice, Product


class DatabaseManager:
    """Clase para gestionar la base de datos local"""
    
    def __init__(self, db_path: str = DB_PATH):
        """
        Inicializa el gestor de base de datos.
        
        Args:
            db_path: Ruta del archivo de base de datos SQLite
        """
        self.db_path = db_path
        self.setup_database()
    
    def setup_database(self) -> None:
        """Configura las tablas necesarias en la base de datos"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Crear tabla para facturas locales
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS facturas_locales (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            cliente_nombre TEXT,
            cliente_identificacion TEXT,
            fecha TEXT,
            total REAL,
            productos TEXT,
            estado TEXT,
            pdf_path TEXT,
            siigo_id TEXT,
            fecha_actualizacion TEXT
        )
        ''')
        
        # Crear tabla para items de facturas
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS items_factura (
            id TEXT PRIMARY KEY,
            factura_id TEXT,
            producto_id TEXT,
            producto_nombre TEXT,
            cantidad REAL,
            precio REAL,
            impuesto_id TEXT,
            total REAL,
            FOREIGN KEY (factura_id) REFERENCES facturas_locales(id)
        )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Base de datos configurada correctamente")
    
    def save_invoice(self, invoice: Invoice, products: List[Product]) -> bool:
        """
        Guarda una factura y sus productos en la base de datos.
        
        Args:
            invoice: Objeto Invoice a guardar
            products: Lista de productos de la factura
            
        Returns:
            bool: True si se guarda correctamente, False en caso contrario
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Insertar factura
            cursor.execute('''
            INSERT INTO facturas_locales
            (id, cliente_nombre, cliente_identificacion, fecha, total, productos, estado, pdf_path, fecha_actualizacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                invoice.factura_id,
                invoice.nombre_cliente,
                invoice.identificacion,
                invoice.fecha_emision,
                invoice.valor_total,
                invoice.productos_facturados,
                invoice.estado,
                invoice.pdf_url or '',
                datetime.datetime.now().isoformat()
            ))
            
            # Insertar items de factura
            import time
            for product in products:
                item_id = f"{invoice.factura_id}-{product.nombre}-{time.time()}"
                cursor.execute('''
                INSERT INTO items_factura
                (id, factura_id, producto_nombre, cantidad, precio, total)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    item_id,
                    invoice.factura_id,
                    product.nombre,
                    product.cantidad,
                    product.precio,
                    product.precio * product.cantidad
                ))
            
            conn.commit()
            conn.close()
            logger.info(f"Factura {invoice.factura_id} guardada en base de datos local")
            return True
            
        except Exception as e:
            logger.error(f"Error al guardar factura en base de datos local: {e}")
            return False
    
    def update_invoice_status(self, invoice_id: str, status: str, siigo_id: Optional[str] = None) -> bool:
        """
        Actualiza el estado de una factura en la base de datos.
        
        Args:
            invoice_id: ID de la factura a actualizar
            status: Nuevo estado
            siigo_id: ID de Siigo (opcional)
            
        Returns:
            bool: True si se actualiza correctamente, False en caso contrario
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            if siigo_id:
                cursor.execute('''
                UPDATE facturas_locales 
                SET estado = ?, siigo_id = ?, fecha_actualizacion = ?
                WHERE id = ?
                ''', (status, siigo_id, datetime.datetime.now().isoformat(), invoice_id))
            else:
                cursor.execute('''
                UPDATE facturas_locales 
                SET estado = ?, fecha_actualizacion = ?
                WHERE id = ?
                ''', (status, datetime.datetime.now().isoformat(), invoice_id))
            
            conn.commit()
            conn.close()
            return True
            
        except Exception as e:
            logger.error(f"Error al actualizar estado de factura: {e}")
            return False
    
    def get_invoices(self, limit: int = 10) -> List[Dict[str, Any]]:
        """
        Obtiene las últimas facturas de la base de datos.
        
        Args:
            limit: Número máximo de facturas a devolver
            
        Returns:
            Lista de facturas como diccionarios
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row  # Para obtener resultados como diccionarios
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT id, cliente_nombre, cliente_identificacion, fecha, total, productos, 
                   estado, pdf_path, siigo_id, fecha_actualizacion
            FROM facturas_locales 
            ORDER BY fecha_actualizacion DESC 
            LIMIT ?
            ''', (limit,))
            
            invoices = [dict(row) for row in cursor.fetchall()]
            conn.close()
            
            return invoices
            
        except Exception as e:
            logger.error(f"Error al obtener facturas: {e}")
            return []
    
    def get_invoice_by_id(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        """
        Obtiene una factura por su ID.
        
        Args:
            invoice_id: ID de la factura a buscar
            
        Returns:
            Diccionario con los datos de la factura o None si no existe
        """
        try:
            conn = sqlite3.connect(self.db_path)
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            
            cursor.execute('''
            SELECT * FROM facturas_locales WHERE id = ?
            ''', (invoice_id,))
            
            invoice = cursor.fetchone()
            
            if invoice:
                # Obtener items de la factura
                cursor.execute('''
                SELECT * FROM items_factura WHERE factura_id = ?
                ''', (invoice_id,))
                
                items = [dict(row) for row in cursor.fetchall()]
                invoice_dict = dict(invoice)
                invoice_dict['items'] = items
                
                conn.close()
                return invoice_dict
            
            conn.close()
            return None
            
        except Exception as e:
            logger.error(f"Error al obtener factura {invoice_id}: {e}")
            return None