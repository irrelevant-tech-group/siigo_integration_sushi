#!/usr/bin/env python
"""
Script para iniciar el bot de Telegram integrado con el sistema de facturación.
"""
import os
import sys

# Asegurar que el directorio del proyecto esté en el path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config.logging_config import logger
from config.settings import load_env_file
from apis.google_sheets_api import GoogleSheetsClient
from apis.siigo_api import SiigoAPIClient
from database.db_manager import DatabaseManager
from services.client_service import ClientService
from services.image_service import ImageService
from services.invoice_service import InvoiceService
from services.pdf_service import PDFService
from services.product_service import ProductService
from ui.telegram_bot import TelegramInterface


def main():
    """Inicia el bot de Telegram con todos los servicios necesarios"""
    try:
        # Cargar variables de entorno
        ENV_VARS = load_env_file()
        
        # Inicializar base de datos
        db_manager = DatabaseManager()
        
        # Inicializar clientes APIs
        sheets_client = GoogleSheetsClient()
        claude_client = ClaudeAPIClient()
        
        # Inicializar Siigo API
        try:
            siigo_client = SiigoAPIClient()
            if not siigo_client.is_available():
                logger.warning("API de Siigo no disponible, funcionando en modo limitado")
                siigo_client = None
        except Exception as e:
            logger.error(f"Error al inicializar API de Siigo: {e}")
            siigo_client = None
        
        # Inicializar servicios
        pdf_service = PDFService()
        client_service = ClientService(sheets_client)
        product_service = ProductService(sheets_client)
        image_service = ImageService(claude_client)
        invoice_service = InvoiceService(
            db_manager,
            sheets_client,
            siigo_client,
            pdf_service,
            client_service,
            product_service
        )
        
        # Inicializar la interfaz de Telegram
        telegram_bot = TelegramInterface(
            invoice_service,
            client_service,
            product_service,
            image_service
        )
        
        # Configurar y ejecutar el bot
        application = telegram_bot.setup_bot()
        
        if application:
            logger.info("Iniciando Bot de Telegram para sistema de facturación...")
            print("Bot de Telegram iniciado. Presiona Ctrl+C para detener.")
            application.run_polling()
        else:
            logger.error("No se pudo configurar el bot de Telegram.")
            print("Error al configurar el bot. Verifica el token y las credenciales.")
            
    except KeyboardInterrupt:
        print("\nBot detenido por el usuario.")
        logger.info("Bot detenido por el usuario")
    except Exception as e:
        print(f"\nError inesperado: {e}")
        logger.exception("Error inesperado al iniciar el bot:")


if __name__ == "__main__":
    main()