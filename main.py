"""
Punto de entrada principal para el sistema de facturación.
"""
import os
import sys

# Asegurar que el directorio del proyecto esté en el path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ui.cli import CLI
from config.logging_config import logger


def main():
    """Función principal del sistema de facturación"""
    try:
        # Inicializar y ejecutar la CLI
        cli = CLI()
        cli.run()
    except KeyboardInterrupt:
        print("\nPrograma interrumpido por el usuario.")
        logger.info("Programa interrumpido por el usuario")
    except Exception as e:
        print(f"\nError inesperado: {e}")
        logger.exception("Error inesperado:")


if __name__ == "__main__":
    main()