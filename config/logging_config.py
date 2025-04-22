"""
Configuración centralizada del sistema de logging.
"""
import logging
import os

def setup_logger(name='siigo_gsheets', log_file='siigo_gsheets.log'):
    """
    Configura y devuelve un logger con la configuración estándar.
    
    Args:
        name (str): Nombre del logger
        log_file (str): Nombre del archivo de log
        
    Returns:
        logging.Logger: Logger configurado
    """
    logger = logging.getLogger(name)
    
    # Evitar configurar múltiples veces el mismo logger
    if logger.handlers:
        return logger
        
    logger.setLevel(logging.INFO)
    
    # Formato
    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    
    # Handler para archivo
    file_handler = logging.FileHandler(log_file)
    file_handler.setFormatter(formatter)
    
    # Handler para consola
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    
    # Agregar handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)
    
    return logger

# Logger principal
logger = setup_logger()
