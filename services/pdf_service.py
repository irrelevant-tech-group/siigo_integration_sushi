"""
Servicio para la generación de PDFs de facturas.
"""
import os
from typing import List, Optional
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch

from config.logging_config import logger
from database.models import Invoice, Product


class PDFService:
    """Servicio para la generación de documentos PDF"""
    
    def __init__(self, output_dir: str = ""):
        """
        Inicializa el servicio de PDF.
        
        Args:
            output_dir: Directorio donde se guardarán los PDFs generados
        """
        self.output_dir = output_dir
        
        # Crear directorio si no existe
        if output_dir and not os.path.exists(output_dir):
            try:
                os.makedirs(output_dir)
                logger.info(f"Directorio creado: {output_dir}")
            except Exception as e:
                logger.error(f"Error al crear directorio {output_dir}: {e}")
    
    def generate_invoice_pdf(self, invoice: Invoice, products: List[Product], filename: Optional[str] = None) -> Optional[str]:
        """
        Genera un archivo PDF con la factura.
        
        Args:
            invoice: Datos de la factura
            products: Lista de productos de la factura
            filename: Nombre del archivo (opcional, se genera automáticamente si no se proporciona)
            
        Returns:
            Ruta absoluta al archivo PDF generado o None si hay error
        """
        try:
            # Generar nombre de archivo si no se proporciona
            if not filename:
                timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
                filename = f"factura_{invoice.factura_id}_{timestamp}.pdf"
            
            # Ruta completa del archivo
            file_path = os.path.join(self.output_dir, filename) if self.output_dir else filename
            
            # Crear documento
            doc = SimpleDocTemplate(file_path, pagesize=letter)
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
            elements.append(Paragraph(f"Factura #: {invoice.factura_id}", subtitle_style))
            elements.append(Paragraph(f"Fecha: {invoice.fecha_emision}", normal_style))
            elements.append(Spacer(1, 0.2 * inch))
            
            # Información del cliente
            elements.append(Paragraph("Información del Cliente", subtitle_style))
            cliente_data = [
                ["Cliente:", invoice.nombre_cliente],
                ["Identificación:", invoice.identificacion]
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
            for product in products:
                price_unit = product.precio
                price_total = product.get_total()
                products_data.append([
                    product.nombre,
                    str(product.cantidad),
                    f"${price_unit:.2f}",
                    f"${price_total:.2f}"
                ])
            
            # Fila de total
            total = invoice.valor_total
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
            
            logger.info(f"Factura PDF generada: {os.path.abspath(file_path)}")
            return os.path.abspath(file_path)
            
        except Exception as e:
            logger.error(f"Error al generar PDF: {e}")
            return None