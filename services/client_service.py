"""
Servicio para gestión de clientes.
"""
from typing import List, Dict, Any, Optional

from apis.google_sheets_api import GoogleSheetsClient
from config.logging_config import logger
from database.models import Client
from utils.text_utils import normalize_text, calculate_similarity


class ClientService:
    """Servicio para la gestión de clientes"""
    
    def __init__(self, sheets_client: GoogleSheetsClient):
        """
        Inicializa el servicio de clientes.
        
        Args:
            sheets_client: Cliente de Google Sheets
        """
        self.sheets_client = sheets_client
    
    def get_all_clients(self) -> List[Dict[str, Any]]:
        """
        Obtiene todos los clientes registrados.
        
        Returns:
            Lista de clientes
        """
        return self.sheets_client.get_clients()
    
    def find_client_by_id(self, identification: str) -> Optional[Dict[str, Any]]:
        """
        Busca un cliente por su número de identificación.
        
        Args:
            identification: Número de identificación
            
        Returns:
            Datos del cliente o None si no se encuentra
        """
        clients = self.get_all_clients()
        for client in clients:
            if client.get('identificacion') == identification:
                return client
        return None
    
    def find_client_by_name(self, name: str, threshold: float = 0.6) -> Optional[Dict[str, Any]]:
        """
        Busca un cliente por su nombre con comparación flexible.
        
        Args:
            name: Nombre del cliente a buscar
            threshold: Umbral de similitud (0.0 a 1.0)
            
        Returns:
            Datos del cliente o None si no se encuentra con suficiente similitud
        """
        if not name:
            return None
            
        clients = self.get_all_clients()
        if not clients:
            logger.warning("No hay clientes registrados")
            return None
            
        normalized_search = normalize_text(name)
        best_match = None
        best_score = 0
        
        for client_data in clients:
            client_name = client_data.get('nombre_cliente', '')
            similarity = calculate_similarity(normalized_search, client_name)
            
            if similarity > best_score:
                best_score = similarity
                best_match = client_data
        
        # Si la mejor coincidencia supera el umbral, devolverla
        if best_match and best_score >= threshold:
            logger.info(f"Cliente encontrado: {best_match['nombre_cliente']} (Coincidencia: {best_score:.0%})")
            return best_match
            
        # Si hay una coincidencia parcial, podemos registrarla
        if best_match and best_score >= threshold / 2:
            logger.info(f"Posible coincidencia: {best_match['nombre_cliente']} (Coincidencia: {best_score:.0%})")
            return best_match
            
        logger.warning(f"No se encontró coincidencia suficiente para: {name}")
        return None
    
    def prompt_client_selection(self) -> Optional[Dict[str, Any]]:
        """
        Solicita al usuario que seleccione un cliente de una lista.
        
        Returns:
            Cliente seleccionado o None si se cancela
        """
        clients = self.get_all_clients()
        
        if not clients:
            logger.warning("No hay clientes registrados")
            return None
        
        print("\nClientes disponibles:")
        for i, client_data in enumerate(clients):
            print(f"{i+1}. {client_data['nombre_cliente']} - {client_data['identificacion']}")
        
        selection = input("\nSelecciona el número del cliente (o Enter para cancelar): ")
        if selection.strip() and selection.isdigit():
            index = int(selection) - 1
            if 0 <= index < len(clients):
                return clients[index]
        
        return None
    
    def confirm_client_match(self, detected_name: str, possible_match: Dict[str, Any]) -> bool:
        """
        Solicita confirmación al usuario sobre una posible coincidencia de cliente.
        
        Args:
            detected_name: Nombre detectado
            possible_match: Posible coincidencia de cliente
            
        Returns:
            True si se confirma, False en caso contrario
        """
        confirm = input(
            f"\n¿Confirmar que '{detected_name}' es '{possible_match['nombre_cliente']}'? (s/n): "
        )
        return confirm.lower() in ('s', 'si', 'sí', 'y', 'yes')
    
    def get_client_data(self, client_name: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Obtiene los datos del cliente, ya sea por nombre o por selección manual.
        
        Args:
            client_name: Nombre del cliente (opcional)
            
        Returns:
            Datos del cliente o None si no se encuentra o se cancela
        """
        if client_name:
            # Buscar por nombre
            client_data = self.find_client_by_name(client_name)
            
            if client_data:
                # Si encontramos una coincidencia buena, devolverla directamente
                similarity = calculate_similarity(client_name, client_data['nombre_cliente'])
                if similarity >= 0.6:
                    return client_data
                
                # Si es coincidencia parcial, pedir confirmación
                if similarity >= 0.3:
                    if self.confirm_client_match(client_name, client_data):
                        return client_data
            
            # Si no hay coincidencia o no se confirma, mostrar lista para selección
            print(f"\nNo se encontró coincidencia clara para '{client_name}'.")
            return self.prompt_client_selection()
        else:
            # Si no se proporciona nombre, solicitar selección manual
            return self.prompt_client_selection()
    
    def create_client_model(self, client_data: Dict[str, Any]) -> Client:
        """
        Crea un modelo de cliente a partir de datos de diccionario.
        
        Args:
            client_data: Datos del cliente
            
        Returns:
            Objeto Client
        """
        return Client.from_dict(client_data)