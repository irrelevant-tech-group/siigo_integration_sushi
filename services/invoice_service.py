"""
Servicio para la generación y gestión de facturas.
"""
import json
import os
import time
from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime

from apis.google_sheets_api import GoogleSheetsClient
from apis.siigo_api import SiigoAPIClient
from config.logging_config import logger
from database.db_manager import DatabaseManager
from database.models import Invoice, Product, Client
from services.client_service import ClientService
from services.pdf_service import PDFService
from services.product_service import ProductService


class InvoiceService:
    """Servicio para la gestión de facturas"""
    
    def __init__(
        self,
        db_manager: DatabaseManager,
        sheets_client: GoogleSheetsClient,
        siigo_client: Optional[SiigoAPIClient] = None,
        pdf_service: Optional[PDFService] = None,
        client_service: Optional[ClientService] = None,
        product_service: Optional[ProductService] = None
    ):
        """
        Inicializa el servicio de facturas.
        
        Args:
            db_manager: Gestor de base de datos
            sheets_client: Cliente de Google Sheets
            siigo_client: Cliente de Siigo API (opcional)
            pdf_service: Servicio de generación de PDFs (opcional)
            client_service: Servicio de clientes (opcional)
            product_service: Servicio de productos (opcional)
        """
        self.db_manager = db_manager
        self.sheets_client = sheets_client
        self.siigo_client = siigo_client
        
        # Inicializar servicios si no se proporcionan
        self.pdf_service = pdf_service or PDFService()
        self.client_service = client_service or ClientService(sheets_client)
        self.product_service = product_service or ProductService(sheets_client)
    
    def is_siigo_available(self) -> bool:
        """
        Verifica si la integración con Siigo está disponible.
        
        Returns:
            True si está disponible, False en caso contrario
        """
        return self.siigo_client is not None and self.siigo_client.is_available()
    
    def generate_invoice(self, client_data: Dict[str, Any], products: List[Product]) -> Optional[Invoice]:
        """
        Genera una factura a partir de los datos del cliente y productos.
        
        Args:
            client_data: Datos del cliente
            products: Lista de productos
            
        Returns:
            Objeto Invoice generado o None si hay error
        """
        try:
            if not products:
                logger.error("No se puede generar factura sin productos")
                return None
                
            # Crear cliente
            client = Client.from_dict(client_data)
            
            # Crear factura
            invoice = Invoice.create_new(client, products)
            
            logger.info(f"Factura generada con ID: {invoice.factura_id}")
            return invoice
            
        except Exception as e:
            logger.error(f"Error al generar factura: {e}")
            return None
    
    def display_invoice(self, invoice: Invoice, products: List[Product]) -> None:
        """
        Muestra la factura en formato legible en la consola.
        
        Args:
            invoice: Factura a mostrar
            products: Productos de la factura
        """
        print("\n" + "="*50)
        print(f"{'FACTURA':^50}")
        print("="*50)
        print(f"Factura #: {invoice.factura_id}")
        print(f"Fecha: {invoice.fecha_emision}")
        print("-"*50)
        print(f"Cliente: {invoice.nombre_cliente}")
        print(f"Identificación: {invoice.identificacion}")
        print("-"*50)
        print("PRODUCTOS:")
        
        for product in products:
            total = product.precio * product.cantidad
            print(f"{product.nombre} x {product.cantidad} = ${total:.2f}")
        
        print("-"*50)
        print(f"TOTAL: ${invoice.valor_total:.2f}")
        print("="*50)
    
    def save_invoice(self, invoice: Invoice, products: List[Product], save_to_sheets: bool = True) -> bool:
        """
        Guarda la factura en la base de datos local y opcionalmente en Google Sheets.
        
        Args:
            invoice: Factura a guardar
            products: Productos de la factura
            save_to_sheets: Si True, guarda también en Google Sheets
            
        Returns:
            True si se guarda correctamente, False en caso contrario
        """
        # Guardar en base de datos local
        db_result = self.db_manager.save_invoice(invoice, products)
        
        # Guardar en Google Sheets si se solicita
        sheets_result = True
        if save_to_sheets and self.sheets_client.is_available():
            sheets_result = self.sheets_client.save_invoice_to_sheet(invoice.to_dict())
        
        return db_result and (not save_to_sheets or sheets_result)
    
    def generate_invoice_pdf(self, invoice: Invoice, products: List[Product]) -> Optional[str]:
        """
        Genera un PDF para la factura.
        
        Args:
            invoice: Factura a convertir en PDF
            products: Productos de la factura
            
        Returns:
            Ruta al archivo PDF generado o None si hay error
        """
        timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
        filename = f"factura_{invoice.factura_id}_{timestamp}.pdf"
        
        pdf_path = self.pdf_service.generate_invoice_pdf(invoice, products, filename)
        
        if pdf_path:
            # Actualizar la factura con la ruta del PDF
            invoice.pdf_url = pdf_path
            logger.info(f"PDF generado exitosamente: {pdf_path}")
        
        return pdf_path
    
    def generate_siigo_invoice(
        self, 
        invoice: Invoice, 
        products: List[Product], 
        client_data: Dict[str, Any], 
        send_to_dian: bool = False
    ) -> Optional[str]:
        """
        Genera una factura electrónica en Siigo.
        
        Args:
            invoice: Factura local
            products: Productos de la factura
            client_data: Datos completos del cliente
            send_to_dian: Si True, envía la factura a la DIAN
            
        Returns:
            ID de la factura en Siigo o None si hay error
        """
        if not self.is_siigo_available():
            logger.error("No se puede generar factura electrónica: API de Siigo no disponible")
            return None
        
        try:
            # 1. Verificar cliente en Siigo o crearlo
            customers = self.siigo_client.get_customers(identification=client_data['identificacion'])
            customer_id = None
            
            if customers and 'results' in customers and len(customers['results']) > 0:
                customer_id = customers['results'][0]['id']
                logger.info(f"Cliente encontrado en Siigo con ID: {customer_id}")
            else:
                logger.info("Cliente no encontrado en Siigo, creando nuevo cliente...")
                new_customer = {
                    "type": "Customer",
                    "person_type": client_data.get('tipo_persona', 'Person'),
                    "id_type": client_data.get('tipo_identificacion', '13'),
                    "identification": client_data['identificacion'],
                    "name": [client_data['nombre_cliente']],
                    "commercial_name": client_data['nombre_cliente'],
                    "active": True,
                    "vat_responsible": False,
                    "fiscal_responsibilities": [{"code": "R-99-PN"}],
                    "address": {
                        "address": client_data.get('direccion', 'N/A'),
                        "city": {
                            "country_code": "Co",
                            "state_code": "11",
                            "city_code": "11001"
                        }
                    },
                    "contacts": [
                        {
                            "first_name": client_data['nombre_cliente'].split()[0],
                            "last_name": " ".join(client_data['nombre_cliente'].split()[1:]) if len(client_data['nombre_cliente'].split()) > 1 else "",
                            "email": client_data.get('email', 'cliente@ejemplo.com')
                        }
                    ]
                }
                
                try:
                    customer_result = self.siigo_client.create_customer(new_customer)
                    customer_id = customer_result['id']
                    logger.info(f"Cliente creado en Siigo con ID: {customer_id}")
                except Exception as e:
                    logger.error(f"Error al crear cliente en Siigo: {e}")
                    return None
            
            # 2. Procesar productos para Siigo
            invoice_items = []
            for product in products:
                product_code = product.producto_id or f"P{int(time.time())}"
                
                siigo_products = self.siigo_client.get_products(code=product_code)
                product_id = None
                
                if siigo_products and 'results' in siigo_products and len(siigo_products['results']) > 0:
                    product_id = siigo_products['results'][0]['id']
                    logger.info(f"Producto encontrado en Siigo: {product.nombre} (ID: {product_id})")
                else:
                    logger.info(f"Producto no encontrado en Siigo, creando nuevo producto: {product.nombre}")
                    new_product = {
                        "code": product_code,
                        "name": product.nombre,
                        "account_group": 1253,
                        "type": "Product",
                        "stock_control": True,
                        "active": True,
                        "tax_classification": "Taxed",
                        "taxes": [{"id": product.impuesto_id or 13156}],
                        "prices": [{
                            "currency_code": "COP",
                            "price_list": [
                                {
                                    "position": 1,
                                    "value": float(product.precio)
                                }
                            ]
                        }]
                    }
                    
                    try:
                        product_result = self.siigo_client.create_product(new_product)
                        product_id = product_result['id']
                        logger.info(f"Producto creado en Siigo: {product.nombre} (ID: {product_id})")
                    except Exception as e:
                        logger.error(f"Error al crear producto en Siigo: {e}")
                        continue
                
                invoice_items.append({
                    "code": product_code,
                    "description": product.nombre,
                    "quantity": float(product.cantidad),
                    "price": float(product.precio),
                    "discount": 0
                })
            
            # 3. Obtener vendedor/usuario
            users_data = self.siigo_client.get_users()
            seller_id = None
            
            if isinstance(users_data, dict) and 'results' in users_data:
                users_list = users_data['results']
            elif isinstance(users_data, list):
                users_list = users_data
            else:
                users_list = []
            
            if users_list:
                seller_id = users_list[0].get('id')
                logger.info(f"Usando usuario vendedor con ID: {seller_id}")
            else:
                logger.warning("No se encontraron usuarios registrados en Siigo")
            
            # 4. Obtener tipo de documento
            document_types = self.siigo_client.get_document_types("FV")
            if not document_types:
                logger.error("No se encontraron tipos de documento para facturas")
                return None
            
            document_id = None
            selected_document_type = None
            for doc_type in document_types:
                if doc_type.get('electronic_type') == 'ElectronicInvoice':
                    document_id = doc_type['id']
                    selected_document_type = doc_type
                    break
            
            if not document_id and document_types:
                document_id = document_types[0]['id']
                selected_document_type = document_types[0]
            
            if not document_id:
                logger.error("No se pudo determinar el tipo de documento para la factura")
                return None
            
            # Verificar si se requiere número manual
            requires_manual_number = False
            invoice_number = None
            if selected_document_type and selected_document_type.get('automatic_number') is False:
                requires_manual_number = True
                invoice_number = selected_document_type.get('consecutive', 1)
                logger.info(f"El documento requiere numeración manual. Usando consecutivo: {invoice_number}")
            
            # 5. Obtener método de pago
            payment_types = self.siigo_client.get_payment_types("FV")
            payment_id = None
            
            if payment_types and isinstance(payment_types, list) and len(payment_types) > 0:
                payment_id = payment_types[0]['id']
                logger.info(f"Usando forma de pago con ID: {payment_id}")
            else:
                # Verificar si payment_types tiene la estructura esperada o usar un ID predeterminado
                if isinstance(payment_types, dict) and 'results' in payment_types and len(payment_types['results']) > 0:
                    payment_id = payment_types['results'][0]['id']
                    logger.info(f"Usando forma de pago (de results) con ID: {payment_id}")
                else:
                    # Usar un ID de pago predeterminado para entorno de pruebas
                    payment_id = 5636  # ID predeterminado para entorno de pruebas - Pago de contado
                    logger.warning(f"No se encontraron formas de pago. Usando ID predeterminado: {payment_id}")
            
            # Verificación adicional para asegurarse de que payment_id nunca sea None
            if payment_id is None:
                payment_id = 5636  # ID predeterminado para pago de contado en entorno de pruebas
                logger.warning(f"Forzando uso de ID de pago predeterminado: {payment_id}")
            
            # 6. Crear factura en Siigo
            invoice_data_siigo = {
                "document": {"id": document_id},
                "date": datetime.now().strftime("%Y-%m-%d"),
                "customer": {"identification": str(client_data['identificacion']), "branch_office": 0},
                "seller": seller_id,
                "observations": f"Factura generada automáticamente. Ref: {invoice.factura_id}",
                "items": invoice_items,
                "payments": [{
                    "id": payment_id,
                    "value": invoice.valor_total,
                    "due_date": datetime.now().strftime("%Y-%m-%d")
                }],
                "stamp": {"send": send_to_dian},
                "mail": {"send": True}
            }
            
            if requires_manual_number and invoice_number is not None:
                invoice_data_siigo["document"]["number"] = invoice_number
            
            # Guardar JSON de la factura
            invoice.payload_json = json.dumps(invoice_data_siigo)
            
            # Enviar factura a Siigo
            logger.info("Intentando crear factura en Siigo...")
            result = self.siigo_client.create_invoice(invoice_data_siigo)
            
            if result and 'id' in result:
                siigo_id = result['id']
                logger.info(f"Factura electrónica creada exitosamente en Siigo ID: {siigo_id}")
                
                # Actualizar estado en la base de datos
                self.db_manager.update_invoice_status(
                    invoice.factura_id, 
                    'Facturado en Siigo', 
                    siigo_id
                )
                
                # Actualizar objeto de factura
                invoice.estado = 'Facturado en Siigo'
                invoice.siigo_id = siigo_id
                
                return siigo_id
            else:
                logger.error(f"Respuesta inválida de Siigo: {result}")
                return None
                
        except Exception as e:
            import traceback
            logger.error(f"Error al crear factura en Siigo: {str(e)}")
            logger.error(f"Traceback completo: {traceback.format_exc()}")
            return None
    
    def process_order_from_image(
        self, 
        client_name: str, 
        detected_products: List[Dict[str, Any]]
    ) -> Optional[Tuple[Invoice, List[Product], str]]:
        """
        Procesa un pedido a partir de información detectada en una imagen.
        
        Args:
            client_name: Nombre del cliente detectado
            detected_products: Lista de productos detectados
            
        Returns:
            Tupla con (factura, productos, pdf_path) o None si hay error
        """
        try:
            # 1. Obtener datos del cliente
            logger.info(f"Buscando información del cliente: {client_name}")
            client_data = self.client_service.get_client_data(client_name)
            
            if not client_data:
                logger.error("No se pudo obtener información del cliente")
                return None
            
            # 2. Procesar productos detectados
            logger.info("Procesando productos detectados...")
            products = self.product_service.process_detected_products(detected_products)
            
            if not products:
                logger.error("No se pudo obtener información suficiente de productos")
                return None
            
            # 3. Generar factura
            logger.info("Generando factura...")
            invoice = self.generate_invoice(client_data, products)
            
            if not invoice:
                logger.error("Error al generar la factura")
                return None
            
            # 4. Mostrar factura generada
            self.display_invoice(invoice, products)
            
            # 5. Generar PDF
            logger.info("Generando PDF de la factura...")
            pdf_path = self.generate_invoice_pdf(invoice, products)
            
            if not pdf_path:
                logger.error("Error al generar PDF de la factura")
            
            # 6. Guardar factura en base de datos
            self.save_invoice(invoice, products, False)  # No guardar en sheets automáticamente
            
            return invoice, products, pdf_path or ""
            
        except Exception as e:
            logger.error(f"Error al procesar pedido: {e}")
            return None