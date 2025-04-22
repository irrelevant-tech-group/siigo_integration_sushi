"""
Define los modelos de datos para la integración Siigo-Google Sheets.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional, Dict, Any


@dataclass
class Product:
    """Modelo para productos"""
    nombre: str
    cantidad: float
    precio: float
    producto_id: Optional[str] = None
    impuesto_id: Optional[str] = None
    
    def get_total(self) -> float:
        """Calcula el precio total del producto"""
        return self.precio * self.cantidad


@dataclass
class Client:
    """Modelo para clientes"""
    nombre_cliente: str
    identificacion: str
    tipo_persona: str = "Person"
    tipo_identificacion: str = "13"
    direccion: Optional[str] = None
    email: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Client':
        """Crea una instancia de Client desde un diccionario"""
        return cls(
            nombre_cliente=data.get('nombre_cliente', ''),
            identificacion=data.get('identificacion', ''),
            tipo_persona=data.get('tipo_persona', 'Person'),
            tipo_identificacion=data.get('tipo_identificacion', '13'),
            direccion=data.get('direccion', None),
            email=data.get('email', None)
        )


@dataclass
class Invoice:
    """Modelo para facturas"""
    factura_id: str
    fecha_emision: str
    nombre_cliente: str
    identificacion: str
    productos_facturados: str
    valor_total: float
    estado: str = "Preparado"
    pdf_url: Optional[str] = None
    siigo_id: Optional[str] = None
    payload_json: Optional[str] = None
    
    @classmethod
    def create_new(cls, client: Client, products: List[Product]) -> 'Invoice':
        """Crea una nueva factura a partir de datos de cliente y productos"""
        # Calcular el total
        total = sum(product.get_total() for product in products)
        
        # Formatear la lista de productos
        products_list = "\n".join([
            f"{p.nombre} x {p.cantidad} = ${p.get_total():.2f}" 
            for p in products
        ])
        
        # Generar ID único de factura
        invoice_id = f"FACT-{datetime.now().strftime('%Y%m%d%H%M%S')}"
        
        return cls(
            factura_id=invoice_id,
            fecha_emision=datetime.now().strftime("%Y-%m-%d"),
            nombre_cliente=client.nombre_cliente,
            identificacion=client.identificacion,
            productos_facturados=products_list,
            valor_total=total
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convierte la factura en un diccionario"""
        return {
            "factura_id": self.factura_id,
            "fecha_emision": self.fecha_emision,
            "nombre_cliente": self.nombre_cliente,
            "identificacion": self.identificacion,
            "productos_facturados": self.productos_facturados,
            "valor_total": self.valor_total,
            "estado": self.estado,
            "pdf_url": self.pdf_url,
            "siigo_id": self.siigo_id,
            "payload_json": self.payload_json
        }