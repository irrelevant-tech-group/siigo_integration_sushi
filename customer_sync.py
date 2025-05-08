import os
import logging
import json
import time
from datetime import datetime
import sqlite3
import pandas as pd
from apis.siigo_api import SiigoAPIClient

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("customer_sync.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('customer_sync')

class CustomerSynchronizer:
    """Clase para sincronizar clientes entre nuestra base de datos local y Siigo"""
    
    def __init__(self, db_path="local_database.db"):
        """Inicializa el sincronizador con la base de datos local y la API de Siigo"""
        self.db_path = db_path
        self.siigo_api = SiigoAPIClient()
        self.setup_database()
        # Cargar datos de catálogo necesarios para la transformación
        self._load_catalog_data()
    
    
    def sync_from_siigo(self, full_sync=False):
        """
        Sincroniza clientes desde Siigo a la base de datos local
        
        Parámetros:
        - full_sync: Si es True, sincroniza todos los clientes. 
                     Si es False, solo sincroniza los clientes actualizados desde la última sincronización.
        """
        sync_log = {
            'sync_type': 'from_siigo',
            'start_time': datetime.now().isoformat(),
            'customers_created': 0,
            'customers_updated': 0,
            'customers_failed': 0,
            'details': []
        }
        
        try:
            # Obtener la fecha de la última sincronización
            last_sync_date = None
            if not full_sync:
                conn = sqlite3.connect(self.db_path)
                cursor = conn.cursor()
                cursor.execute('''
                SELECT end_time FROM customer_sync_log 
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
            
            # Configuración de paginación
            page = 1
            page_size = 100
            has_more_pages = True
            total_processed = 0

            while has_more_pages:
                logger.info(f"Obteniendo página {page} de clientes de Siigo (procesados hasta ahora: {total_processed})")
                
                try:
                    # Obtener página de clientes
                    customers_response = self.siigo_api.get_customers(page=page, page_size=page_size, **params)
                    
                    # Verificar si hay resultados
                    if not customers_response or 'results' not in customers_response:
                        logger.warning(f"No se encontraron resultados en la página {page}")
                        break
                    
                    current_page_results = customers_response.get('results', [])
                    if not current_page_results:
                        logger.info("No hay más clientes para procesar")
                        break
                    
                    # Procesar clientes de esta página
                    self._process_siigo_customers(current_page_results, sync_log)
                    
                    # Actualizar contadores y verificar si hay más páginas
                    total_processed += len(current_page_results)
                    
                    # Verificar si hay más páginas según la paginación
                    pagination = customers_response.get('pagination', {})
                    total_pages = pagination.get('total_pages', 0)
                    total_results = pagination.get('total_results', 0)
                    
                    logger.info(f"Progreso: {total_processed}/{total_results} clientes procesados")
                    
                    if page >= total_pages or total_processed >= total_results:
                        has_more_pages = False
                        logger.info("Se alcanzó el final de los resultados")
                    else:
                        page += 1
                    
                    # Pequeña pausa para no sobrecargar la API
                    time.sleep(0.5)
                    
                except Exception as e:
                    error_msg = f"Error procesando página {page}: {str(e)}"
                    logger.error(error_msg)
                    sync_log['details'].append(error_msg)
                    # Intentar continuar con la siguiente página
                    page += 1
                    continue
            
            logger.info(f"Sincronización desde Siigo completada: {sync_log['customers_created']} creados, "
                       f"{sync_log['customers_updated']} actualizados, {sync_log['customers_failed']} fallidos")
        
        except Exception as e:
            error_msg = f"Error en sincronización desde Siigo: {str(e)}"
            logger.error(error_msg)
            sync_log['details'].append(error_msg)
        
        finally:
            # Registrar resultados en el log de sincronización
            sync_log['end_time'] = datetime.now().isoformat()
            self._save_sync_log(sync_log)
            
            return sync_log
    
    def _process_siigo_customers(self, customers, sync_log):
        """Procesa los clientes de Siigo y los guarda en la base de datos local"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        for customer in customers:
            try:
                siigo_id = customer.get('id')
                identification = customer.get('identification')
                branch_office = customer.get('branch_office', 0)
                
                # Obtener nombre concatenado del array
                name_parts = customer.get('name', [])
                name = " ".join(name_parts) if name_parts else ""
                
                # Verificar si el cliente ya existe en la base de datos
                cursor.execute('SELECT id FROM siigo_customers WHERE id = ?', (siigo_id,))
                exists = cursor.fetchone()
                
                # Extraer datos de dirección si existe
                address_data = customer.get('address', {})
                address = address_data.get('address', '')
                city_data = address_data.get('city', {}) if address_data else {}
                city = city_data.get('city_name', '')
                state = city_data.get('state_name', '')
                country = city_data.get('country_name', '')
                postal_code = address_data.get('postal_code', '')
                
                # Preparar datos para guardar
                siigo_data = {
                    'id': siigo_id,
                    'identification': identification,
                    'branch_office': branch_office,
                    'name': name,
                    'commercial_name': customer.get('commercial_name', ''),
                    'person_type': customer.get('person_type', ''),
                    'id_type': customer.get('id_type', {}).get('code') if customer.get('id_type') else '',
                    'vat_responsible': 1 if customer.get('vat_responsible') else 0,
                    'fiscal_responsibilities': json.dumps(customer.get('fiscal_responsibilities', [])),
                    'address': address,
                    'city': city,
                    'state': state,
                    'country': country,
                    'postal_code': postal_code,
                    'last_updated': customer.get('metadata', {}).get('last_updated') or datetime.now().isoformat(),
                    'raw_data': json.dumps(customer)
                }
                
                if exists:
                    # Actualizar cliente existente
                    cursor.execute('''
                    UPDATE siigo_customers
                    SET identification = ?, branch_office = ?, name = ?, commercial_name = ?, 
                        person_type = ?, id_type = ?, vat_responsible = ?, fiscal_responsibilities = ?,
                        address = ?, city = ?, state = ?, country = ?, postal_code = ?,
                        last_updated = ?, raw_data = ?
                    WHERE id = ?
                    ''', (
                        siigo_data['identification'], siigo_data['branch_office'], siigo_data['name'], 
                        siigo_data['commercial_name'], siigo_data['person_type'], siigo_data['id_type'],
                        siigo_data['vat_responsible'], siigo_data['fiscal_responsibilities'],
                        siigo_data['address'], siigo_data['city'], siigo_data['state'], 
                        siigo_data['country'], siigo_data['postal_code'],
                        siigo_data['last_updated'], siigo_data['raw_data'], siigo_id
                    ))
                    sync_log['customers_updated'] += 1
                else:
                    # Insertar nuevo cliente
                    cursor.execute('''
                    INSERT INTO siigo_customers
                    (id, identification, branch_office, name, commercial_name, person_type, id_type,
                     vat_responsible, fiscal_responsibilities, address, city, state, country, 
                     postal_code, last_updated, raw_data)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ''', (
                        siigo_data['id'], siigo_data['identification'], siigo_data['branch_office'], 
                        siigo_data['name'], siigo_data['commercial_name'], siigo_data['person_type'],
                        siigo_data['id_type'], siigo_data['vat_responsible'], siigo_data['fiscal_responsibilities'],
                        siigo_data['address'], siigo_data['city'], siigo_data['state'], 
                        siigo_data['country'], siigo_data['postal_code'],
                        siigo_data['last_updated'], siigo_data['raw_data']
                    ))
                    sync_log['customers_created'] += 1
                
                # Verificar si existe un cliente local con la misma identificación
                cursor.execute('SELECT id FROM customers WHERE identification = ? AND branch_office = ?', 
                              (identification, branch_office))
                local_customer = cursor.fetchone()
                
                if local_customer:
                    # Actualizar referencia al cliente local
                    cursor.execute('''
                    UPDATE siigo_customers SET local_id = ?, local_synced = 1 WHERE id = ?
                    ''', (local_customer[0], siigo_id))
                    
                    # Actualizar referencia en el cliente local
                    cursor.execute('''
                    UPDATE customers SET siigo_id = ?, siigo_synced = 1, siigo_last_sync = ? WHERE id = ?
                    ''', (siigo_id, datetime.now().isoformat(), local_customer[0]))
            
            except Exception as e:
                error_msg = f"Error procesando cliente de Siigo {customer.get('identification')}: {str(e)}"
                logger.error(error_msg)
                sync_log['details'].append(error_msg)
                sync_log['customers_failed'] += 1
        
        conn.commit()
        conn.close()
    
    def sync_to_siigo(self, customer_ids=None):
        """
        Sincroniza clientes desde la base de datos local a Siigo
        
        Parámetros:
        - customer_ids: Lista de IDs de clientes locales para sincronizar. 
                       Si es None, sincroniza todos los clientes no sincronizados.
        """
        sync_log = {
            'sync_type': 'to_siigo',
            'start_time': datetime.now().isoformat(),
            'customers_created': 0,
            'customers_updated': 0,
            'customers_failed': 0,
            'details': []
        }
        
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Construir consulta según si se especificaron IDs o no
            if customer_ids:
                placeholders = ','.join(['?'] * len(customer_ids))
                cursor.execute(f'''
                SELECT id, identification, branch_office, name, person_type, id_type,
                       email, phone, address, city, state, country, postal_code, raw_data, siigo_id
                FROM customers
                WHERE id IN ({placeholders})
                ''', customer_ids)
            else:
                cursor.execute('''
                SELECT id, identification, branch_office, name, person_type, id_type,
                       email, phone, address, city, state, country, postal_code, raw_data, siigo_id
                FROM customers
                WHERE siigo_synced = 0 OR siigo_id IS NULL
                ''')
            
            customers = cursor.fetchall()
            logger.info(f"Sincronizando {len(customers)} clientes locales a Siigo")
            
            for customer_data in customers:
                customer = {
                    'id': customer_data[0],
                    'identification': customer_data[1],
                    'branch_office': customer_data[2],
                    'name': customer_data[3],
                    'person_type': customer_data[4],
                    'id_type': customer_data[5],
                    'email': customer_data[6],
                    'phone': customer_data[7],
                    'address': customer_data[8],
                    'city': customer_data[9],
                    'state': customer_data[10],
                    'country': customer_data[11],
                    'postal_code': customer_data[12],
                    'raw_data': json.loads(customer_data[13]) if customer_data[13] else None,
                    'siigo_id': customer_data[14]
                }
                
                # Transformar cliente al formato de Siigo
                siigo_customer = self._transform_to_siigo_format(customer)
                
                if customer['siigo_id']:
                    # Actualizar cliente existente
                    try:
                        result = self.siigo_api.update_customer(customer['siigo_id'], siigo_customer)
                        
                        # Actualizar estado de sincronización
                        cursor.execute('''
                        UPDATE customers SET siigo_synced = 1, siigo_last_sync = ? WHERE id = ?
                        ''', (datetime.now().isoformat(), customer['id']))
                        
                        sync_log['customers_updated'] += 1
                        logger.info(f"Cliente actualizado en Siigo: {customer['identification']}")
                    except Exception as e:
                        error_msg = f"Error actualizando cliente {customer['identification']} en Siigo: {str(e)}"
                        logger.error(error_msg)
                        sync_log['details'].append(error_msg)
                        sync_log['customers_failed'] += 1
                else:
                    # Crear nuevo cliente
                    try:
                        result = self.siigo_api.create_customer(siigo_customer)
                        siigo_id = result.get('id')
                        
                        # Guardar ID de Siigo en cliente local
                        cursor.execute('''
                        UPDATE customers SET siigo_id = ?, siigo_synced = 1, siigo_last_sync = ? WHERE id = ?
                        ''', (siigo_id, datetime.now().isoformat(), customer['id']))
                        
                        # Registrar cliente en tabla de siigo_customers
                        # Extraer campos relevantes de la respuesta
                        name_parts = result.get('name', [])
                        name = " ".join(name_parts) if name_parts else ""
                        
                        # Extraer datos de dirección si existe
                        address_data = result.get('address', {})
                        address = address_data.get('address', '')
                        city_data = address_data.get('city', {}) if address_data else {}
                        city = city_data.get('city_name', '')
                        state = city_data.get('state_name', '')
                        country = city_data.get('country_name', '')
                        postal_code = address_data.get('postal_code', '')
                        
                        cursor.execute('''
                        INSERT INTO siigo_customers 
                        (id, identification, branch_office, name, commercial_name, person_type, id_type,
                         vat_responsible, fiscal_responsibilities, address, city, state, country, 
                         postal_code, last_updated, local_synced, local_id, raw_data)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1, ?, ?)
                        ''', (
                            siigo_id, 
                            result.get('identification'), 
                            result.get('branch_office', 0), 
                            name,
                            result.get('commercial_name', ''),
                            result.get('person_type', ''),
                            result.get('id_type', {}).get('code') if result.get('id_type') else '',
                            1 if result.get('vat_responsible') else 0,
                            json.dumps(result.get('fiscal_responsibilities', [])),
                            address, city, state, country, postal_code,
                            datetime.now().isoformat(),
                            customer['id'],
                            json.dumps(result)
                        ))
                        
                        sync_log['customers_created'] += 1
                        logger.info(f"Cliente creado en Siigo: {customer['identification']} con ID {siigo_id}")
                    except Exception as e:
                        error_msg = f"Error creando cliente {customer['identification']} en Siigo: {str(e)}"
                        logger.error(error_msg)
                        sync_log['details'].append(error_msg)
                        sync_log['customers_failed'] += 1
            
            conn.commit()
            
            logger.info(f"Sincronización a Siigo completada: {sync_log['customers_created']} creados, "
                       f"{sync_log['customers_updated']} actualizados, {sync_log['customers_failed']} fallidos")
        
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
    
    def _transform_to_siigo_format(self, customer):
        """Transforma un cliente local al formato requerido por Siigo"""
        
        # Definir tipo de persona Person/Company
        person_type = customer['person_type']
        if not person_type or person_type.lower() not in ['person', 'company']:
            # Por defecto asumimos persona natural
            person_type = 'Person'
        
        # Verificar tipo de documento
        id_type = customer['id_type']
        if not id_type:
            # Por defecto usar cédula para personas naturales y NIT para empresas
            id_type = '13' if person_type == 'Person' else '31'
        
        # Preparar nombre según tipo de persona
        name_parts = customer['name'].split()
        if person_type == 'Person':
            # Para personas naturales, dividir en nombre y apellido
            if len(name_parts) > 1:
                first_name = name_parts[0]
                last_name = " ".join(name_parts[1:])
                name = [first_name, last_name]
            else:
                # Si solo hay una palabra, usar como nombre y apellido en blanco
                name = [customer['name'], ""]
        else:
            # Para empresas, usar el nombre completo como un solo elemento
            name = [customer['name']]
        
        # Preparar datos de ciudad
        city = {
            "country_code": customer.get('country', 'Co'),
            "state_code": customer.get('state', '11'),
            "city_code": customer.get('city', '11001')
        }
        
        # Construir objeto de cliente para Siigo
        siigo_customer = {
            "type": "Customer",  # Tipo por defecto
            "person_type": person_type,
            "id_type": id_type,
            "identification": customer['identification'],
            "branch_office": customer.get('branch_office', 0),
            "name": name,
            "active": True,
        }
        
        # Agregar dirección
        if customer.get('address'):
            siigo_customer["address"] = {
                "address": customer['address'],
                "city": city,
                "postal_code": customer.get('postal_code', '')
            }
        
        # Agregar teléfono si existe
        if customer.get('phone'):
            siigo_customer["phones"] = [
                {
                    "number": customer['phone']
                }
            ]
        
        # Agregar al menos un contacto (obligatorio)
        contact_name = name[0]
        contact_email = customer.get('email', '')
        
        siigo_customer["contacts"] = [
            {
                "first_name": contact_name,
                "last_name": name[1] if len(name) > 1 else "",
                "email": contact_email
            }
        ]
        
        # Agregar responsabilidades fiscales (siempre debe tener al menos una)
        siigo_customer["fiscal_responsibilities"] = [
            {
                "code": "R-99-PN"  # No aplica - Otros (valor por defecto)
            }
        ]
        
        return siigo_customer
    
    def add_local_customer(self, customer_data):
        """
        Agrega un cliente a la base de datos local
        
        Parámetros:
        - customer_data: Diccionario con los datos del cliente
        """
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Verificar si ya existe un cliente con la misma identificación y sucursal
            cursor.execute('SELECT id FROM customers WHERE identification = ? AND branch_office = ?', 
                          (customer_data['identification'], customer_data.get('branch_office', 0)))
            existing = cursor.fetchone()
            
            if existing:
                # Actualizar cliente existente
                query = '''
                UPDATE customers
                SET name = ?, person_type = ?, id_type = ?, email = ?, phone = ?,
                    address = ?, city = ?, state = ?, country = ?, postal_code = ?,
                    last_updated = ?, raw_data = ?
                WHERE identification = ? AND branch_office = ?
                '''
                
                cursor.execute(query, (
                    customer_data['name'],
                    customer_data.get('person_type', ''),
                    customer_data.get('id_type', ''),
                    customer_data.get('email', ''),
                    customer_data.get('phone', ''),
                    customer_data.get('address', ''),
                    customer_data.get('city', ''),
                    customer_data.get('state', ''),
                    customer_data.get('country', ''),
                    customer_data.get('postal_code', ''),
                    datetime.now().isoformat(),
                    json.dumps(customer_data),
                    customer_data['identification'],
                    customer_data.get('branch_office', 0)
                ))
                
                customer_id = existing[0]
                logger.info(f"Cliente actualizado en base local: {customer_data['identification']}")
            else:
                # Crear cliente nuevo
                customer_id = customer_data.get('id', str(int(time.time() * 1000)))  # Generar ID si no existe
                
                query = '''
                INSERT INTO customers
                (id, identification, branch_office, name, person_type, id_type, email, phone,
                 address, city, state, country, postal_code, last_updated, raw_data)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                '''
                
                cursor.execute(query, (
                    customer_id,
                    customer_data['identification'],
                    customer_data.get('branch_office', 0),
                    customer_data['name'],
                    customer_data.get('person_type', ''),
                    customer_data.get('id_type', ''),
                    customer_data.get('email', ''),
                    customer_data.get('phone', ''),
                    customer_data.get('address', ''),
                    customer_data.get('city', ''),
                    customer_data.get('state', ''),
                    customer_data.get('country', ''),
                    customer_data.get('postal_code', ''),
                    datetime.now().isoformat(),
                    json.dumps(customer_data)
                ))
                
                logger.info(f"Cliente creado en base local: {customer_data['identification']}")
            
            conn.commit()
            conn.close()
            
            return customer_id
        
        except Exception as e:
            logger.error(f"Error al agregar cliente local: {str(e)}")
            raise
    
    def import_customers_from_csv(self, csv_path, mappings=None):
        """
        Importa clientes desde un archivo CSV
        
        Parámetros:
        - csv_path: Ruta al archivo CSV
        - mappings: Diccionario con mapeos de columnas CSV a campos de cliente
        """
        if not mappings:
            # Mapeos por defecto
            mappings = {
                'identification': 'identification',
                'name': 'name',
                'person_type': 'person_type',
                'id_type': 'id_type',
                'email': 'email',
                'phone': 'phone',
                'address': 'address',
                'city': 'city',
                'state': 'state',
                'country': 'country',
                'postal_code': 'postal_code'
            }
        
        try:
            # Leer CSV
            df = pd.read_csv(csv_path)
            
            # Convertir a lista de diccionarios con los campos mapeados
            customers = []
            for _, row in df.iterrows():
                customer = {}
                for target_field, source_field in mappings.items():
                    if source_field in row:
                        customer[target_field] = row[source_field]
                
                # Validar campos mínimos
                if 'identification' in customer and 'name' in customer:
                    customers.append(customer)
                else:
                    logger.warning(f"Cliente ignorado por falta de campos obligatorios: {customer}")
            
            # Agregar clientes a la base local
            added_count = 0
            for customer in customers:
                try:
                    self.add_local_customer(customer)
                    added_count += 1
                except Exception as e:
                    logger.error(f"Error al importar cliente {customer.get('identification')}: {str(e)}")
            
            logger.info(f"Importación CSV completada: {added_count} de {len(customers)} clientes importados")
            return added_count
        
        except Exception as e:
            logger.error(f"Error en importación de CSV: {str(e)}")
            raise
    
    def _save_sync_log(self, sync_log):
        """Guarda el log de sincronización en la base de datos"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        cursor.execute('''
        INSERT INTO customer_sync_log (sync_type, start_time, end_time, customers_created, customers_updated, customers_failed, details)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ''', (
            sync_log['sync_type'],
            sync_log['start_time'],
            sync_log['end_time'],
            sync_log['customers_created'],
            sync_log['customers_updated'],
            sync_log['customers_failed'],
            json.dumps(sync_log['details'])
        ))
        
        conn.commit()
        conn.close()


# Ejemplo de uso
if __name__ == "__main__":
    try:
        # Inicializar sincronizador
        synchronizer = CustomerSynchronizer()
        
        # Para pruebas: Sincronizar desde Siigo
        print("Sincronizando clientes desde Siigo...")
        sync_result = synchronizer.sync_from_siigo(full_sync=True)
        print(f"Resultado: {sync_result['customers_created']} creados, "
              f"{sync_result['customers_updated']} actualizados, "
              f"{sync_result['customers_failed']} fallidos")
        
        # Para pruebas: Importar clientes de un CSV (si existe)
        csv_path = "clientes_ejemplo.csv"
        if os.path.exists(csv_path):
            print(f"\nImportando clientes desde {csv_path}...")
            imported = synchronizer.import_customers_from_csv(csv_path)
            print(f"Clientes importados: {imported}")
            ''' 
            Revisar si hay forma de primero revisar que los clientes que trajeron
            '''
            # Sincronizar a Siigo los clientes recién importados
            print("\nSincronizando clientes importados a Siigo...")
            sync_result = synchronizer.sync_to_siigo()
            print(f"Resultado: {sync_result['customers_created']} creados, "
                 f"{sync_result['customers_updated']} actualizados, "
                 f"{sync_result['customers_failed']} fallidos")
    
    except Exception as e:
        print(f"Error en ejemplo de uso: {str(e)}")