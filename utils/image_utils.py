"""
Utilidades para procesamiento de imágenes.
"""
import os
import base64
from typing import Optional
from PIL import Image
from config.logging_config import logger


def load_image(image_path: str) -> Optional[str]:
    """
    Carga una imagen desde una ruta y la codifica en base64.
    
    Args:
        image_path: Ruta de la imagen
        
    Returns:
        Imagen codificada en base64 o None si hay error
    """
    try:
        if not os.path.exists(image_path):
            logger.error(f"La imagen no existe: {image_path}")
            return None
            
        with open(image_path, "rb") as image_file:
            return base64.b64encode(image_file.read()).decode('utf-8')
    except Exception as e:
        logger.error(f"Error al cargar la imagen: {e}")
        return None


def resize_image(image_path: str, output_path: str, max_size: int = 1024) -> bool:
    """
    Redimensiona una imagen manteniendo su proporción.
    
    Args:
        image_path: Ruta de la imagen original
        output_path: Ruta donde guardar la imagen redimensionada
        max_size: Tamaño máximo en píxeles (ancho o alto)
        
    Returns:
        True si la operación fue exitosa, False en caso contrario
    """
    try:
        if not os.path.exists(image_path):
            logger.error(f"La imagen no existe: {image_path}")
            return False
            
        with Image.open(image_path) as img:
            # Redimensionar manteniendo proporción
            img.thumbnail((max_size, max_size))
            img.save(output_path)
            
        logger.info(f"Imagen redimensionada guardada en: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Error al redimensionar la imagen: {e}")
        return False


def check_image_valid(image_path: str) -> bool:
    """
    Verifica si una imagen es válida y puede ser abierta.
    
    Args:
        image_path: Ruta de la imagen a verificar
        
    Returns:
        True si la imagen es válida, False en caso contrario
    """
    try:
        if not os.path.exists(image_path):
            return False
            
        with Image.open(image_path) as img:
            # Intentar acceder a propiedades para verificar que es una imagen válida
            img.verify()
            return True
    except Exception:
        return False


def get_image_format(image_path: str) -> Optional[str]:
    """
    Obtiene el formato de una imagen.
    
    Args:
        image_path: Ruta de la imagen
        
    Returns:
        Formato de la imagen (por ejemplo, 'JPEG', 'PNG') o None si hay error
    """
    try:
        if not os.path.exists(image_path):
            return None
            
        with Image.open(image_path) as img:
            return img.format
    except Exception:
        return None