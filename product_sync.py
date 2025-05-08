import os
import logging
import json
import time
from datetime import datetime
import pandas as pd
from apis.siigo_api import SiigoAPIClient

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
    """Clase para sincronizar productos desde Siigo a Google Sheets"""
    
    def __init__(self):
        """Inicializa el sincronizador con la API de Siigo"""
        self.siigo_api = SiigoAPIClient()
        self._load_catalog_data()
    
    def _load_catalog_data(self):
        """Carga datos de catálogo desde Siigo para usarlos en transformaciones"""
        try:
            # Obtener grupos de inventario
            self.account_groups = self.siigo_api.get_account_groups() or []
            
            # Obtener impuestos
            self.taxes = self.siigo_api.get_taxes() or []
            
            logger.info("Datos de catálogo cargados correctamente")
        except Exception as e:
            logger.error(f"Error al cargar datos de catálogo: {str(e)}")
            self.account_groups = []
            self.taxes = []
    
    def _get_account_group_name(self, group_id):
        """Obtiene el nombre de un grupo de inventario por su ID"""
        if not group_id:
            return ""
        
        for group in self.account_groups:
            if str(group.get('id')) == str(group_id):
                return group.get('name', '')
        
        return str(group_id)  # Si no se encuentra, devolver el ID como string
    
    def sync_from_siigo(self, full_sync=False):
        """
        Sincroniza productos desde Siigo
        
        Parámetros:
        - full_sync: Si es True, sincroniza todos los productos. 
                     Si es False, solo sincroniza los productos actualizados desde la última sincronización.
        """
        sync_log = {
            'sync_type': 'from_siigo',
            'start_time': datetime.now().isoformat(),
            'products_processed': 0,
            'products_failed': 0,
            'details': []
        }
        
        try:
            # Obtener productos paginados
            page = 1
            page_size = 100
            total_pages = 1  # Se actualizará con la primera respuesta
            productos_list = []
            
            while page <= total_pages:
                logger.info(f"Obteniendo productos de Siigo - Página {page} de {total_pages}")
                
                # Obtener página de productos
                products_response = self.siigo_api.get_products(page=page, page_size=page_size)
                logger.info(f"Cantidad de productos obtenidos: {len(products_response['results'])}")
                
                # Actualizar total de páginas si es la primera página
                if page == 1 and 'pagination' in products_response:
                    total_results = products_response['pagination']['total_results']
                    total_pages = (total_results + page_size - 1) // page_size
                    logger.info(f"Total de productos a sincronizar: {total_results}")
                
                # Procesar productos de esta página
                if 'results' in products_response:
                    for product in products_response['results']:
                        try:
                            # Obtener el precio del producto
                            price = 0
                            if product.get('prices') and len(product['prices']) > 0:
                                price_list = product['prices'][0].get('price_list', [])
                                if price_list and len(price_list) > 0:
                                    price = price_list[0].get('value', 0)
                            
                            # Obtener el impuesto
                            tax_id = ""
                            if product.get('taxes') and len(product['taxes']) > 0:
                                tax_id = product['taxes'][0].get('id', '')
                            
                            # Obtener la categoría (account_group)
                            category = self._get_account_group_name(product.get('account_group'))
                            
                            productos_list.append({
                                'producto_id': product.get('id', ''),
                                'nombre_producto': product.get('name', ''),
                                'descripcion': product.get('description', ''),
                                'codigo': product.get('code', ''),
                                'precio_unitario': price,
                                'impuesto_id': tax_id,
                                'categoria': category
                            })
                            sync_log['products_processed'] += 1
                            
                        except Exception as e:
                            error_msg = f"Error procesando producto de Siigo {product.get('code')}: {str(e)}"
                            logger.error(error_msg)
                            sync_log['details'].append(error_msg)
                            sync_log['products_failed'] += 1
                
                # Pasar a la siguiente página
                page += 1
                
                # Pequeña pausa para no sobrecargar la API
                time.sleep(0.5)
            
            logger.info(f"Sincronización desde Siigo completada: {sync_log['products_processed']} procesados, "
                       f"{sync_log['products_failed']} fallidos")
            
            return productos_list
        
        except Exception as e:
            error_msg = f"Error en sincronización desde Siigo: {str(e)}"
            logger.error(error_msg)
            sync_log['details'].append(error_msg)
            return None


# Ejemplo de uso
if __name__ == "__main__":
    try:
        # Inicializar sincronizador
        synchronizer = ProductSynchronizer()
        
        # Para pruebas: Sincronizar desde Siigo
        print("Sincronizando productos desde Siigo...")
        sync_result = synchronizer.sync_from_siigo(full_sync=True)
        print(f"Resultado: {sync_result}")
        
    except Exception as e:
        print(f"Error en ejemplo de uso: {str(e)}")