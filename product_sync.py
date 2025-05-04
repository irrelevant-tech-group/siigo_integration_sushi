import os
import logging
import json
import time
from datetime import datetime
import sqlite3
import pandas as pd
from siigo_api import SiigoAPIClient

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("product_sync.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('product_sync')

class ProductSynchronizer:
    """Clase para sincronizar productos entre nuestra base de datos local y Siigo"""
    
    def __init__(self, db_path="local_database.db"):
        """Inicializa el sincronizador con la base de datos local y la API de Siigo"""
        self.db_path = db_path
        self.siigo_api = SiigoAPIClient()
        self.setup_database()
        # Cargar datos de catálogo necesarios para la transformación
        self._load_catalog_data()
    
    def setup_database(self):
        """Configura la base de datos local si no existe"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Crear tabla para productos locales
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS products (
            id TEXT PRIMARY KEY,
            code TEXT UNIQUE,
            name TEXT,
            description TEXT,
            price REAL,
            tax_included INTEGER,
            tax_rate REAL,
            category TEXT,
            last_updated TEXT,
            siigo_id TEXT,
            siigo_synced INTEGER DEFAULT 0,
            siigo_last_sync TEXT,
            raw_data TEXT
        )
        ''')
        
        # Crear tabla para productos de Siigo
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS siigo_products (
            id TEXT PRIMARY KEY,
            code TEXT UNIQUE,
            name TEXT,
            account_group INTEGER,
            tax_classification TEXT,
            tax_included INTEGER,
            last_updated TEXT,
            local_synced INTEGER DEFAULT 0,
            local_id TEXT,
            raw_data TEXT
        )
        ''')
        
        # Crear tabla para registro de sincronización
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS sync_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sync_type TEXT,
            start_time TEXT,
            end_time TEXT,
            products_created INTEGER,
            products_updated INTEGER,
            products_failed INTEGER,
            details TEXT
        )
        ''')
        
        # Crear tabla para almacenar datos de catálogo
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS catalog_data (
            catalog_type TEXT,
            catalog_id TEXT,
            name TEXT,
            additional_data TEXT,
            PRIMARY KEY (catalog_type, catalog_id)
        )
        ''')
        
        conn.commit()
        conn.close()
    
    def _load_catalog_data(self):
        """Carga datos de catálogo desde Siigo para usarlos en transformaciones"""
        try:
            # Obtener grupos de inventario
            account_groups = self.siigo_api.get_account_groups()
            self._save_catalog_data("account_group", account_groups)
            
            # Obtener impuestos
            taxes = self.siigo_api.get_taxes()
            self._save_catalog_data("tax", taxes)
            
            logger.info("Datos de catálogo cargados correctamente")
        except Exception as e:
            logger.error(f"Error al cargar datos de catálogo: {str(e)}")
    
    def _save_catalog_data(self, catalog_type, items):
        """Guarda datos de catálogo en la base de datos local"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for item in items:
            item_id = str(item.get('id'))
            name = item.get('name', '')
            additional_data = json.dumps(item)
            
            cursor.execute('''
            INSERT OR REPLACE INTO catalog_data (catalog_type, catalog_id, name, additional_data)
            VALUES (?, ?, ?, ?)
            ''', (catalog_type, item_id, name, additional_data))
        
        conn.commit()
        conn.close()
    
    def _get_catalog_item(self, catalog_type, item_id=None, name=None):
        """Obtiene un item de catálogo por id o nombre"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        if item_id:
            cursor.execute('''
            SELECT catalog_id, name, additional_data FROM catalog_data
            WHERE catalog_type = ? AND catalog_id = ?
            ''', (catalog_type, str(item_id)))
        elif name:
            cursor.execute('''
            SELECT catalog_id, name, additional_data FROM catalog_data
            WHERE catalog_type = ? AND name LIKE ?
            ''', (catalog_type, f"%{name}%"))
        else:
            cursor.execute('''
            SELECT catalog_id, name, additional_data FROM catalog_data
            WHERE catalog_type = ?
            ''', (catalog_type,))
        
        results = cursor.fetchall()
        conn.close()
        
        if not results:
            return None
        
        if item_id or name:
            # Devolver solo el primer resultado como diccionario
            item_id, name, additional_data = results[0]
            return {
                'id': item_id,
                'name': name,
                'data': json.loads(additional_data)
            }
        else:
            # Devolver todos los resultados como lista de diccionarios
            return [
                {'id': r[0], 'name': r[1], 'data': json.loads(r[2])}
                for r in results
            ]
    
    def sync_from_siigo(self, full_sync=False):
        """
        Sincroniza productos desde Siigo a la base de datos local
        
        Parámetros:
        - full_sync: Si es True, sincroniza todos los productos. 
                     Si es False, solo sincroniza los productos actualizados desde la última sincronización.
        """
        sync_log = {
            'sync_type': 'from_siigo',
            'start_time': datetime.now().isoformat(),
            'products_created': 0,
            'products_updated': 0,
            'products_failed': 0,
            'details': []
        }
        
        try:
            # Obtener la fecha de la última sincronización
            last_sync_date = None
            if not full_sync:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('''
                SELECT end_time FROM sync_log 
                WHERE sync_type = 'from_siigo' AND end_time IS NOT NULL
                ORDER BY end_time DESC LIMIT 1
                ''')
                result = cursor.fetchone()
                conn.close()
                
                if result:
                    last_sync_date = result[0]
                    # Convertir a formato de fecha adecuado para la API
                    last_sync_date = datetime.fromisoformat(last_sync_date).strftime('%Y-%m-%d')
            
            # Parámetros para la consulta
            params = {}
            if last_sync_date:
                params['updated_start'] = last_sync_date
            
            # Obtener productos paginados
            page = 1
            page_size = 100
            total_pages = 1  # Se actualizará con la primera respuesta
            
            while page <= total_pages:
                logger.info(f"Obteniendo productos de Siigo - Página {page} de {total_pages}")
                
                # Obtener página de productos
                products_response = self.siigo_api.get_products(page=page, page_size=page_size, **params)
                
                # Actualizar total de páginas si es la primera página
                if page == 1 and 'pagination' in products_response:
                    total_results = products_response['pagination']['total_results']
                    total_pages = (total_results + page_size - 1) // page_size
                    logger.info(f"Total de productos a sincronizar: {total_results}")
                
                # Procesar productos de esta página
                if 'results' in products_response:
                    self._process_siigo_products(products_response['results'], sync_log)
                
                # Pasar a la siguiente página
                page += 1
                
                # Pequeña pausa para no sobrecargar la API
                time.sleep(0.5)
            
            logger.info(f"Sincronización desde Siigo completada: {sync_log['products_created']} creados, "
                       f"{sync_log['products_updated']} actualizados, {sync_log['products_failed']} fallidos")
        
        except Exception as e:
            error_msg = f"Error en sincronización desde Siigo: {str(e)}"
            logger.error(error_msg)
            sync_log['details'].append(error_msg)
        
        finally:
            # Registrar resultados en el log de sincronización
            sync_log['end_time'] = datetime.now().isoformat()
            self._save_sync_log(sync_log)
            
            return sync_log
    
    def _process_siigo_products(self, products, sync_log):
        """Procesa los productos de Siigo y los guarda en la base de datos local"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for product in products:
            try:
                siigo_id = product.get('id')
                code = product.get('code')
                
                # Verificar si el producto ya existe en la base de datos
                cursor.execute('SELECT id FROM siigo_products WHERE id = ?', (siigo_id,))
                exists = cursor.fetchone()
                
                # Preparar datos para guardar
                siigo_data = {
                    'id': siigo_id,
                    'code': code,
                    'name': product.get('name', ''),
                    'account_group': product.get('account_group', {}).get('id') if product.get('account_group') else None,
                    'tax_classification': product.get('tax_classification', 'Taxed'),
                    'tax_included': 1 if product.get('tax_included') else 0,
                    'last_updated': product.get('metadata', {}).get('last_updated') or datetime.now().isoformat(),
                    'raw_data': json.dumps(product)
                }
                
                if exists:
                    # Actualizar producto existente
                    cursor.execute('''
                    UPDATE siigo_products
                    SET code = ?, name = ?, account_group = ?, tax_classification = ?,
                        tax_included = ?, last_updated = ?, raw_data = ?
                    WHERE id = ?
                    ''', (
                        siigo_data['code'], siigo_data['name'], siigo_data['account_group'],
                        siigo_data['tax_classification'], siigo_data['tax_included'],
                        siigo_data['last_updated'], siigo_data['raw_data'], siigo_id
                    ))
                    sync_log['products_updated'] += 1
                else:
                    # Insertar nuevo producto
                    cursor.execute('''
                    INSERT INTO siigo_products
                    (id, code, name, account_group, tax_classification, tax_included, last_updated, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        siigo_data['id'], siigo_data['code'], siigo_data['name'], siigo_data['account_group'],
                        siigo_data['tax_classification'], siigo_data['tax_included'],
                        siigo_data['last_updated'], siigo_data['raw_data']
                    ))
                    sync_log['products_created'] += 1
                
                # Verificar si existe un producto local con el mismo código
                cursor.execute('SELECT id FROM products WHERE code = ?', (code,))
                local_product = cursor.fetchone()
                
                if local_product:
                    # Actualizar referencia al producto local
                    cursor.execute('''
                    UPDATE siigo_products SET local_id = ?, local_synced = 1 WHERE id = ?
                    ''', (local_product[0], siigo_id))
                    
                    # Actualizar referencia en el producto local
                    cursor.execute('''
                    UPDATE products SET siigo_id = ?, siigo_synced = 1, siigo_last_sync = ? WHERE id = ?
                    ''', (siigo_id, datetime.now().isoformat(), local_product[0]))
            
            except Exception as e:
                error_msg = f"Error procesando producto de Siigo {product.get('code')}: {str(e)}"
                logger.error(error_msg)
                sync_log['details'].append(error_msg)
                sync_log['products_failed'] += 1
        
        conn.commit()
        conn.close()
    
    def sync_to_siigo(self, product_ids=None):
        """
        Sincroniza productos desde la base de datos local a Siigo
        
        Parámetros:
        - product_ids: Lista de IDs de productos locales para sincronizar. 
                      Si es None, sincroniza todos los productos no sincronizados.
        """
        sync_log = {
            'sync_type': 'to_siigo',
            'start_time': datetime.now().isoformat(),
            'products_created': 0,
            'products_updated': 0,
            'products_failed': 0,
            'details': []
        }
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Construir consulta según si se especificaron IDs o no
            if product_ids:
                placeholders = ','.join(['?'] * len(product_ids))
                cursor.execute(f'''
                SELECT id, code, name, description, price, tax_included, tax_rate, category, raw_data, siigo_id
                FROM products
                WHERE id IN ({placeholders})
                ''', product_ids)
            else:
                cursor.execute('''
                SELECT id, code, name, description, price, tax_included, tax_rate, category, raw_data, siigo_id
                FROM products
                WHERE siigo_synced = 0 OR siigo_id IS NULL
                ''')
            
            products = cursor.fetchall()
            logger.info(f"Sincronizando {len(products)} productos locales a Siigo")
            
            for product_data in products:
                product = {
                    'id': product_data[0],
                    'code': product_data[1],
                    'name': product_data[2],
                    'description': product_data[3],
                    'price': product_data[4],
                    'tax_included': bool(product_data[5]),
                    'tax_rate': product_data[6],
                    'category': product_data[7],
                    'raw_data': json.loads(product_data[8]) if product_data[8] else None,
                    'siigo_id': product_data[9]
                }
                
                # Transformar producto al formato de Siigo
                siigo_product = self._transform_to_siigo_format(product)
                
                if product['siigo_id']:
                    # Actualizar producto existente
                    try:
                        result = self.siigo_api.update_product(product['siigo_id'], siigo_product)
                        
                        # Actualizar estado de sincronización
                        cursor.execute('''
                        UPDATE products SET siigo_synced = 1, siigo_last_sync = ? WHERE id = ?
                        ''', (datetime.now().isoformat(), product['id']))
                        
                        sync_log['products_updated'] += 1
                        logger.info(f"Producto actualizado en Siigo: {product['code']}")
                    except Exception as e:
                        error_msg = f"Error actualizando producto {product['code']} en Siigo: {str(e)}"
                        logger.error(error_msg)
                        sync_log['details'].append(error_msg)
                        sync_log['products_failed'] += 1
                else:
                    # Crear nuevo producto
                    try:
                        result = self.siigo_api.create_product(siigo_product)
                        siigo_id = result.get('id')
                        
                        # Guardar ID de Siigo en producto local
                        cursor.execute('''
                        UPDATE products SET siigo_id = ?, siigo_synced = 1, siigo_last_sync = ? WHERE id = ?
                        ''', (siigo_id, datetime.now().isoformat(), product['id']))
                        
                        # Registrar producto en tabla de siigo_products
                        cursor.execute('''
                        INSERT INTO siigo_products 
                        (id, code, name, account_group, tax_classification, tax_included, last_updated, local_synced, local_id, raw_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                        ''', (
                            siigo_id, 
                            product['code'], 
                            product['name'], 
                            siigo_product.get('account_group'),
                            siigo_product.get('tax_classification', 'Taxed'),
                            1 if siigo_product.get('tax_included') else 0,
                            datetime.now().isoformat(),
                            product['id'],
                            json.dumps(result)
                        ))
                        
                        sync_log['products_created'] += 1
                        logger.info(f"Producto creado en Siigo: {product['code']} con ID {siigo_id}")
                    except Exception as e:
                        error_msg = f"Error creando producto {product['code']} en Siigo: {str(e)}"
                        logger.error(error_msg)
                        sync_log['details'].append(error_msg)
                        sync_log['products_failed'] += 1
            
            conn.commit()
            
            logger.info(f"Sincronización a Siigo completada: {sync_log['products_created']} creados, "
                       f"{sync_log['products_updated']} actualizados, {sync_log['products_failed']} fallidos")
        
        except Exception as e:
            error_msg = f"Error en sincronización a Siigo: {str(e)}"
            logger.error(error_msg)
            sync_log['details'].append(error_msg)
        
        finally:
            if 'conn' in locals():
                conn.close()
            
            # Registrar resultados en el log de sincronización
            sync_log['end_time'] = datetime.now().isoformat()
            self._save_sync_log(sync_log)
            
            return sync_log
    
    def _transform_to_siigo_format(self, product):
        """Transforma un producto local al formato requerido por Siigo"""
        # Buscar grupo de inventario según la categoría
        account_group = self._find_account_group(product['category'])
        if not account_group:
            # Usar el primer grupo de inventario como fallback
            all_groups = self._get_catalog_item('account_group')
            account_group = all_groups[0]['id'] if all_groups else "1253"  # ID de ejemplo, habría que ajustarlo
        
        # Buscar impuesto según la tasa
        tax_id = self._find_tax_by_rate(product['tax_rate'])
        
        # Determinar clasificación tributaria
        tax_classification = "Taxed"  # Valor por defecto: Gravado
        if product['tax_rate'] == 0:
            # Tasa cero puede significar Exento o Excluido, usamos Excluido como ejemplo
            tax_classification = "Excluded"
        
        # Construir objeto de producto para Siigo
        siigo_product = {
            "code": product['code'],
            "name": product['name'],
            "account_group": int(account_group),
            "type": "Product",  # Por defecto es producto, podría ser Service o ConsumerGood
            "stock_control": True,  # Por defecto asumimos control de inventario
            "active": True,
            "tax_classification": tax_classification,
            "tax_included": product['tax_included'],
        }
        
        # Agregar descripción si existe
        if product['description']:
            siigo_product["description"] = product['description']
        
        # Agregar impuestos si existen
        if tax_id:
            siigo_product["taxes"] = [{"id": int(tax_id)}]
        
        # Agregar precios
        siigo_product["prices"] = [{
            "currency_code": "COP",  # Moneda por defecto, podría ser parametrizable
            "price_list": [
                {
                    "position": 1,
                    "value": float(product['price'])
                }
            ]
        }]
        
        return siigo_product
    
    def _find_account_group(self, category_name):
        """Busca un grupo de inventario que coincida con la categoría del producto"""
        if not category_name:
            return None
        
        # Buscar el grupo por nombre
        account_group = self._get_catalog_item('account_group', name=category_name)
        
        if account_group:
            return account_group['id']
        
        # Si no se encuentra, devuelve None
        return None
    
    def _find_tax_by_rate(self, tax_rate):
        """Busca un impuesto que coincida con la tasa de impuesto del producto"""
        if tax_rate is None:
            return None
        
        # Obtener todos los impuestos
        all_taxes = self._get_catalog_item('tax')
        
        if not all_taxes:
            return None
        
        # Buscar el impuesto con la tasa más cercana
        closest_tax = None
        min_diff = float('inf')
        
        for tax in all_taxes:
            tax_data = tax['data']
            if tax_data.get('type') != 'IVA':
                continue
            
            percentage = tax_data.get('percentage', 0)
            diff = abs(percentage - tax_rate)
            
            if diff < min_diff:
                min_diff = diff
                closest_tax = tax['id']
        
        return closest_tax
    
    def add_local_product(self, product_data):
        """
        Agrega un producto a la base de datos local
        
        Parámetros:
        - product_data: Diccionario con los datos del producto
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Verificar si ya existe un producto con el mismo código
            cursor.execute('SELECT id FROM products WHERE code = ?', (product_data['code'],))
            existing = cursor.fetchone()
            
            if existing:
                # Actualizar producto existente
                query = '''
                UPDATE products
                SET name = ?, description = ?, price = ?, tax_included = ?, tax_rate = ?, 
                    category = ?, last_updated = ?, raw_data = ?
                WHERE code = ?
                '''
                
                cursor.execute(query, (
                    product_data['name'],
                    product_data.get('description', ''),
                    product_data['price'],
                    1 if product_data.get('tax_included', False) else 0,
                    product_data.get('tax_rate', 0),
                    product_data.get('category', ''),
                    datetime.now().isoformat(),
                    json.dumps(product_data),
                    product_data['code']
                ))
                
                product_id = existing[0]
                logger.info(f"Producto actualizado en base local: {product_data['code']}")
            else:
                # Crear producto nuevo
                product_id = product_data.get('id', str(int(time.time() * 1000)))  # Generar ID si no existe
                
                query = '''
                INSERT INTO products
                (id, code, name, description, price, tax_included, tax_rate, category, last_updated, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
                
                cursor.execute(query, (
                    product_id,
                    product_data['code'],
                    product_data['name'],
                    product_data.get('description', ''),
                    product_data['price'],
                    1 if product_data.get('tax_included', False) else 0,
                    product_data.get('tax_rate', 0),
                    product_data.get('category', ''),
                    datetime.now().isoformat(),
                    json.dumps(product_data)
                ))
                
                logger.info(f"Producto creado en base local: {product_data['code']}")
            
            conn.commit()
            conn.close()
            
            return product_id
        
        except Exception as e:
            logger.error(f"Error al agregar producto local: {str(e)}")
            raise
    
    def import_products_from_csv(self, csv_path, mappings=None):
        """
        Importa productos desde un archivo CSV
        
        Parámetros:
        - csv_path: Ruta al archivo CSV
        - mappings: Diccionario con mapeos de columnas CSV a campos de producto
        """
        if not mappings:
            # Mapeos por defecto
            mappings = {
                'code': 'code',
                'name': 'name',
                'description': 'description',
                'price': 'price',
                'tax_included': 'tax_included',
                'tax_rate': 'tax_rate',
                'category': 'category'
            }
        
        try:
            # Leer CSV
            df = pd.read_csv(csv_path)
            
            # Convertir a lista de diccionarios con los campos mapeados
            products = []
            for _, row in df.iterrows():
                product = {}
                for target_field, source_field in mappings.items():
                    if source_field in row:
                        product[target_field] = row[source_field]
                
                # Validar campos mínimos
                if 'code' in product and 'name' in product and 'price' in product:
                    products.append(product)
                else:
                    logger.warning(f"Producto ignorado por falta de campos obligatorios: {product}")
            
            # Agregar productos a la base local
            added_count = 0
            for product in products:
                try:
                    self.add_local_product(product)
                    added_count += 1
                except Exception as e:
                    logger.error(f"Error al importar producto {product.get('code')}: {str(e)}")
            
            logger.info(f"Importación CSV completada: {added_count} de {len(products)} productos importados")
            return added_count
        
        except Exception as e:
            logger.error(f"Error en importación de CSV: {str(e)}")
            raise
    
    def _save_sync_log(self, sync_log):
        """Guarda el log de sincronización en la base de datos"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO sync_log (sync_type, start_time, end_time, products_created, products_updated, products_failed, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            sync_log['sync_type'],
            sync_log['start_time'],
            sync_log['end_time'],
            sync_log['products_created'],
            sync_log['products_updated'],
            sync_log['products_failed'],
            json.dumps(sync_log['details'])
        ))
        
        conn.commit()
        conn.close()


# Ejemplo de uso
if __name__ == "__main__":
    try:
        # Inicializar sincronizador
        synchronizer = ProductSynchronizer()
        
        # Para pruebas: Sincronizar desde Siigo
        print("Sincronizando productos desde Siigo...")
        sync_result = synchronizer.sync_from_siigo(full_sync=True)
        print(f"Resultado: {sync_result['products_created']} creados, "
              f"{sync_result['products_updated']} actualizados, "
              f"{sync_result['products_failed']} fallidos")
        
        # Para pruebas: Importar productos de un CSV (si existe)
        csv_path = "productos_ejemplo.csv"
        if os.path.exists(csv_path):
            print(f"\nImportando productos desde {csv_path}...")
            imported = synchronizer.import_products_from_csv(csv_path)
            print(f"Productos importados: {imported}")
            
            # Sincronizar a Siigo los productos recién importados
            print("\nSincronizando productos importados a Siigo...")
            sync_result = synchronizer.sync_to_siigo()
            print(f"Resultado: {sync_result['products_created']} creados, "
                 f"{sync_result['products_updated']} actualizados, "
                 f"{sync_result['products_failed']} fallidos")
    
    except Exception as e:
        print(f"Error en ejemplo de uso: {str(e)}")