"""
Utilidades para procesamiento de texto.
"""
import json
from typing import Dict, Any, Optional, Union


def normalize_text(text: str) -> str:
    """
    Normaliza el texto para comparaciones insensibles a tildes y caracteres especiales.
    
    Args:
        text: Texto a normalizar
        
    Returns:
        Texto normalizado
    """
    if not text:
        return ""
    
    # Convertir a minúsculas
    text = text.lower()
    
    # Reemplazar caracteres con tilde por sus equivalentes sin tilde
    replacements = {
        'á': 'a', 'é': 'e', 'í': 'i', 'ó': 'o', 'ú': 'u',
        'ü': 'u', 'ñ': 'n', 'ç': 'c'
    }
    
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    
    # Eliminar caracteres especiales y espacios extras
    text = ''.join(c for c in text if c.isalnum() or c.isspace())
    text = ' '.join(text.split())  # Normalizar espacios
    
    return text


def clean_price(price_str: Union[str, int, float]) -> float:
    """
    Limpia un string de precio para convertirlo a float.
    
    Args:
        price_str: String de precio a limpiar
        
    Returns:
        Precio como float
    """
    if isinstance(price_str, (int, float)):
        return float(price_str)
    
    if not price_str:
        return 0.0
    
    # Eliminar símbolos de moneda y espacios
    for char in ['$', '€', '£', '¥', ' ', ',']:
        price_str = price_str.replace(char, '')
    
    try:
        return float(price_str)
    except ValueError:
        print(f"Error al convertir precio: {price_str}")
        return 0.0


def extract_json_from_response(response_text: str) -> Dict[str, Any]:
    """
    Extrae un objeto JSON del texto de respuesta.
    
    Args:
        response_text: Texto de respuesta que contiene JSON
        
    Returns:
        Diccionario con los datos extraídos o mensaje de error
    """
    try:
        # Intenta encontrar el JSON en la respuesta
        start_idx = response_text.find('{')
        end_idx = response_text.rfind('}') + 1
        
        if start_idx != -1 and end_idx != -1:
            json_str = response_text[start_idx:end_idx]
            data = json.loads(json_str)
            return data
        else:
            # Si no encuentra formato JSON, intentamos parsear el texto
            return {"error": "Formato de respuesta no reconocido"}
    except json.JSONDecodeError as e:
        return {"error": f"Error al decodificar la respuesta: {str(e)}"}


def calculate_similarity(text1: str, text2: str) -> float:
    """
    Calcula la similitud entre dos textos basada en palabras comunes.
    
    Args:
        text1: Primer texto
        text2: Segundo texto
        
    Returns:
        Puntuación de similitud entre 0.0 y 1.0
    """
    # Normalizar textos
    norm_text1 = normalize_text(text1)
    norm_text2 = normalize_text(text2)
    
    # Obtener conjuntos de palabras
    words1 = set(norm_text1.split())
    words2 = set(norm_text2.split())
    
    # Calcular intersección
    common_words = words1.intersection(words2)
    
    # Si no hay palabras, retornar 0
    if len(words1) == 0 or len(words2) == 0:
        return 0.0
    
    # Calcular similitud (número de palabras comunes / máximo de palabras en ambos textos)
    return len(common_words) / max(len(words1), len(words2))