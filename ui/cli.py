"""
Interfaz de línea de comandos para el sistema de facturación.
"""
import os
import sqlite3
from typing import Optional

from apis.gemini_api import GeminiAPIClient
from apis.google_sheets_api import GoogleSheetsClient
from apis.siigo_api import SiigoAPIClient
from config.logging_config import logger
from config.settings import DB_PATH, SPREADSHEET_ID
from database.db_manager import DatabaseManager
from database.models import Invoice, Product
from services.client_service import ClientService
from services.image_service import ImageService
from services.invoice_service import InvoiceService
from services.pdf_service import PDFService
from services.product_service import ProductService


class CLI:
    """Interfaz de línea de comandos para el sistema de facturación"""
    
    def __init__(self):
        """Inicializa la CLI y todos los servicios necesarios"""
        # Inicializar base de datos
        self.db_manager = DatabaseManager(DB_PATH)
        
        # Inicializar clientes APIs
        self.sheets_client = GoogleSheetsClient()
        self.gemini_client = GeminiAPIClient()
        self.siigo_client = None
        
        # Intentar inicializar Siigo API si es posible
        try:
            self.siigo_client = SiigoAPIClient()
            if self.siigo_client.is_available():
                logger.info("API de Siigo inicializada correctamente")
            else:
                logger.warning("API de Siigo no disponible, funcionando en modo limitado")
                self.siigo_client = None
        except Exception as e:
            logger.error(f"Error al inicializar API de Siigo: {e}")
            self.siigo_client = None
        
        # Inicializar servicios
        self.pdf_service = PDFService()
        self.client_service = ClientService(self.sheets_client)
        self.product_service = ProductService(self.sheets_client)
        self.image_service = ImageService(self.gemini_client)
        self.invoice_service = InvoiceService(
            self.db_manager,
            self.sheets_client,
            self.siigo_client,
            self.pdf_service,
            self.client_service,
            self.product_service
        )
    
    def display_header(self):
        """Muestra el encabezado de la aplicación"""
        print("=" * 80)
        print(f"{'SISTEMA DE FACTURACIÓN CON RECONOCIMIENTO DE IMÁGENES':^80}")
        print("=" * 80)
        
        if self.siigo_client and self.siigo_client.is_available():
            print("📋 Modo: Facturación Electrónica (Siigo) y PDF")
        else:
            print("📋 Modo: Facturación PDF solamente")
        
        if not self.gemini_client.is_available():
            print("⚠️  Advertencia: API de Gemini no disponible. Procesamiento de imágenes limitado.")
    
    def display_menu(self):
        """Muestra el menú principal"""
        print("\nOpciones:")
        print("1. Procesar pedido desde imagen")
        print("2. Ver historial de facturas")
        print("3. Verificar conexión con Siigo")
        print("4. Verificar conexión con Google Sheets")
        print("0. Salir")
    
    def process_order_from_image(self):
        """Procesa un pedido a partir de una imagen"""
        image_path = input("Ruta de la imagen del pedido (Enter para usar image_pedido.jpg): ") or "image_pedido.jpg"
        
        if not os.path.exists(image_path):
            print(f"Error: La imagen '{image_path}' no existe.")
            return
        
        # Procesar la imagen para extraer cliente y productos
        client_name, products_data = self.image_service.process_order_image(image_path)
        
        if not products_data:
            print("No se pudieron detectar productos en la imagen.")
            return
        
        # Procesar el pedido
        result = self.invoice_service.process_order_from_image(client_name, products_data)
        
        if not result:
            print("No se pudo procesar el pedido.")
            return
        
        invoice, products, pdf_path = result
        
        # Preguntar si guardar en Google Sheets
        confirm_sheets = input("\n¿Deseas guardar esta factura en el historial de Google Sheets? (s/n): ")
        if confirm_sheets.lower() == 's':
            logger.info("Guardando factura en el historial...")
            saved = self.sheets_client.save_invoice_to_sheet(invoice.to_dict())
            if saved:
                print("Factura guardada correctamente en Google Sheets")
            else:
                print("Error al guardar la factura en Google Sheets")
        
        # Verificar si se puede generar factura electrónica
        if self.invoice_service.is_siigo_available():
            confirm_siigo = input("\n¿Deseas generar factura electrónica en Siigo? (s/n): ")
            if confirm_siigo.lower() == 's':
                # Preguntar si enviar a la DIAN
                confirm_dian = input("\n¿Enviar directamente a la DIAN? (s/n): ")
                send_to_dian = confirm_dian.lower() == 's'
                
                # Obtener datos del cliente
                client_data = self.client_service.get_client_data(invoice.nombre_cliente)
                
                if not client_data:
                    print("Error: No se pudo obtener información del cliente para factura electrónica")
                    return
                
                print(f"Generando factura electrónica en Siigo{' y enviando a DIAN' if send_to_dian else ' (sin enviar a DIAN)'}...")
                siigo_id = self.invoice_service.generate_siigo_invoice(
                    invoice, products, client_data, send_to_dian
                )
                
                if siigo_id:
                    print(f"Factura electrónica generada con éxito en Siigo con ID: {siigo_id}")
                else:
                    print("No se pudo generar la factura electrónica en Siigo")
    
    def show_invoice_history(self):
        """Muestra el historial de facturas"""
        print("\n--- HISTORIAL DE FACTURAS ---")
        try:
            invoices = self.db_manager.get_invoices(10)  # Últimas 10 facturas
            
            if invoices:
                print("\nÚltimas 10 facturas:")
                print("-" * 90)
                print(f"{'ID':^20} | {'Cliente':^30} | {'Fecha':^12} | {'Total':^10} | {'Estado':^15}")
                print("-" * 90)
                
                for factura in invoices:
                    print(
                        f"{factura['id']:^20} | {factura['cliente_nombre'][:28]:^30} | {factura['fecha']:^12} | "
                        f"${float(factura['total']):<9.2f} | {factura['estado']:^15}"
                    )
                
                print("-" * 90)
            else:
                print("No hay facturas registradas.")
        except Exception as e:
            print(f"Error al obtener el historial: {e}")
    
    def check_siigo_connection(self):
        """Verifica la conexión con Siigo API"""
        if self.siigo_client:
            try:
                token = self.siigo_client.get_token()
                if token:
                    print("✅ Conexión con Siigo API establecida correctamente")
                else:
                    print("❌ No se pudo obtener token de Siigo API")
            except Exception as e:
                print(f"❌ Error al conectar con Siigo API: {e}")
        else:
            print("❌ API de Siigo no inicializada. Verifique las credenciales en .env")
    
    def check_google_sheets_connection(self):
        """Verifica la conexión con Google Sheets"""
        if self.sheets_client.is_available():
            try:
                worksheets = self.sheets_client.spreadsheet.worksheets()
                print("✅ Conexión con Google Sheets establecida correctamente")
                print(f"   Hojas disponibles: {', '.join([ws.title for ws in worksheets])}")
            except Exception as e:
                print(f"❌ Error al conectar con Google Sheets: {e}")
        else:
            print("❌ Cliente de Google Sheets no inicializado. Verifique el archivo de credenciales.")
    
    def run(self):
        """Ejecuta el bucle principal de la CLI"""
        self.display_header()
        
        while True:
            self.display_menu()
            option = input("\nSelecciona una opción: ")
            
            if option == "0":
                print("Saliendo del sistema...")
                break
            elif option == "1":
                self.process_order_from_image()
            elif option == "2":
                self.show_invoice_history()
            elif option == "3":
                self.check_siigo_connection()
            elif option == "4":
                self.check_google_sheets_connection()
            else:
                print("Opción no válida")