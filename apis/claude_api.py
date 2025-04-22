"""
Cliente para la API de Claude Vision.
"""
import anthropic
from typing import Optional, Dict, Any, List

from config.settings import ANTHROPIC_API_KEY, CLAUDE_MODEL
from config.logging_config import logger
from utils.text_utils import extract_json_from_response


class ClaudeAPIClient:
    """Cliente para interactuar con la API de Claude (Anthropic)"""
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Inicializa el cliente de Claude API.
        
        Args:
            api_key: API key de Anthropic (opcional, usa la de config si no se proporciona)
        """
        self.api_key = api_key or ANTHROPIC_API_KEY
        self.client = None
        
        if not self.api_key:
            logger.warning("No se ha configurado una API key para Claude")
        else:
            self.client = anthropic.Anthropic(api_key=self.api_key)
    
    def is_available(self) -> bool:
        """
        Verifica si el cliente está correctamente configurado.
        
        Returns:
            True si el cliente está disponible, False en caso contrario
        """
        return self.client is not None
    
    def process_image(self, image_base64: str, system_prompt: str, user_prompt: str) -> Optional[str]:
        """
        Procesa una imagen con Claude Vision.
        
        Args:
            image_base64: Imagen codificada en base64
            system_prompt: Instrucciones para el sistema
            user_prompt: Prompt del usuario
            
        Returns:
            Texto de respuesta o None si hay error
        """
        if not self.is_available():
            logger.error("No se puede procesar la imagen: API key de Claude no configurada")
            return None
        
        try:
            message = self.client.messages.create(
                model=CLAUDE_MODEL,
                max_tokens=1000,
                temperature=0,
                system=system_prompt,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "image",
                                "source": {
                                    "type": "base64",
                                    "media_type": "image/jpeg",
                                    "data": image_base64
                                }
                            },
                            {
                                "type": "text",
                                "text": user_prompt
                            }
                        ]
                    }
                ]
            )
            logger.info("Imagen procesada correctamente por Claude")
            return message.content[0].text
        except Exception as e:
            logger.error(f"Error al procesar con Claude: {e}")
            return None
    
    def detect_client_from_image(self, image_base64: str) -> Optional[str]:
        """
        Detecta el nombre del cliente desde una imagen.
        
        Args:
            image_base64: Imagen codificada en base64
            
        Returns:
            Nombre del cliente o None si no se detecta o hay error
        """
        system_prompt = (
            "Eres un asistente especializado en extraer información de clientes en imágenes. "
            "Analiza la imagen y extrae el nombre del cliente si está presente. "
            "Responde únicamente con un JSON en el formato: {'cliente': 'nombre_del_cliente'}"
        )
        
        user_prompt = (
            "Identifica si hay algún nombre de cliente en esta imagen. "
            "Solo necesito el nombre, sin títulos como 'Sr.' o 'Sra.'. "
            "Si no hay un cliente claramente identificable, devuelve un JSON con cliente vacío."
        )
        
        response = self.process_image(image_base64, system_prompt, user_prompt)
        if not response:
            return None
        
        client_data = extract_json_from_response(response)
        return client_data.get('cliente', '')
    
    def detect_products_from_image(self, image_base64: str) -> Optional[List[Dict[str, Any]]]:
        """
        Detecta productos y cantidades desde una imagen.
        
        Args:
            image_base64: Imagen codificada en base64
            
        Returns:
            Lista de productos detectados o None si hay error
        """
        system_prompt = (
            "Eres un asistente especializado en extraer información de imágenes de pedidos. "
            "Analiza la imagen y extrae una lista de productos y sus cantidades. "
            "Responde únicamente con un JSON en el formato: "
            "{'productos': [{'nombre': 'nombre del producto', 'cantidad': número}]}"
        )
        
        user_prompt = (
            "Identifica todos los productos y sus cantidades en esta imagen. "
            "Devuelve solo un objeto JSON con la lista de productos y cantidades."
        )
        
        response = self.process_image(image_base64, system_prompt, user_prompt)
        if not response:
            return None
        
        products_data = extract_json_from_response(response)
        if "error" in products_data:
            logger.error(f"Error al extraer productos: {products_data['error']}")
            return None
            
        if "productos" not in products_data:
            logger.error("No se encontraron productos en la respuesta")
            return None
            
        return products_data["productos"]