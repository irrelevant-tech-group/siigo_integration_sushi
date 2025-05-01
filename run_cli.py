import os
import json
import base64
import datetime
import gspread
import logging
import sqlite3
import time
from PIL import Image
from dotenv import load_dotenv
from google.oauth2.service_account import Credentials
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image as ReportLabImage
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
import requests
import time
import anthropic

# Importar la clase SiigoAPI
try:
    from apis.siigo_api import SiigoAPIClient
    SIIGO_AVAILABLE = True
except ImportError:
    SIIGO_AVAILABLE = False
    print("Advertencia: No se encontró el módulo siigo_api. La funcionalidad de facturación electrónica estará limitada.")

# Configuración de Google Sheets
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets',
    'https://www.googleapis.com/auth/drive'
]
SPREADSHEET_ID = "1cHrdIEDH_gNUsjFUZjwqw-wSmi04yOV_6RtXXUyDrVc"

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("siigo_gsheets.log"),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('siigo_gsheets')

# Función para cargar manualmente el archivo .env
def load_env_file():
    env_vars = {}
    try:
        with open('.env', 'r') as f:
            for line in f:
                line = line.strip()
                if line and not line.startswith('#'):
                    key, value = line.split('=', 1)
                    env_vars[key] = value
        return env_vars
    except Exception as e:
        logger.error(f"Error al cargar el archivo .env: {e}")
        return {}

# Cargar variables de entorno
load_dotenv()
env_vars = load_env_file()

class SiigoGSheetsIntegration:
    """Clase para integrar Google Sheets con Siigo API y generar facturas desde imágenes"""
    
    def __init__(self, db_path="siigo_gsheets.db"):
        """Inicializa la integración con base de datos local y recursos necesarios"""
        self.db_path = db_path
        self.setup_database()
        
        # Inicializar API de Siigo si está disponible
        self.siigo_api = None
        if SIIGO_AVAILABLE and self._check_siigo_credentials():
            try:
                self.siigo_api = SiigoAPIClient()
                logger.info("API de Siigo inicializada correctamente")
            except Exception as e:
                logger.error(f"Error al inicializar API de Siigo: {e}")
        
        # Inicializar cliente de Google Sheets
        self.gs_client = self._get_google_sheets_client()
        
        # Configuración de Claude API
        self.claude_api_key = env_vars.get("ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
        if not self.claude_api_key:
            logger.warning("No se encontró la API key de Anthropic. La detección de imágenes no funcionará.")
    
    def _check_siigo_credentials(self):
        """Verifica si existen las credenciales de Siigo necesarias"""
        username = os.getenv("SIIGO_USERNAME")
        access_key = os.getenv("SIIGO_ACCESS_KEY")
        
        if username and access_key:
            return True
        
        logger.warning("No se encontraron credenciales de Siigo. Se utilizará generación de PDF solamente.")
        return False
    
    def setup_database(self):
        """Configura la base de datos local para la integración"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # Crear tabla para facturas locales
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS facturas_locales (
            id TEXT PRIMARY KEY,
            cliente_id TEXT,
            cliente_nombre TEXT,
            cliente_identificacion TEXT,
            fecha TEXT,
            total REAL,
            productos TEXT,
            estado TEXT,
            pdf_path TEXT,
            siigo_id TEXT,
            fecha_actualizacion TEXT
        )
        ''')
        
        # Crear tabla para items de facturas
        cursor.execute('''
        CREATE TABLE IF NOT EXISTS items_factura (
            id TEXT PRIMARY KEY,
            factura_id TEXT,
            producto_id TEXT,
            producto_nombre TEXT,
            cantidad REAL,
            precio REAL,
            impuesto_id TEXT,
            total REAL,
            FOREIGN KEY (factura_id) REFERENCES facturas_locales(id)
        )
        ''')
        
        conn.commit()
        conn.close()
        logger.info("Base de datos configurada correctamente")
    
    def _get_google_sheets_client(self):
        """Obtiene un cliente autorizado para Google Sheets"""
        try:
            creds_file = env_vars.get("GOOGLE_CREDS_FILE") or "creds.json"
            creds = Credentials.from_service_account_file(creds_file, scopes=SCOPES)
            return gspread.authorize(creds)
        except Exception as e:
            logger.error(f"Error al obtener cliente de Google Sheets: {e}")
            return None
    
    def normalize_text(self, text):
        """Normaliza el texto para comparaciones insensibles a tildes y caracteres especiales"""
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
    
    def clean_price(self, price_str):
        """Limpia un string de precio para convertirlo a float"""
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
            logger.error(f"Error al convertir precio: {price_str}")
            return 0.0
    
    def load_image(self, image_path):
        """Carga una imagen desde una ruta y la codifica en base64"""
        try:
            with open(image_path, "rb") as image_file:
                return base64.b64encode(image_file.read()).decode('utf-8')
        except Exception as e:
            logger.error(f"Error al cargar la imagen: {e}")
            return None
    
    def process_image_with_claude(self, image_base64, system_prompt, user_prompt):
        """Procesa la imagen usando la API de Claude Vision con un prompt personalizado"""
        if not self.claude_api_key:
            logger.error("No se puede procesar la imagen: API key de Claude no configurada")
            return None
        
        client = anthropic.Anthropic(api_key=self.claude_api_key)
        
        try:
            message = client.messages.create(
                model="claude-3-haiku-20240307",
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
            return message.content[0].text
        except Exception as e:
            logger.error(f"Error al procesar con Claude: {e}")
            return None
        
    def extract_json_from_response(self, response_text):
        """Extrae un objeto JSON del texto de respuesta"""
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
                logger.warning("No se encontró formato JSON en la respuesta")
                return {"error": "Formato de respuesta no reconocido"}
        except json.JSONDecodeError as e:
            logger.error(f"Error al decodificar JSON: {e}")
            logger.debug(f"Texto recibido: {response_text}")
            return {"error": "Error al decodificar la respuesta"}
    
    def get_products_data(self):
        """Obtiene los datos de productos desde Google Sheets"""
        try:
            if not self.gs_client:
                logger.error("Cliente de Google Sheets no inicializado")
                return []
            
            spreadsheet = self.gs_client.open_by_key(SPREADSHEET_ID)
            worksheet = spreadsheet.worksheet("Productos")
            return worksheet.get_all_records()
        except Exception as e:
            logger.error(f"Error al obtener datos de productos: {e}")
            return []
    
    def get_client_data(self, client_name=None):
        """Obtiene los datos del cliente desde Google Sheets con búsqueda por nombre"""
        try:
            if not self.gs_client:
                logger.error("Cliente de Google Sheets no inicializado")
                return None
            
            spreadsheet = self.gs_client.open_by_key(SPREADSHEET_ID)
            worksheet = spreadsheet.worksheet("Clientes")
            clients = worksheet.get_all_records()
            
            if client_name:
                # Normalizar el nombre buscado
                normalized_search = self.normalize_text(client_name)
                
                # Buscar cliente con comparación flexible
                best_match = None
                best_score = 0
                
                for client_data in clients:
                    normalized_client = self.normalize_text(client_data['nombre_cliente'])
                    
                    # Calcular similitud simple (coincidencia de palabras)
                    search_words = set(normalized_search.split())
                    client_words = set(normalized_client.split())
                    common_words = search_words.intersection(client_words)
                    
                    if len(common_words) > 0:
                        score = len(common_words) / max(len(search_words), len(client_words))
                        if score > best_score:
                            best_score = score
                            best_match = client_data
                
                # Si hay buena coincidencia (más del 60% de similitud)
                if best_match and best_score > 0.6:
                    logger.info(f"Cliente encontrado: {best_match['nombre_cliente']} (Coincidencia: {best_score:.0%})")
                    return best_match
                
                # Si hay coincidencia parcial (más del 30%)
                if best_match and best_score > 0.3:
                    logger.info(f"Posible coincidencia: {best_match['nombre_cliente']} (Coincidencia: {best_score:.0%})")
                    confirm = input(f"¿Confirmar que '{client_name}' es '{best_match['nombre_cliente']}'? (s/n): ")
                    if confirm.lower() == 's':
                        return best_match
                
                logger.warning(f"No se encontró coincidencia suficiente para: {client_name}")
                print("Clientes disponibles:")
                for i, client_data in enumerate(clients):
                    print(f"{i+1}. {client_data['nombre_cliente']}")
                
                selection = input("Selecciona el número del cliente (o Enter para cancelar): ")
                if selection.strip() and selection.isdigit():
                    index = int(selection) - 1
                    if 0 <= index < len(clients):
                        return clients[index]
                return None
            
            # Si no se especifica cliente, mostrar lista para seleccionar
            if clients:
                print("Clientes disponibles:")
                for i, client_data in enumerate(clients):
                    print(f"{i+1}. {client_data['nombre_cliente']}")
                
                selection = input("Selecciona el número del cliente (o Enter para cancelar): ")
                if selection.strip() and selection.isdigit():
                    index = int(selection) - 1
                    if 0 <= index < len(clients):
                        return clients[index]
                return None
            
            logger.warning("No hay clientes registrados.")
            return None
        
        except Exception as e:
            logger.error(f"Error al obtener datos del cliente: {e}")
            return None
    
    def find_product_price(self, products_data, product_name):
        """Busca el precio de un producto basado en su nombre con comparación flexible"""
        if not product_name:
            return None
        
        # Normalizar el nombre del producto buscado
        normalized_search = self.normalize_text(product_name)
        
        # Intentar encontrar coincidencia con comparación flexible
        best_match = None
        best_score = 0
        
        for product in products_data:
            normalized_product = self.normalize_text(product['nombre_producto'])
            
            # Calcular similitud simple (coincidencia de palabras)
            search_words = set(normalized_search.split())
            product_words = set(normalized_product.split())
            common_words = search_words.intersection(product_words)
            
            if len(common_words) > 0:
                score = len(common_words) / max(len(search_words), len(product_words))
                if score > best_score:
                    best_score = score
                    best_match = product
        
        # Si hay buena coincidencia (más del 70% de similitud)
        if best_match and best_score > 0.7:
            logger.info(f"Producto encontrado: {best_match['nombre_producto']} (Coincidencia: {best_score:.0%})")
            return best_match
        
        # Si hay coincidencia parcial (más del 40%)
        if best_match and best_score > 0.4:
            logger.info(f"Posible coincidencia para '{product_name}': '{best_match['nombre_producto']}' (Coincidencia: {best_score:.0%})")
            confirm = input(f"¿Confirmar que '{product_name}' es '{best_match['nombre_producto']}'? (s/n): ")
            if confirm.lower() == 's':
                return best_match
        
        logger.warning(f"No se encontró ningún producto que coincida con '{product_name}'")
        return None
    
    def generate_invoice_data(self, products_info, client_data):
        """Genera los datos de la factura basados en la información de productos y cliente"""
        try:
            # Calcular el valor total
            total = sum(p['precio'] * p['cantidad'] for p in products_info)
            
            # Formatear la lista de productos
            products_list = "\n".join([f"{p['nombre']} x {p['cantidad']} = ${p['precio'] * p['cantidad']:.2f}" for p in products_info])
            
            # Crear la factura
            invoice = {
                "fecha_emision": datetime.datetime.now().strftime("%Y-%m-%d"),
                "nombre_cliente": client_data['nombre_cliente'],
                "identificacion": client_data['identificacion'],
                "productos_facturados": products_list,
                "valor_total": total,
                "factura_id": f"FACT-{datetime.datetime.now().strftime('%Y%m%d%H%M%S')}",
                "estado": "Preparado"
            }
            
            return invoice
        
        except Exception as e:
            logger.error(f"Error al generar la factura: {e}")
            return None
    
    def generate_invoice_pdf(self, invoice_data, products_info, output_path="factura.pdf"):
        """Genera un archivo PDF con la factura"""
        try:
            doc = SimpleDocTemplate(output_path, pagesize=letter)
            styles = getSampleStyleSheet()
            elements = []
            
            # Estilos personalizados
            title_style = ParagraphStyle(
                'TitleStyle',
                parent=styles['Heading1'],
                alignment=1,  # Centrado
                spaceAfter=12
            )
            
            subtitle_style = ParagraphStyle(
                'SubtitleStyle',
                parent=styles['Heading2'],
                fontSize=14,
                alignment=0,  # Izquierda
                spaceAfter=6
            )
            
            normal_style = styles['Normal']
            
            # Título de la factura
            elements.append(Paragraph("FACTURA", title_style))
            elements.append(Spacer(1, 0.1 * inch))
            
            # Información de la factura
            elements.append(Paragraph(f"Factura #: {invoice_data['factura_id']}", subtitle_style))
            elements.append(Paragraph(f"Fecha: {invoice_data['fecha_emision']}", normal_style))
            elements.append(Spacer(1, 0.2 * inch))
            
            # Información del cliente
            elements.append(Paragraph("Información del Cliente", subtitle_style))
            cliente_data = [
                ["Cliente:", invoice_data['nombre_cliente']],
                ["Identificación:", invoice_data['identificacion']]
            ]
            cliente_table = Table(cliente_data, colWidths=[1.5*inch, 4*inch])
            cliente_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (0, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('PADDING', (0, 0), (-1, -1), 6)
            ]))
            elements.append(cliente_table)
            elements.append(Spacer(1, 0.2 * inch))
            
            # Tabla de productos
            elements.append(Paragraph("Detalle de Productos", subtitle_style))
            
            # Encabezados de la tabla
            products_data = [["Producto", "Cantidad", "Precio Unit.", "Total"]]
            
            # Filas de productos
            for product in products_info:
                price_unit = product['precio']
                price_total = price_unit * product['cantidad']
                products_data.append([
                    product['nombre'],
                    str(product['cantidad']),
                    f"${price_unit:.2f}",
                    f"${price_total:.2f}"
                ])
            
            # Fila de total
            total = invoice_data['valor_total']
            products_data.append(["", "", "TOTAL", f"${total:.2f}"])
            
            # Crear tabla de productos
            products_table = Table(products_data, colWidths=[3*inch, 1*inch, 1.5*inch, 1.5*inch])
            products_table.setStyle(TableStyle([
                ('BACKGROUND', (0, 0), (-1, 0), colors.lightgrey),
                ('BACKGROUND', (2, -1), (3, -1), colors.lightgrey),
                ('GRID', (0, 0), (-1, -1), 0.5, colors.black),
                ('SPAN', (0, -1), (1, -1)),  # Combinar celdas en la fila del total
                ('ALIGN', (1, 0), (3, -1), 'RIGHT'),  # Alinear a la derecha cantidades y precios
                ('FONTWEIGHT', (0, 0), (-1, 0), 'BOLD'),  # Encabezados en negrita
                ('FONTWEIGHT', (2, -1), (3, -1), 'BOLD'),  # Total en negrita
                ('PADDING', (0, 0), (-1, -1), 6)
            ]))
            elements.append(products_table)
            
            # Pie de factura
            elements.append(Spacer(1, 0.3 * inch))
            elements.append(Paragraph("Gracias por su compra", ParagraphStyle(
                'Footer',
                parent=styles['Normal'],
                alignment=1,  # Centrado
                fontSize=10,
                textColor=colors.darkblue
            )))
            
            # Generar PDF
            doc.build(elements)
            logger.info(f"Factura PDF generada: {os.path.abspath(output_path)}")
            return os.path.abspath(output_path)
            
        except Exception as e:
            logger.error(f"Error al generar PDF: {e}")
            return None
    
    def save_invoice_to_sheets(self, invoice_data):
        """Guarda la factura en la hoja de Historial Facturación"""
        try:
            if not self.gs_client:
                logger.error("Cliente de Google Sheets no inicializado")
                return False
            
            spreadsheet = self.gs_client.open_by_key(SPREADSHEET_ID)
            worksheet = spreadsheet.worksheet("Historial Facturación")
            
            # Preparar los datos para insertar
            row = [
                invoice_data['fecha_emision'],
                invoice_data['nombre_cliente'],
                invoice_data['identificacion'],
                invoice_data['productos_facturados'],
                invoice_data['valor_total'],
                invoice_data['factura_id'],
                invoice_data.get('pdf_url', ''),
                invoice_data.get('payload_json', ''),
                invoice_data['estado']
            ]
            
            # Agregar la factura como nueva fila
            worksheet.append_row(row)
            logger.info(f"Factura {invoice_data['factura_id']} guardada correctamente en Google Sheets.")
            return True
        
        except Exception as e:
            logger.error(f"Error al guardar la factura en Google Sheets: {e}")
            return False
    
    def save_invoice_to_db(self, invoice_data, products_info):
        """Guarda la factura en la base de datos local"""
        try:
            conn = sqlite3.connect(self.db_path)
            cursor = conn.cursor()
            
            # Insertar factura
            cursor.execute('''
            INSERT INTO facturas_locales
            (id, cliente_nombre, cliente_identificacion, fecha, total, productos, estado, pdf_path, fecha_actualizacion)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                invoice_data['factura_id'],
                invoice_data['nombre_cliente'],
                invoice_data['identificacion'],
                invoice_data['fecha_emision'],
                invoice_data['valor_total'],
                invoice_data['productos_facturados'],
                invoice_data['estado'],
                invoice_data.get('pdf_url', ''),
                datetime.datetime.now().isoformat()
            ))
            
            # Insertar items de factura
            for product in products_info:
                item_id = f"{invoice_data['factura_id']}-{product['nombre']}-{time.time()}"
                cursor.execute('''
                INSERT INTO items_factura
                (id, factura_id, producto_nombre, cantidad, precio, total)
                VALUES (?, ?, ?, ?, ?, ?)
                ''', (
                    item_id,
                    invoice_data['factura_id'],
                    product['nombre'],
                    product['cantidad'],
                    product['precio'],
                    product['precio'] * product['cantidad']
                ))
            
            conn.commit()
            conn.close()
            logger.info(f"Factura {invoice_data['factura_id']} guardada en base de datos local")
            return True
        
        except Exception as e:
            logger.error(f"Error al guardar factura en base de datos local: {e}")
            return False
    
    def display_invoice(self, invoice_data, products_info):
        """Muestra la factura en formato legible en la consola"""
        print("\n" + "="*50)
        print(f"{'FACTURA':^50}")
        print("="*50)
        print(f"Factura #: {invoice_data['factura_id']}")
        print(f"Fecha: {invoice_data['fecha_emision']}")
        print("-"*50)
        print(f"Cliente: {invoice_data['nombre_cliente']}")
        print(f"Identificación: {invoice_data['identificacion']}")
        print("-"*50)
        print("PRODUCTOS:")
        
        for product in products_info:
            price = product['precio'] * product['cantidad']
            print(f"{product['nombre']} x {product['cantidad']} = ${price:.2f}")
        
        print("-"*50)
        print(f"TOTAL: ${invoice_data['valor_total']:.2f}")
        print("="*50)
    
    def generate_siigo_invoice(self, invoice_data, products_info, client_data, send_to_dian=False):
        """Genera una factura electrónica en Siigo a partir de los datos de factura"""
        try:
            if not self.siigo_api:
                logger.error("No se puede generar factura electrónica: API de Siigo no inicializada")
                return None

            # 1. Transformar la información al formato requerido por Siigo

            # Buscar información del cliente en Siigo
            customers = self.siigo_api.get_customers(identification=client_data['identificacion'])
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
                    customer_result = self.siigo_api.create_customer(new_customer)
                    customer_id = customer_result['id']
                    logger.info(f"Cliente creado en Siigo con ID: {customer_id}")
                except Exception as e:
                    logger.error(f"Error al crear cliente en Siigo: {e}")
                    return None

            # 2. Obtener los productos en Siigo o crearlos si no existen
            invoice_items = []
            for product_info in products_info:
                product_code = product_info.get('producto_id', f"P{int(time.time())}")
                product_name = product_info['nombre']

                siigo_products = self.siigo_api.get_products(code=product_code)
                product_id = None

                if siigo_products and 'results' in siigo_products and len(siigo_products['results']) > 0:
                    product_id = siigo_products['results'][0]['id']
                    logger.info(f"Producto encontrado en Siigo: {product_name} (ID: {product_id})")
                else:
                    logger.info(f"Producto no encontrado en Siigo, creando nuevo producto: {product_name}")
                    new_product = {
                        "code": product_code,
                        "name": product_name,
                        "account_group": 1253,
                        "type": "Product",
                        "stock_control": True,
                        "active": True,
                        "tax_classification": "Taxed",
                        "taxes": [{"id": product_info.get('impuesto_id', 13156)}],
                        "prices": [{
                            "currency_code": "COP",
                            "price_list": [
                                {
                                    "position": 1,
                                    "value": float(product_info['precio'])
                                }
                            ]
                        }]
                    }
                    try:
                        product_result = self.siigo_api.create_product(new_product)
                        product_id = product_result['id']
                        logger.info(f"Producto creado en Siigo: {product_name} (ID: {product_id})")
                    except Exception as e:
                        logger.error(f"Error al crear producto en Siigo: {e}")
                        continue
                
                # Si el producto no tiene cantidad, no se agrega
                if product_info['cantidad'] > 0:
                    invoice_items.append({
                        "code": product_code,
                        "description": product_name,
                        "quantity": float(product_info['cantidad']),
                        "price": float(product_info['precio']),
                        "discount": 0
                    })

            # 3. Obtener vendedor/usuario correctamente
            users_data = self.siigo_api.get_users()
            if isinstance(users_data, dict) and 'results' in users_data:
                users_list = users_data['results']
            elif isinstance(users_data, list):
                users_list = users_data
            else:
                users_list = []

            if users_list:
                logger.info(f"Usuarios disponibles en Siigo: {len(users_list)}")
                for i, user in enumerate(users_list):
                    logger.info(f"Usuario {i+1}: ID {user.get('id')}, Nombre: {user.get('first_name')} {user.get('last_name')}")
                seller_id = users_list[0].get('id')
                logger.info(f"Usando usuario vendedor con ID: {seller_id}")
            else:
                seller_id = None
                logger.warning("No se encontraron usuarios registrados en Siigo")

            # 4. Preparar documento para factura electrónica y obtener su configuración
            document_types = self.siigo_api.get_document_types("FV")
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

            requires_manual_number = False
            invoice_number = None
            if selected_document_type and selected_document_type.get('automatic_number') is False:
                requires_manual_number = True
                invoice_number = selected_document_type.get('consecutive', 1)
                logger.info(f"El documento requiere numeración manual. Usando consecutivo: {invoice_number}")

            # 5. Preparar pagos correctamente
            payment_types = self.siigo_api.get_payment_types("FV")
            if payment_types:
                logger.info(f"Formas de pago disponibles: {len(payment_types)}")
                for i, payment in enumerate(payment_types):
                    logger.info(f"Pago {i+1}: ID {payment.get('id')}, Nombre: {payment.get('name')}")
                payment_id = payment_types[0]['id']
                logger.info(f"Usando forma de pago con ID: {payment_id}")
            else:
                logger.error("No se encontraron formas de pago disponibles")
                payment_id = None

            # 6. Crear la estructura base del documento
            invoice_data_siigo = {
                "document": {"id": document_id},
                "date": datetime.datetime.now().strftime("%Y-%m-%d"),
                "customer": {"identification": str(client_data['identificacion']), "branch_office": 0},
                "seller": seller_id,
                "observations": f"Factura generada automáticamente. Ref: {invoice_data['factura_id']}",
                "items": invoice_items,
                "payments": [{
                    "id": payment_id,
                    "value": invoice_data['valor_total'],
                    "due_date": datetime.datetime.now().strftime("%Y-%m-%d")
                }],
                "stamp": {"send": send_to_dian},
                "mail": {"send": True}
            }

            if requires_manual_number and invoice_number is not None:
                invoice_data_siigo["document"]["number"] = invoice_number

            try:
                logger.info(f"Enviando factura a Siigo: {json.dumps(invoice_data_siigo, indent=2)}")
                logger.info("Intentando crear factura en Siigo...")
                result = self.siigo_api.create_invoice(invoice_data_siigo)

                if result and 'id' in result:
                    logger.info(f"Factura electrónica creada exitosamente en Siigo ID: {result['id']}")

                    conn = sqlite3.connect(self.db_path)
                    cursor = conn.cursor()
                    cursor.execute('''
                    UPDATE facturas_locales 
                    SET siigo_id = ?, estado = ? 
                    WHERE id = ?
                    ''', (
                        result['id'],
                        'Facturado en Siigo',
                        invoice_data['factura_id']
                    ))
                    conn.commit()
                    conn.close()

                    invoice_data['estado'] = 'Facturado en Siigo'
                    invoice_data['siigo_id'] = result['id']
                    return result['id']
                else:
                    logger.error(f"Respuesta inválida de Siigo: {result}")
                    return None

            except Exception as e:
                import traceback
                logger.error(f"Error al crear factura en Siigo: {str(e)}")
                logger.error(f"Traceback completo: {traceback.format_exc()}")
                return None

        except Exception as e:
            logger.error(f"Error general en generación de factura Siigo: {e}")
            return None

    def process_order_from_image(self, image_path):
        """Procesa un pedido a partir de una imagen y genera una factura"""
        if not os.path.exists(image_path):
            logger.error(f"Error: La imagen '{image_path}' no existe.")
            return None

        logger.info("Cargando imagen...")
        image_base64 = self.load_image(image_path)
        if not image_base64:
            return None

        logger.info("Identificando al cliente en la imagen...")
        client_system_prompt = (
            "Eres un asistente especializado en extraer información de clientes en imágenes. "
            "Analiza la imagen y extrae el nombre del cliente si está presente. "
            "Responde únicamente con un JSON en el formato: {'cliente': 'nombre_del_cliente'}"
        )
        client_user_prompt = (
            "Identifica si hay algún nombre de cliente en esta imagen. "
            "Solo necesito el nombre, sin títulos como 'Sr.' o 'Sra.'. "
            "Si no hay un cliente claramente identificable, devuelve un JSON con cliente vacío."
        )
        client_response = self.process_image_with_claude(image_base64, client_system_prompt, client_user_prompt)
        if not client_response:
            logger.error("No se pudo procesar la imagen para identificar al cliente. ")
            return None
        client_data = self.extract_json_from_response(client_response)
        detected_client_name = client_data.get('cliente', '')

        if detected_client_name:
            logger.info(f"Cliente detectado en la imagen: {detected_client_name}")
        else:
            logger.info("No se detectó ningún cliente en la imagen.")

        logger.info("Procesando productos en la imagen...")
        product_system_prompt = (
            "Eres un asistente especializado en extraer información de imágenes de pedidos. "
            "Analiza la imagen y extrae una lista de productos y sus cantidades. "
            "Responde **exclusivamente** con un JSON en el formato: "
            "{'productos': [{'nombre': 'nombre del producto', 'cantidad': número}]}"
        )
        product_user_prompt = (
            "Identifica todos los productos y sus cantidades en esta imagen. "
            "Devuelve solo un objeto JSON con la lista de productos y cantidades."
            "{'productos': [{'nombre': 'nombre del producto', 'cantidad': número}]}"
        )
        products_response = self.process_image_with_claude(image_base64, product_system_prompt, product_user_prompt)
        if not products_response:
            logger.error("No se pudo procesar la imagen para identificar los productos.")
            return None

        products_data = self.extract_json_from_response(products_response)
        if "error" in products_data:
            logger.error(f"Error: {products_data['error']}")
            return None
        if "productos" not in products_data or len(products_data["productos"]) == 0:
            logger.error("No se encontraron productos en la imagen.")
            return None

        print("\nProductos identificados en la imagen:")
        for i, product in enumerate(products_data["productos"]):
            print(f"{i+1}. {product['nombre']} - Cantidad: {product['cantidad']}")

        logger.info("\nBuscando información del cliente...")
        client_info = self.get_client_data(detected_client_name)
        if not client_info:
            logger.error("No se pudo obtener información del cliente para generar la factura.")
            return None

        logger.info("Obteniendo catálogo de productos...")
        products_catalog = self.get_products_data()
        if not products_catalog:
            logger.error("No se encontraron productos en el catálogo.")
            return None

        logger.info("Buscando información detallada de los productos...")
        detailed_products = []
        for product in products_data["productos"]:
            product_name = product["nombre"]
            product_qty = product["cantidad"]

            product_details = self.find_product_price(products_catalog, product_name)
            if product_details:
                detailed_products.append({
                    "nombre": product_details["nombre_producto"],
                    "cantidad": product_qty,
                    "precio": self.clean_price(product_details["precio_unitario"]),
                    "producto_id": product_details["producto_id"],
                    "impuesto_id": product_details.get("impuesto_id", "")
                })
            else:
                logger.warning(f"Advertencia: No se encontró el producto '{product_name}' en el catálogo.")
                price_input = input(f"Ingresa el precio unitario para '{product_name}' (o presiona Enter para omitir): ")
                if price_input.strip() and price_input.replace('.', '', 1).isdigit():
                    detailed_products.append({
                        "nombre": product_name,
                        "cantidad": product_qty,
                        "precio": float(price_input),
                        "producto_id": "MANUAL",
                        "impuesto_id": ""
                    })

        if not detailed_products:
            logger.error("No se pudo obtener información suficiente para generar la factura.")
            return None

        logger.info("Generando factura...")
        invoice = self.generate_invoice_data(detailed_products, client_info)
        if not invoice:
            return None

        self.display_invoice(invoice, detailed_products)

        logger.info("\nGenerando PDF de la factura...")
        timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
        pdf_filename = f"factura_{invoice['factura_id']}_{timestamp}.pdf"
        pdf_path = self.generate_invoice_pdf(invoice, detailed_products, pdf_filename)

        if pdf_path:
            invoice['pdf_url'] = pdf_path
            logger.info(f"PDF generado exitosamente: {pdf_path}")

        self.save_invoice_to_db(invoice, detailed_products)
        logger.info("Guardando factura en el historial de Google Sheets")
        self.save_invoice_to_sheets(invoice)

        siigo_id = None
        if self.siigo_api:
            confirm_dian = input("\n¿Enviar directamente a la DIAN? (s/n): ")
            send_to_dian = confirm_dian.lower() == 's'
            logger.info(
                f"Generando factura electrónica en Siigo{' y enviando a DIAN' if send_to_dian else ' (sin enviar a DIAN)'}..."
            )
            siigo_id = self.generate_siigo_invoice(invoice, detailed_products, client_info, send_to_dian)
            if siigo_id:
                logger.info(f"Factura electrónica generada con éxito en Siigo con ID: {siigo_id}")
                invoice['estado'] = 'Facturado en Siigo'
                invoice['siigo_id'] = siigo_id
            else:
                logger.error("No se pudo generar la factura electrónica en Siigo")
        else:
            logger.info("La generación de facturas electrónicas en Siigo no está disponible (API no inicializada)")

        logger.info("\nProceso de facturación completado.")
        return invoice


def main():
    """Función principal para ejecutar el proceso de facturación"""
    print("=" * 80)
    print(f"{'SISTEMA DE FACTURACIÓN CON RECONOCIMIENTO DE IMÁGENES':^80}")
    print("=" * 80)

    integration = SiigoGSheetsIntegration()

    if integration.siigo_api:
        print("📋 Modo: Facturación Electrónica (Siigo) y PDF")
    else:
        print("📋 Modo: Facturación PDF solamente")

    while True:
        print("\nOpciones:")
        print("1. Procesar pedido desde imagen")
        print("2. Ver historial de facturas")
        print("3. Verificar conexión con Siigo")
        print("4. Verificar conexión con Google Sheets")
        print("0. Salir")

        option = input("\nSelecciona una opción: ")

        if option == "0":
            print("Saliendo del sistema...")
            break
        elif option == "1":
            image_path = input("Ruta de la imagen del pedido (Enter para usar image_pedido.jpg): ") or "image_pedido.jpg"
            if not os.path.exists(image_path):
                print(f"Error: La imagen '{image_path}' no existe.")
            else:
                integration.process_order_from_image(image_path)
        elif option == "2":
            print("\n--- HISTORIAL DE FACTURAS ---")
            try:
                conn = sqlite3.connect(integration.db_path)
                cursor = conn.cursor()
                cursor.execute('''
                SELECT id, cliente_nombre, fecha, total, estado 
                FROM facturas_locales ORDER BY fecha DESC LIMIT 10
                ''')
                facturas = cursor.fetchall()
                conn.close()

                if facturas:
                    print("\nÚltimas 10 facturas:")
                    print("-" * 90)
                    print(f"{'ID':^20} | {'Cliente':^30} | {'Fecha':^12} | {'Total':^10} | {'Estado':^15}")
                    print("-" * 90)
                    for factura in facturas:
                        print(
                            f"{factura[0]:^20} | {factura[1][:28]:^30} | {factura[2]:^12} | "
                            f"${factura[3]:<9.2f} | {factura[4]:^15}"
                        )
                    print("-" * 90)
                else:
                    print("No hay facturas registradas.")
            except Exception as e:
                print(f"Error al obtener el historial: {e}")
        elif option == "3":
            if integration.siigo_api:
                try:
                    token = integration.siigo_api.get_token()
                    if token:
                        print("✅ Conexión con Siigo API establecida correctamente")
                    else:
                        print("❌ No se pudo obtener token de Siigo API")
                except Exception as e:
                    print(f"❌ Error al conectar con Siigo API: {e}")
            else:
                print("❌ API de Siigo no inicializada. Verifique las credenciales en .env")
        elif option == "4":
            if integration.gs_client:
                try:
                    spreadsheet = integration.gs_client.open_by_key(SPREADSHEET_ID)
                    worksheets = spreadsheet.worksheets()
                    print("✅ Conexión con Google Sheets establecida correctamente")
                    print(f"   Hojas disponibles: {', '.join([ws.title for ws in worksheets])}")
                except Exception as e:
                    print(f"❌ Error al conectar con Google Sheets: {e}")
            else:
                print("❌ Cliente de Google Sheets no inicializado. Verifique el archivo de credenciales.")
        else:
            print("Opción no válida")


if __name__ == "__main__":
    main()  