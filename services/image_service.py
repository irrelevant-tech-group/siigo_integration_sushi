"""
Servicio para procesamiento de imágenes.
"""
import os
from typing import Dict, List, Any, Optional, Tuple

from apis.gemini_api import GeminiAPIClient
from config.logging_config import logger
from utils.image_utils import load_image, check_image_valid
from utils.text_utils import extract_json_from_response


class ImageService:
    """Servicio para procesamiento de imágenes de pedidos"""
    
    def __init__(self, gemini_client: GeminiAPIClient):
        """
        Inicializa el servicio de procesamiento de imágenes.
        
        Args:
            gemini_client: Cliente de Gemini API
        """
        self.gemini_client = gemini_client
    
    def validate_image(self, image_path: str) -> bool:
        """
        Valida si la imagen existe y es válida.
        
        Args:
            image_path: Ruta de la imagen
            
        Returns:
            True si la imagen es válida, False en caso contrario
        """
        if not os.path.exists(image_path):
            logger.error(f"La imagen '{image_path}' no existe")
            return False
            
        if not check_image_valid(image_path):
            logger.error(f"La imagen '{image_path}' no es válida o está dañada")
            return False
            
        return True
    
    def process_order_image(self, image_path: str) -> Tuple[Optional[str], Optional[List[Dict[str, Any]]]]:
        """
        Procesa una imagen de pedido para extraer cliente y productos.
        
        Args:
            image_path: Ruta de la imagen
            
        Returns:
            Tupla con (nombre_cliente, lista_productos) o (None, None) si hay error
        """
        # Validar imagen
        if not self.validate_image(image_path):
            return None, None
            
        # Cargar imagen
        logger.info(f"Cargando imagen: {image_path}")
        image_base64 = load_image(image_path)
        if not image_base64:
            return None, None
            
        # Detectar cliente
        logger.info("Identificando al cliente en la imagen...")
        client_name = self.gemini_client.detect_client_from_image(image_base64)
        
        if client_name:
            logger.info(f"Cliente detectado en la imagen: {client_name}")
        else:
            logger.info("No se detectó ningún cliente en la imagen")
        
        # Detectar productos
        logger.info("Procesando productos en la imagen...")
        products = self.gemini_client.detect_products_from_image(image_base64)
        
        if not products:
            logger.error("No se pudieron detectar productos en la imagen")
            return client_name, None
            
        logger.info(f"Se detectaron {len(products)} productos en la imagen")
        return client_name, products