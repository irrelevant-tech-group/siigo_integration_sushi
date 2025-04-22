"""
Servicio para gestión de productos.
"""
from typing import List, Dict, Any, Optional

from apis.google_sheets_api import GoogleSheetsClient
from config.logging_config import logger
from database.models import Product
from utils.text_utils import normalize_text, calculate_similarity, clean_price


class ProductService:
    """Servicio para la gestión de productos"""
    
    def __init__(self, sheets_client: GoogleSheetsClient):
        """
        Inicializa el servicio de productos.
        
        Args:
            sheets_client: Cliente de Google Sheets
        """
        self.sheets_client = sheets_client
    
    def get_all_products(self) -> List[Dict[str, Any]]:
        """
        Obtiene todos los productos registrados.
        
        Returns:
            Lista de productos
        """
        return self.sheets_client.get_products()
    
    def find_product_by_id(self, product_id: str) -> Optional[Dict[str, Any]]:
        """
        Busca un producto por su ID.
        
        Args:
            product_id: ID del producto
            
        Returns:
            Datos del producto o None si no se encuentra
        """
        products = self.get_all_products()
        for product in products:
            if product.get('producto_id') == product_id:
                return product
        return None
    
    def find_product_by_name(self, name: str, threshold: float = 0.7) -> Optional[Dict[str, Any]]:
        """
        Busca un producto por su nombre con comparación flexible.
        
        Args:
            name: Nombre del producto a buscar
            threshold: Umbral de similitud (0.0 a 1.0)
            
        Returns:
            Datos del producto o None si no se encuentra con suficiente similitud
        """
        if not name:
            return None
            
        products = self.get_all_products()
        if not products:
            logger.warning("No hay productos registrados")
            return None
            
        normalized_search = normalize_text(name)
        best_match = None
        best_score = 0
        
        for product_data in products:
            product_name = product_data.get('nombre_producto', '')
            similarity = calculate_similarity(normalized_search, product_name)
            
            if similarity > best_score:
                best_score = similarity
                best_match = product_data
        
        # Si la mejor coincidencia supera el umbral, devolverla
        if best_match and best_score >= threshold:
            logger.info(f"Producto encontrado: {best_match['nombre_producto']} (Coincidencia: {best_score:.0%})")
            return best_match
            
        # Si hay una coincidencia parcial, podemos registrarla
        if best_match and best_score >= 0.4:
            logger.info(f"Posible coincidencia para '{name}': '{best_match['nombre_producto']}' (Coincidencia: {best_score:.0%})")
            return best_match
            
        logger.warning(f"No se encontró ningún producto que coincida con '{name}'")
        return None
    
    def confirm_product_match(self, detected_name: str, possible_match: Dict[str, Any]) -> bool:
        """
        Solicita confirmación al usuario sobre una posible coincidencia de producto.
        
        Args:
            detected_name: Nombre detectado
            possible_match: Posible coincidencia de producto
            
        Returns:
            True si se confirma, False en caso contrario
        """
        confirm = input(
            f"\n¿Confirmar que '{detected_name}' es '{possible_match['nombre_producto']}'? (s/n): "
        )
        return confirm.lower() in ('s', 'si', 'sí', 'y', 'yes')
    
    def process_detected_products(self, detected_products: List[Dict[str, Any]]) -> List[Product]:
        """
        Procesa productos detectados, buscando coincidencias en el catálogo.
        
        Args:
            detected_products: Lista de productos detectados con nombres y cantidades
            
        Returns:
            Lista de objetos Product con información completa
        """
        processed_products = []
        product_catalog = self.get_all_products()
        
        if not product_catalog:
            logger.error("No se encontraron productos en el catálogo")
            return []
        
        print("\nProductos identificados:")
        for i, product in enumerate(detected_products):
            product_name = product["nombre"]
            product_qty = product["cantidad"]
            
            print(f"{i+1}. {product_name} - Cantidad: {product_qty}")
            
            # Buscar coincidencia en el catálogo
            product_details = self.find_product_by_name(product_name)
            
            if product_details:
                # Si hay coincidencia buena, usar directamente
                similarity = calculate_similarity(product_name, product_details['nombre_producto'])
                if similarity >= 0.7:
                    processed_products.append(Product(
                        nombre=product_details["nombre_producto"],
                        cantidad=product_qty,
                        precio=clean_price(product_details["precio_unitario"]),
                        producto_id=product_details["producto_id"],
                        impuesto_id=product_details.get("impuesto_id", "")
                    ))
                    continue
                
                # Si hay coincidencia parcial, solicitar confirmación
                if similarity >= 0.4:
                    if self.confirm_product_match(product_name, product_details):
                        processed_products.append(Product(
                            nombre=product_details["nombre_producto"],
                            cantidad=product_qty,
                            precio=clean_price(product_details["precio_unitario"]),
                            producto_id=product_details["producto_id"],
                            impuesto_id=product_details.get("impuesto_id", "")
                        ))
                        continue
            
            # Si no hay coincidencia, solicitar precio manual
            logger.warning(f"No se encontró el producto '{product_name}' en el catálogo")
            price_input = input(f"Ingresa el precio unitario para '{product_name}' (o presiona Enter para omitir): ")
            
            if price_input.strip() and price_input.replace('.', '', 1).isdigit():
                processed_products.append(Product(
                    nombre=product_name,
                    cantidad=product_qty,
                    precio=float(price_input),
                    producto_id="MANUAL",
                    impuesto_id=""
                ))
        
        return processed_products