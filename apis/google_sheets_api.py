"""
Cliente para la API de Google Sheets.
"""
from typing import List, Dict, Any, Optional

import gspread
from google.oauth2.service_account import Credentials

from config.settings import SCOPES, SPREADSHEET_ID, GOOGLE_CREDS_FILE
from config.logging_config import logger


class GoogleSheetsClient:
    """Cliente para interactuar con Google Sheets"""
    
    def __init__(self, creds_file: str = GOOGLE_CREDS_FILE, spreadsheet_id: str = SPREADSHEET_ID):
        """
        Inicializa el cliente de Google Sheets.
        
        Args:
            creds_file: Ruta al archivo de credenciales JSON de Google
            spreadsheet_id: ID de la hoja de cálculo
        """
        self.creds_file = creds_file
        self.spreadsheet_id = spreadsheet_id
        self.client = self._get_client()
        self.spreadsheet = None
        
        if self.client:
            try:
                self.spreadsheet = self.client.open_by_key(self.spreadsheet_id)
                logger.info(f"Hoja de cálculo abierta correctamente: {self.spreadsheet.title}")
            except Exception as e:
                logger.error(f"Error al abrir hoja de cálculo: {e}")
    
    def _get_client(self) -> Optional[gspread.Client]:
        """
        Obtiene un cliente autorizado para Google Sheets.
        
        Returns:
            Cliente de gspread o None si hay error
        """
        try:
            creds = Credentials.from_service_account_file(self.creds_file, scopes=SCOPES)
            client = gspread.authorize(creds)
            logger.info("Cliente de Google Sheets inicializado correctamente")
            return client
        except Exception as e:
            logger.error(f"Error al obtener cliente de Google Sheets: {e}")
            return None
    
    def is_available(self) -> bool:
        """
        Verifica si el cliente está correctamente configurado.
        
        Returns:
            True si el cliente está disponible, False en caso contrario
        """
        return self.client is not None and self.spreadsheet is not None
    
    def get_worksheet(self, name: str) -> Optional[gspread.Worksheet]:
        """
        Obtiene una hoja de trabajo por su nombre.
        
        Args:
            name: Nombre de la hoja
            
        Returns:
            Objeto Worksheet o None si no se encuentra o hay error
        """
        if not self.is_available():
            logger.error("Cliente de Google Sheets no disponible")
            return None
            
        try:
            return self.spreadsheet.worksheet(name)
        except Exception as e:
            logger.error(f"Error al obtener hoja '{name}': {e}")
            return None
    
    def get_all_records(self, worksheet_name: str) -> List[Dict[str, Any]]:
        """
        Obtiene todos los registros de una hoja como una lista de diccionarios.
        
        Args:
            worksheet_name: Nombre de la hoja
            
        Returns:
            Lista de registros (filas como diccionarios)
        """
        worksheet = self.get_worksheet(worksheet_name)
        if not worksheet:
            return []
            
        try:
            return worksheet.get_all_records()
        except Exception as e:
            logger.error(f"Error al obtener registros de '{worksheet_name}': {e}")
            return []
    
    def append_row(self, worksheet_name: str, row_data: List[Any]) -> bool:
        """
        Añade una fila a una hoja.
        
        Args:
            worksheet_name: Nombre de la hoja
            row_data: Datos de la fila a añadir
            
        Returns:
            True si se añade correctamente, False en caso contrario
        """
        worksheet = self.get_worksheet(worksheet_name)
        if not worksheet:
            return False
            
        try:
            worksheet.append_row(row_data)
            logger.info(f"Fila añadida correctamente a '{worksheet_name}'")
            return True
        except Exception as e:
            logger.error(f"Error al añadir fila a '{worksheet_name}': {e}")
            return False
    
    def get_clients(self) -> List[Dict[str, Any]]:
        """
        Obtiene la lista de clientes desde la hoja 'Clientes'.
        
        Returns:
            Lista de clientes
        """
        return self.get_all_records("Clientes")
    
    def get_products(self) -> List[Dict[str, Any]]:
        """
        Obtiene la lista de productos desde la hoja 'Productos'.
        
        Returns:
            Lista de productos
        """
        return self.get_all_records("Productos")
    
    def save_invoice_to_sheet(self, invoice_data: Dict[str, Any]) -> bool:
        """
        Guarda una factura en la hoja 'Historial Facturación'.
        
        Args:
            invoice_data: Datos de la factura
            
        Returns:
            True si se guarda correctamente, False en caso contrario
        """
        try:
            # Preparar los datos para insertar
            row = [
                invoice_data.get('fecha_emision', ''),
                invoice_data.get('nombre_cliente', ''),
                invoice_data.get('identificacion', ''),
                invoice_data.get('productos_facturados', ''),
                invoice_data.get('valor_total', 0),
                invoice_data.get('factura_id', ''),
                invoice_data.get('pdf_url', ''),
                invoice_data.get('payload_json', ''),
                invoice_data.get('estado', 'Preparado')
            ]
            
            return self.append_row("Historial Facturación", row)
        except Exception as e:
            logger.error(f"Error al guardar factura en Google Sheets: {e}")
            return False