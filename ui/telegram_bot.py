"""
Interfaz de Telegram para el sistema de facturación.
"""
import os
import tempfile
import logging
from typing import Dict, List, Any, Optional
from datetime import datetime

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    CallbackQueryHandler,
    ConversationHandler,
)

# Google Cloud Storage
from google.cloud import storage

# Importaciones de servicios existentes
from config.logging_config import logger
from config.settings import GCS_BUCKET_NAME, TELEGRAM_TOKEN
from services.client_service import ClientService
from services.image_service import ImageService
from services.invoice_service import InvoiceService
from services.product_service import ProductService
from utils.image_utils import load_image
from utils.text_utils import clean_price, calculate_similarity
from database.models import Product

# Estados para el ConversationHandler
(
    MENU,
    PROCESS_IMAGE,
    CONFIRM_CLIENT,
    CONFIRM_PRODUCTS,
    MANUAL_PRICE,
    CONFIRM_INVOICE,
    CONFIRM_SHEETS,
    CONFIRM_SIIGO,
    CONFIRM_DIAN,
    EDIT_PRODUCT_NAME,
    EDIT_PRODUCT_QUANTITY,
) = range(11)


class TelegramInterface:
    """Interfaz de Telegram para el sistema de facturación"""

    def __init__(
        self,
        invoice_service: InvoiceService,
        client_service: ClientService,
        product_service: ProductService,
        image_service: ImageService,
    ):
        """
        Inicializa la interfaz de Telegram con los servicios existentes.

        Args:
            invoice_service: Servicio de facturas
            client_service: Servicio de clientes
            product_service: Servicio de productos
            image_service: Servicio de procesamiento de imágenes
        """
        # Asignar servicios existentes
        self.invoice_service = invoice_service
        self.client_service = client_service
        self.product_service = product_service
        self.image_service = image_service

        # Cliente de Google Cloud Storage
        self.storage_client = None
        self.bucket = None
        try:
            self.storage_client = storage.Client()
            self.bucket = self.storage_client.bucket(GCS_BUCKET_NAME)
            logger.info(f"Bucket de Google Cloud Storage configurado: {GCS_BUCKET_NAME}")
        except Exception as e:
            logger.error(f"Error al inicializar Google Cloud Storage: {e}")

        # Datos temporales para las conversaciones en Telegram
        self.user_data: Dict[int, Dict[str, Any]] = {}

    def setup_bot(self):
        """Configura el bot de Telegram con los manejadores necesarios"""
        # Verificar token
        if not TELEGRAM_TOKEN:
            logger.error("Token de Telegram no configurado en variables de entorno")
            return None

        # Crear la aplicación
        application = Application.builder().token(TELEGRAM_TOKEN).build()

        # Definir el manejador de conversación para procesar pedidos
        conv_handler = ConversationHandler(
            entry_points=[CommandHandler("start", self.start_command)],
            states={
                MENU: [CallbackQueryHandler(self.process_menu_selection)],
                PROCESS_IMAGE: [MessageHandler(filters.PHOTO, self.handle_photo)],
                CONFIRM_CLIENT: [CallbackQueryHandler(self.confirm_client_handler)],
                CONFIRM_PRODUCTS: [CallbackQueryHandler(self.confirm_products_handler)],
                MANUAL_PRICE: [
                    MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_manual_price)
                ],
                EDIT_PRODUCT_NAME: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.handle_edit_product_name
                    )
                ],
                EDIT_PRODUCT_QUANTITY: [
                    MessageHandler(
                        filters.TEXT & ~filters.COMMAND, self.handle_edit_product_quantity
                    )
                ],
                CONFIRM_INVOICE: [CallbackQueryHandler(self.confirm_invoice_handler)],
                CONFIRM_SHEETS: [CallbackQueryHandler(self.confirm_sheets_handler)],
                CONFIRM_SIIGO: [CallbackQueryHandler(self.confirm_siigo_handler)],
                CONFIRM_DIAN: [CallbackQueryHandler(self.confirm_dian_handler)],
            },
            fallbacks=[CommandHandler("cancel", self.cancel_command)],
        )

        # Agregar manejadores a la aplicación
        application.add_handler(conv_handler)
        application.add_handler(CommandHandler("facturar", self.facturar_command))
        application.add_handler(CommandHandler("historial", self.historial_command))
        application.add_handler(CommandHandler("estado", self.check_status_command))
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.handle_text))

        return application

    # -------------------------------------------------------------------------
    # COMANDOS
    # -------------------------------------------------------------------------

    async def start_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Maneja el comando /start"""
        chat_id = update.effective_chat.id
        user = update.effective_user

        welcome_msg = (
            f"¡Hola {user.first_name}! Bienvenido al Sistema de Facturación.\n\n"
            "Con este bot puedes:\n"
            "• Procesar pedidos a partir de imágenes\n"
            "• Generar facturas PDF\n"
            "• Crear facturas electrónicas en Siigo\n"
            "• Consultar el historial de facturas\n\n"
            "Selecciona una opción:"
        )

        # Crear botones para el menú principal
        keyboard = [
            [InlineKeyboardButton("📷 Procesar pedido desde imagen", callback_data="process_image")],
            [InlineKeyboardButton("📋 Historial de facturas", callback_data="history")],
            [InlineKeyboardButton("🔍 Comprobar estado del sistema", callback_data="check_status")],
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)

        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)
        return MENU

    async def facturar_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Maneja el comando /facturar"""
        await update.message.reply_text(
            "Para procesar una factura, envíame una foto del pedido. La procesaré automáticamente."
        )
        return PROCESS_IMAGE

    async def historial_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Maneja el comando /historial mostrando las últimas facturas"""
        try:
            # Obtener las últimas facturas usando el servicio de facturación
            invoices = self.invoice_service.db_manager.get_invoices(5)

            if not invoices:
                await update.message.reply_text("No hay facturas registradas.")
                return

            message = "📋 <b>ÚLTIMAS FACTURAS</b>\n\n"
            for factura in invoices:
                message += (
                    f"<b>ID:</b> {factura['id']}\n"
                    f"<b>Cliente:</b> {factura['cliente_nombre']}\n"
                    f"<b>Fecha:</b> {factura['fecha']}\n"
                    f"<b>Total:</b> ${float(factura['total']):.2f}\n"
                    f"<b>Estado:</b> {factura['estado']}\n"
                    f"{'—' * 20}\n"
                )

            await update.message.reply_text(message, parse_mode="HTML")
        except Exception as e:
            logger.error(f"Error al obtener el historial: {e}")
            await update.message.reply_text(f"Error al obtener el historial: {str(e)}")

    async def check_status_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Maneja el comando /estado verificando la conexión con los servicios"""
        message = "🔍 <b>ESTADO DEL SISTEMA</b>\n\n"

        # Verificar Google Sheets
        sheets_client = self.invoice_service.sheets_client
        if sheets_client.is_available():
            try:
                worksheets = sheets_client.spreadsheet.worksheets()
                message += "✅ <b>Google Sheets:</b> Conectado\n"
                message += f"   Hojas: {', '.join([ws.title for ws in worksheets])}\n\n"
            except Exception as e:
                message += f"❌ <b>Google Sheets:</b> Error - {str(e)}\n\n"
        else:
            message += "❌ <b>Google Sheets:</b> No disponible\n\n"

        # Verificar Siigo API
        siigo_client = self.invoice_service.siigo_client
        if siigo_client and siigo_client.is_available():
            message += "✅ <b>Siigo API:</b> Conectado\n\n"
        else:
            message += "❌ <b>Siigo API:</b> No disponible\n\n"

        # Verificar Claude API
        claude_client = self.image_service.claude_client
        if claude_client.is_available():
            message += "✅ <b>Claude API:</b> Configurado\n\n"
        else:
            message += "❌ <b>Claude API:</b> No disponible\n\n"

        # Verificar Google Cloud Storage
        if self.storage_client:
            message += "✅ <b>Google Cloud Storage:</b> Conectado\n"
            message += f"   Bucket: {GCS_BUCKET_NAME}\n"
        else:
            message += "❌ <b>Google Cloud Storage:</b> No disponible\n"

        await update.message.reply_text(message, parse_mode="HTML")

    async def cancel_command(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Maneja el comando /cancel cancelando la operación actual"""
        await update.message.reply_text("Operación cancelada. Puedes iniciar de nuevo con /start.")
        # Limpiar datos temporales
        if update.effective_chat.id in self.user_data:
            del self.user_data[update.effective_chat.id]
        return ConversationHandler.END

    # -------------------------------------------------------------------------
    # MENÚ PRINCIPAL
    # -------------------------------------------------------------------------

    async def process_menu_selection(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Procesa la selección del menú principal"""
        query = update.callback_query
        await query.answer()

        if query.data == "process_image":
            await query.edit_message_text(
                "📷 Envíame una foto del pedido para procesar. Asegúrate de que sea clara y legible."
            )
            return PROCESS_IMAGE
        elif query.data == "history":
            await self.historial_command(update, context)
            # Mostrar menú principal nuevamente
            keyboard = [
                [InlineKeyboardButton("📷 Procesar pedido desde imagen", callback_data="process_image")],
                [InlineKeyboardButton("📋 Historial de facturas", callback_data="history")],
                [InlineKeyboardButton("🔍 Comprobar estado del sistema", callback_data="check_status")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("¿Qué más deseas hacer?", reply_markup=reply_markup)
            return MENU
        elif query.data == "check_status":
            await self.check_status_command(update, context)
            # Mostrar menú principal nuevamente
            keyboard = [
                [InlineKeyboardButton("📷 Procesar pedido desde imagen", callback_data="process_image")],
                [InlineKeyboardButton("📋 Historial de facturas", callback_data="history")],
                [InlineKeyboardButton("🔍 Comprobar estado del sistema", callback_data="check_status")],
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await query.message.reply_text("¿Qué más deseas hacer?", reply_markup=reply_markup)
            return MENU

        return MENU

    async def handle_text(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        """Maneja mensajes de texto genéricos"""
        await update.message.reply_text(
            "Puedes usar /start para iniciar, /facturar para procesar una factura, "
            "/historial para ver facturas anteriores o /estado para verificar la conexión."
        )

    # -------------------------------------------------------------------------
    # PROCESAMIENTO DE IMAGEN
    # -------------------------------------------------------------------------

    async def handle_photo(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
        """Maneja la recepción de una foto para procesar un pedido"""
        chat_id = update.effective_chat.id

        # Inicializar datos del usuario si no existen
        if chat_id not in self.user_data:
            self.user_data[chat_id] = {}

        # Informar al usuario que estamos procesando la imagen
        status_message = await update.message.reply_text("⏳ Descargando y procesando la imagen...")

        # Obtener la foto con mejor calidad
        photo_file = await update.message.photo[-1].get_file()

        # Crear directorio temporal si no existe
        temp_dir = tempfile.mkdtemp()
        local_file_path = os.path.join(
            temp_dir, f"pedido_{chat_id}_{int(datetime.now().timestamp())}.jpg"
        )

        # Descargar la imagen
        await photo_file.download_to_drive(local_file_path)
        await status_message.edit_text("✅ Imagen recibida. Subiendo a Google Cloud Storage...")

        # Subir imagen a Google Cloud Storage
        try:
            if self.storage_client and self.bucket:
                # Crear blob y subir archivo
                blob_name = f"pedidos/{datetime.now().strftime('%Y%m%d')}_{os.path.basename(local_file_path)}"
                blob = self.bucket.blob(blob_name)
                blob.upload_from_filename(local_file_path)

                # Guardar URL de la imagen
                gcs_url = f"gs://{GCS_BUCKET_NAME}/{blob_name}"
                self.user_data[chat_id]["image_path"] = local_file_path
                self.user_data[chat_id]["gcs_url"] = gcs_url

                await status_message.edit_text(
                    "✅ Imagen subida a Cloud Storage. Procesando contenido..."
                )
            else:
                # Si no hay Google Cloud Storage, usar archivo local
                self.user_data[chat_id]["image_path"] = local_file_path
                await status_message.edit_text(
                    "⚠️ Cloud Storage no disponible. Usando almacenamiento local. Procesando contenido..."
                )
        except Exception as e:
            logger.error(f"Error al subir a Cloud Storage: {e}")
            await status_message.edit_text(
                "⚠️ Error al subir a Cloud Storage. Usando almacenamiento local. Procesando contenido..."
            )
            self.user_data[chat_id]["image_path"] = local_file_path

        # Procesar la imagen para extraer cliente y productos
        try:
            await status_message.edit_text("🔍 Analizando la imagen con IA...")

            client_name, products_data = self.image_service.process_order_image(local_file_path)

            # Filtrar productos que coincidan con el nombre del cliente
            if client_name:
                filtered_products_name = []
                for product in products_data:
                    if product["nombre"].lower() != client_name.lower():
                        filtered_products_name.append(product)
                    else:
                        logger.warning(
                            f"Ignorando producto '{product['nombre']}' porque coincide con el nombre del cliente"
                        )
                products_data = filtered_products_name

            # -----------------------------------------------------------------
            # NUEVO FILTRO: eliminar productos con cantidad 0
            # -----------------------------------------------------------------
            filtered_products_qty = []
            for product in products_data:
                if product.get("cantidad", 0) > 0:
                    filtered_products_qty.append(product)
                else:
                    logger.info(
                        f"Ignorando producto '{product['nombre']}' porque tiene cantidad 0"
                    )
            products_data = filtered_products_qty
            # -----------------------------------------------------------------

            if not products_data:
                await status_message.edit_text("❌ No se pudieron detectar productos en la imagen.")
                return ConversationHandler.END

            # Guardar datos detectados
            self.user_data[chat_id]["client_name"] = client_name
            self.user_data[chat_id]["products_data"] = products_data

            # Buscar cliente
            client_data = None
            if client_name:
                client_data = self.client_service.find_client_by_name(client_name)

            # Mostrar resultado y solicitar confirmación
            if client_data:
                await status_message.edit_text(
                    f"✅ Cliente detectado: <b>{client_name}</b>\n\n"
                    f"Posible coincidencia: <b>{client_data['nombre_cliente']}</b>\n\n"
                    "¿Es correcto?",
                    parse_mode="HTML",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "✅ Sí, es correcto", callback_data="client_correct"
                                )
                            ],
                            [
                                InlineKeyboardButton(
                                    "❌ No, elegir otro", callback_data="client_select"
                                )
                            ],
                        ]
                    ),
                )
                self.user_data[chat_id]["client_data"] = client_data
            else:
                # No se encontró cliente o no se detectó en la imagen
                await status_message.edit_text(
                    f"{'⚠️ Cliente detectado pero no encontrado en el sistema' if client_name else '⚠️ No se detectó cliente en la imagen'}\n\n"
                    "Por favor, selecciona un cliente:",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "📋 Seleccionar cliente", callback_data="client_select"
                                )
                            ]
                        ]
                    ),
                )

            return CONFIRM_CLIENT

        except Exception as e:
            logger.error(f"Error al procesar imagen: {e}")
            await status_message.edit_text(f"❌ Error al procesar la imagen: {str(e)}")
            return ConversationHandler.END

    # -------------------------------------------------------------------------
    # CONFIRMACIÓN DE CLIENTE
    # -------------------------------------------------------------------------

    async def confirm_client_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la confirmación del cliente"""
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id

        if query.data == "client_correct":
            # Cliente confirmado, continuar con productos
            await self.show_products_confirmation(update, context)
            return CONFIRM_PRODUCTS
        elif query.data == "client_select":
            # Obtener lista de clientes y mostrarla para selección
            clients = self.client_service.get_all_clients()

            if not clients:
                await query.edit_message_text("❌ No hay clientes registrados en el sistema.")
                return ConversationHandler.END

            # Crear teclado con clientes disponibles
            keyboard = []
            for i, client in enumerate(clients[:20]):  # Limitar a 20 clientes
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{client['nombre_cliente']} - {client['identificacion']}",
                            callback_data=f"sel_client_{i}",
                        )
                    ]
                )

            self.user_data[chat_id]["available_clients"] = clients

            await query.edit_message_text(
                "Selecciona un cliente de la lista:", reply_markup=InlineKeyboardMarkup(keyboard)
            )
            return CONFIRM_CLIENT
        elif query.data.startswith("sel_client_"):
            # Procesar selección de cliente
            index = int(query.data.split("_")[2])
            client_data = self.user_data[chat_id]["available_clients"][index]
            self.user_data[chat_id]["client_data"] = client_data

            await query.edit_message_text(
                f"✅ Cliente seleccionado: <b>{client_data['nombre_cliente']}</b>\n\n"
                "Procesando productos...",
                parse_mode="HTML",
            )

            await self.show_products_confirmation(update, context)
            return CONFIRM_PRODUCTS

        return CONFIRM_CLIENT

    # -------------------------------------------------------------------------
    # CONFIRMACIÓN DE PRODUCTOS
    # -------------------------------------------------------------------------

    async def show_products_confirmation(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Muestra los productos detectados y solicita confirmación"""
        query = update.callback_query
        chat_id = update.effective_chat.id
        products_data = self.user_data[chat_id]["products_data"]
        client_name = self.user_data[chat_id].get("client_name", "")

        # Procesar productos detectados
        processed_products: List[Product] = []
        pending_products: List[Dict[str, Any]] = []
        product_catalog = self.product_service.get_all_products()

        message = "📦 <b>Productos detectados:</b>\n\n"

        for i, product_info in enumerate(products_data):
            product_name = product_info["nombre"]
            product_qty = product_info["cantidad"]

            # Verificar si el producto es igual al nombre del cliente (filtrar)
            if product_name.lower() == client_name.lower():
                logger.warning(
                    f"Ignorando producto '{product_name}' porque coincide con el nombre del cliente"
                )
                continue

            message += f"{i+1}. {product_name} - Cantidad: {product_qty}\n"

            # Buscar coincidencia en el catálogo
            product_details = self.product_service.find_product_by_name(product_name)

            if product_details:
                # Si hay coincidencia buena, usar directamente
                similarity = calculate_similarity(product_name, product_details["nombre_producto"])

                # -----------------------------------------------------------------
                # Ajuste de umbral de similitud a 0.5
                # -----------------------------------------------------------------
                if similarity >= 0.5:
                    processed_products.append(
                        Product(
                            nombre=product_details["nombre_producto"],
                            cantidad=product_qty,
                            precio=clean_price(product_details["precio_unitario"]),
                            producto_id=product_details["producto_id"],
                            impuesto_id=product_details.get("impuesto_id", ""),
                        )
                    )
                    message += f"   ✅ Coincide con: {product_details['nombre_producto']}\n"
                    message += (
                        f"   💰 Precio: ${clean_price(product_details['precio_unitario']):.2f}\n\n"
                    )
                else:
                    # Agregar a productos pendientes
                    pending_products.append(
                        {
                            "index": i,
                            "detected_name": product_name,
                            "cantidad": product_qty,
                            "possible_match": product_details,
                            "similarity": similarity,
                        }
                    )
                    message += (
                        f"   ⚠️ Posible coincidencia: {product_details['nombre_producto']}\n\n"
                    )
            else:
                # No hay coincidencia, necesita precio manual
                pending_products.append(
                    {
                        "index": i,
                        "detected_name": product_name,
                        "cantidad": product_qty,
                        "possible_match": None,
                        "similarity": 0,
                    }
                )
                message += "   ❓ No encontrado en catálogo\n\n"

        # Guardar productos procesados y pendientes
        self.user_data[chat_id]["processed_products"] = processed_products
        self.user_data[chat_id]["pending_products"] = pending_products

        if pending_products:
            # Hay productos pendientes de confirmar
            message += "\n¿Los productos identificados son correctos?"

            # Añadir botones para editar/eliminar además de confirmar
            buttons = [
                [InlineKeyboardButton("✅ Confirmar productos", callback_data="confirm_products")],
                [InlineKeyboardButton("✏️ Editar un producto", callback_data="edit_products")],
                [InlineKeyboardButton("🗑️ Eliminar un producto", callback_data="delete_products")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_products")],
            ]

            await query.edit_message_text(
                message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
            )
        else:
            # Todos los productos fueron procesados automáticamente
            message += "\nTodos los productos han sido identificados automáticamente."

            # Añadir botones para editar/eliminar además de continuar
            buttons = [
                [InlineKeyboardButton("✅ Continuar", callback_data="products_complete")],
                [InlineKeyboardButton("✏️ Editar productos", callback_data="edit_products")],
                [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_products")],
            ]

            await query.edit_message_text(
                message, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(buttons)
            )

    async def confirm_products_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la confirmación de productos"""
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id

        if query.data == "cancel_products":
            await query.edit_message_text("❌ Operación cancelada.")
            return ConversationHandler.END

        elif query.data == "confirm_products":
            # Procesar productos pendientes
            pending_products = self.user_data[chat_id].get("pending_products", [])

            if pending_products:
                # Obtener el primer producto pendiente
                product = pending_products[0]
                self.user_data[chat_id]["current_product"] = product

                if product["possible_match"]:
                    # Hay coincidencia, pedir confirmación
                    await query.edit_message_text(
                        f"📦 Producto: <b>{product['detected_name']}</b>\n"
                        f"Cantidad: {product['cantidad']}\n\n"
                        f"Posible coincidencia: <b>{product['possible_match']['nombre_producto']}</b>\n"
                        f"Precio: ${clean_price(product['possible_match']['precio_unitario']):.2f}\n\n"
                        "¿Es correcto?",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Sí, usar este producto",
                                        callback_data="use_matched_product",
                                    )
                                ],
                                [
                                    InlineKeyboardButton(
                                        "❌ No, ingresar precio manualmente",
                                        callback_data="manual_price",
                                    )
                                ],
                            ]
                        ),
                    )
                else:
                    # No hay coincidencia, pedir precio manual
                    await query.edit_message_text(
                        f"📦 Producto: <b>{product['detected_name']}</b>\n"
                        f"Cantidad: {product['cantidad']}\n\n"
                        "Este producto no fue encontrado en el catálogo.\n"
                        "Por favor, ingresa el precio unitario:",
                        parse_mode="HTML",
                    )
                    return MANUAL_PRICE

                return CONFIRM_PRODUCTS

            else:
                # No hay productos pendientes, mostrar factura
                await self.generate_invoice_preview(update, context)
                return CONFIRM_INVOICE

        elif query.data == "edit_products":
            # Mostrar lista de productos para editar
            products_data = self.user_data[chat_id]["products_data"]
            keyboard = []

            for i, product in enumerate(products_data):
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"{product['nombre']} (Cant: {product['cantidad']})",
                            callback_data=f"edit_product_{i}",
                        )
                    ]
                )

            keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="back_to_products")])

            await query.edit_message_text(
                "Selecciona el producto que deseas editar:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return CONFIRM_PRODUCTS

        elif query.data == "delete_products":
            # Mostrar lista de productos para eliminar
            products_data = self.user_data[chat_id]["products_data"]
            keyboard = []

            for i, product in enumerate(products_data):
                keyboard.append(
                    [
                        InlineKeyboardButton(
                            f"❌ {product['nombre']} (Cant: {product['cantidad']})",
                            callback_data=f"delete_product_{i}",
                        )
                    ]
                )

            keyboard.append([InlineKeyboardButton("⬅️ Volver", callback_data="back_to_products")])

            await query.edit_message_text(
                "Selecciona el producto que deseas eliminar:",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return CONFIRM_PRODUCTS

        elif query.data.startswith("edit_product_"):
            # Manejar edición de un producto específico
            index = int(query.data.split("_")[2])
            product = self.user_data[chat_id]["products_data"][index]

            # Guardar el índice para usarlo después
            self.user_data[chat_id]["editing_product_index"] = index

            # Opciones de edición
            keyboard = [
                [InlineKeyboardButton("✏️ Editar nombre", callback_data=f"edit_name_{index}")],
                [InlineKeyboardButton("🔢 Editar cantidad", callback_data=f"edit_quantity_{index}")],
                [InlineKeyboardButton("⬅️ Volver", callback_data="back_to_products")],
            ]

            await query.edit_message_text(
                f"Producto: <b>{product['nombre']}</b>\n"
                f"Cantidad actual: {product['cantidad']}\n\n"
                "¿Qué deseas editar?",
                parse_mode="HTML",
                reply_markup=InlineKeyboardMarkup(keyboard),
            )
            return CONFIRM_PRODUCTS

        elif query.data.startswith("delete_product_"):
            # Eliminar un producto
            index = int(query.data.split("_")[2])
            product_name = self.user_data[chat_id]["products_data"][index]["nombre"]

            # Eliminar el producto
            del self.user_data[chat_id]["products_data"][index]

            await query.edit_message_text(
                f"✅ Producto <b>{product_name}</b> eliminado correctamente.", parse_mode="HTML"
            )

            # Volver a mostrar la lista actualizada
            await self.show_products_confirmation(update, context)
            return CONFIRM_PRODUCTS

        elif query.data == "back_to_products":
            # Volver a la pantalla de confirmación de productos
            await self.show_products_confirmation(update, context)
            return CONFIRM_PRODUCTS

        elif query.data.startswith("edit_name_"):
            # Pedir nuevo nombre para el producto
            index = int(query.data.split("_")[2])
            product = self.user_data[chat_id]["products_data"][index]
            self.user_data[chat_id]["editing_product_index"] = index

            await query.edit_message_text(
                f"Producto actual: <b>{product['nombre']}</b>\n\n"
                "Por favor, ingresa el nuevo nombre del producto:",
                parse_mode="HTML",
            )
            return EDIT_PRODUCT_NAME

        elif query.data.startswith("edit_quantity_"):
            # Pedir nueva cantidad para el producto
            index = int(query.data.split("_")[2])
            product = self.user_data[chat_id]["products_data"][index]
            self.user_data[chat_id]["editing_product_index"] = index

            await query.edit_message_text(
                f"Producto: <b>{product['nombre']}</b>\n"
                f"Cantidad actual: {product['cantidad']}\n\n"
                "Por favor, ingresa la nueva cantidad:",
                parse_mode="HTML",
            )
            return EDIT_PRODUCT_QUANTITY

        elif query.data == "use_matched_product":
            # Usar producto coincidente
            product = self.user_data[chat_id]["current_product"]
            matched_product = product["possible_match"]

            processed_products = self.user_data[chat_id].get("processed_products", [])
            processed_products.append(
                Product(
                    nombre=matched_product["nombre_producto"],
                    cantidad=product["cantidad"],
                    precio=clean_price(matched_product["precio_unitario"]),
                    producto_id=matched_product["producto_id"],
                    impuesto_id=matched_product.get("impuesto_id", ""),
                )
            )

            self.user_data[chat_id]["processed_products"] = processed_products

            # Eliminar producto de pendientes
            pending_products = self.user_data[chat_id]["pending_products"]
            pending_products.pop(0)
            self.user_data[chat_id]["pending_products"] = pending_products

            # -----------------------------------------------------------------
            # AJUSTE PARA EVITAR "Message is not modified"
            # -----------------------------------------------------------------
            if pending_products:
                # Hay más productos pendientes
                # Obtenemos el siguiente producto pendiente sin necesidad de editar
                product = pending_products[0]
                self.user_data[chat_id]["current_product"] = product

                if product["possible_match"]:
                    # Hay coincidencia, mostrar para confirmar
                    await query.edit_message_text(
                        f"✅ Producto anterior confirmado.\n\n"
                        f"📦 Siguiente producto: <b>{product['detected_name']}</b>\n"
                        f"Cantidad: {product['cantidad']}\n\n"
                        f"Posible coincidencia: <b>{product['possible_match']['nombre_producto']}</b>\n"
                        f"Precio: ${clean_price(product['possible_match']['precio_unitario']):.2f}\n\n"
                        "¿Es correcto?",
                        parse_mode="HTML",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Sí, usar este producto",
                                        callback_data="use_matched_product",
                                    )
                                ],
                                [
                                    InlineKeyboardButton(
                                        "❌ No, ingresar precio manualmente",
                                        callback_data="manual_price",
                                    )
                                ],
                            ]
                        ),
                    )
                else:
                    # No hay coincidencia, pedir precio manual
                    await query.edit_message_text(
                        f"✅ Producto anterior confirmado.\n\n"
                        f"📦 Siguiente producto: <b>{product['detected_name']}</b>\n"
                        f"Cantidad: {product['cantidad']}\n\n"
                        "Este producto no fue encontrado en el catálogo.\n"
                        "Por favor, ingresa el precio unitario:",
                        parse_mode="HTML",
                    )
                    return MANUAL_PRICE

                return CONFIRM_PRODUCTS
            # -----------------------------------------------------------------

            else:
                # No hay más productos pendientes, mostrar factura
                await self.generate_invoice_preview(update, context)
                return CONFIRM_INVOICE

        elif query.data == "manual_price":
            # Ingresar precio manualmente
            product = self.user_data[chat_id]["current_product"]

            await query.edit_message_text(
                f"📦 Producto: <b>{product['detected_name']}</b>\n"
                f"Cantidad: {product['cantidad']}\n\n"
                "Por favor, ingresa el precio unitario:",
                parse_mode="HTML",
            )
            return MANUAL_PRICE

        elif query.data == "products_complete":
            # Todos los productos están procesados, generar factura
            await self.generate_invoice_preview(update, context)
            return CONFIRM_INVOICE

        return CONFIRM_PRODUCTS

    # -------------------------------------------------------------------------
    # EDICIÓN DE PRODUCTOS (NOMBRE / CANTIDAD)
    # -------------------------------------------------------------------------

    async def handle_edit_product_name(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la edición del nombre de un producto"""
        chat_id = update.effective_chat.id
        new_name = update.message.text.strip()

        if not new_name:
            await update.message.reply_text(
                "❌ El nombre no puede estar vacío. Por favor, ingresa un nombre válido."
            )
            return EDIT_PRODUCT_NAME

        # Actualizar el nombre del producto
        index = self.user_data[chat_id]["editing_product_index"]
        self.user_data[chat_id]["products_data"][index]["nombre"] = new_name

        # Buscar coincidencia en el catálogo con el nuevo nombre
        product_details = self.product_service.find_product_by_name(new_name)

        if product_details:
            # Hay coincidencia, mostrar información
            await update.message.reply_text(
                f"✅ Nombre actualizado a: <b>{new_name}</b>\n\n"
                f"Coincidencia encontrada en el catálogo: <b>{product_details['nombre_producto']}</b>\n"
                f"Precio: ${clean_price(product_details['precio_unitario']):.2f}",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text(
                f"✅ Nombre actualizado a: <b>{new_name}</b>\n\nNo se encontró coincidencia en el catálogo.",
                parse_mode="HTML",
            )

        # Volver a mostrar la lista de productos
        keyboard = [[InlineKeyboardButton("Continuar", callback_data="back_to_products")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "¿Deseas continuar con la lista de productos?", reply_markup=reply_markup
        )

        return CONFIRM_PRODUCTS

    async def handle_edit_product_quantity(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la edición de la cantidad de un producto"""
        chat_id = update.effective_chat.id
        quantity_text = update.message.text.strip()

        # Verificar si la cantidad es válida
        try:
            quantity = float(quantity_text)
            if quantity <= 0:
                await update.message.reply_text("❌ La cantidad debe ser mayor que cero.")
                return EDIT_PRODUCT_QUANTITY

            # Actualizar la cantidad del producto
            index = self.user_data[chat_id]["editing_product_index"]
            product = self.user_data[chat_id]["products_data"][index]
            product["cantidad"] = quantity

            await update.message.reply_text(
                f"✅ Cantidad actualizada a: {quantity} para el producto <b>{product['nombre']}</b>",
                parse_mode="HTML",
            )

            # Volver a mostrar la lista de productos
            keyboard = [[InlineKeyboardButton("Continuar", callback_data="back_to_products")]]
            reply_markup = InlineKeyboardMarkup(keyboard)
            await update.message.reply_text(
                "¿Deseas continuar con la lista de productos?", reply_markup=reply_markup
            )

            return CONFIRM_PRODUCTS

        except ValueError:
            await update.message.reply_text("❌ Por favor, ingresa un número válido para la cantidad.")
            return EDIT_PRODUCT_QUANTITY

    # -------------------------------------------------------------------------
    # PRECIO MANUAL
    # -------------------------------------------------------------------------

    async def handle_manual_price(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la entrada del precio manual para un producto"""
        chat_id = update.effective_chat.id
        price_text = update.message.text.strip()

        # Verificar si el precio es válido
        try:
            price = float(price_text.replace("$", "").replace(",", ""))

            # Obtener el producto actual
            product = self.user_data[chat_id]["current_product"]

            # Crear objeto Product con precio manual
            processed_products = self.user_data[chat_id].get("processed_products", [])
            processed_products.append(
                Product(
                    nombre=product["detected_name"],
                    cantidad=product["cantidad"],
                    precio=price,
                    producto_id="MANUAL",
                    impuesto_id="",
                )
            )

            self.user_data[chat_id]["processed_products"] = processed_products

            # Eliminar producto de pendientes
            pending_products = self.user_data[chat_id]["pending_products"]
            pending_products.pop(0)
            self.user_data[chat_id]["pending_products"] = pending_products

            # Enviar confirmación
            await update.message.reply_text(f"✅ Precio guardado: ${price:.2f}")

            if pending_products:
                # Hay más productos pendientes, continuar con el siguiente
                keyboard = [[InlineKeyboardButton("Continuar", callback_data="confirm_products")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    "Procesando siguiente producto...", reply_markup=reply_markup
                )
                return CONFIRM_PRODUCTS
            else:
                # No hay más productos pendientes, mostrar factura
                keyboard = [[InlineKeyboardButton("Generar Factura", callback_data="products_complete")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    "✅ Todos los productos procesados. ¿Generar factura?", reply_markup=reply_markup
                )
                return CONFIRM_PRODUCTS
        except ValueError:
            await update.message.reply_text(
                "❌ Por favor, ingresa un número válido para el precio (ej. 15000 o 15000.50)"
            )
            return MANUAL_PRICE

    # -------------------------------------------------------------------------
    # GENERACIÓN DE FACTURA
    # -------------------------------------------------------------------------

    async def generate_invoice_preview(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> None:
        """Genera una vista previa de la factura"""
        query = update.callback_query
        chat_id = update.effective_chat.id

        client_data = self.user_data[chat_id]["client_data"]
        products = self.user_data[chat_id]["processed_products"]

        # Generar factura
        invoice = self.invoice_service.generate_invoice(client_data, products)
        self.user_data[chat_id]["invoice"] = invoice

        if not invoice:
            await query.edit_message_text("❌ Error al generar la factura.")
            return

        # Mostrar vista previa de la factura
        message = "📝 <b>VISTA PREVIA DE FACTURA</b>\n\n"
        message += f"<b>Factura #:</b> {invoice.factura_id}\n"
        message += f"<b>Fecha:</b> {invoice.fecha_emision}\n"
        message += f"<b>Cliente:</b> {invoice.nombre_cliente}\n"
        message += f"<b>Identificación:</b> {invoice.identificacion}\n\n"
        message += "<b>PRODUCTOS:</b>\n"

        total = 0
        for product in products:
            subtotal = product.precio * product.cantidad
            total += subtotal
            message += f"• {product.nombre} x {product.cantidad} = ${subtotal:.2f}\n"

        message += f"\n<b>TOTAL: ${total:.2f}</b>"

        await query.edit_message_text(
            message,
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                [
                    [
                        InlineKeyboardButton(
                            "✅ Confirmar y generar PDF", callback_data="confirm_invoice"
                        )
                    ],
                    [InlineKeyboardButton("⬅️ Volver a productos", callback_data="back_to_products")],
                    [InlineKeyboardButton("❌ Cancelar", callback_data="cancel_invoice")],
                ]
            ),
        )

    # -------------------------------------------------------------------------
    # CONFIRMACIÓN DE FACTURA
    # -------------------------------------------------------------------------

    async def confirm_invoice_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la confirmación de la factura"""
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id

        if query.data == "cancel_invoice":
            await query.edit_message_text("❌ Generación de factura cancelada.")
            return ConversationHandler.END

        elif query.data == "back_to_products":
            # Volver a la pantalla de confirmación de productos
            await self.show_products_confirmation(update, context)
            return CONFIRM_PRODUCTS

        elif query.data == "confirm_invoice":
            # Generar PDF
            await query.edit_message_text("⏳ Generando PDF de la factura...")

            invoice = self.user_data[chat_id]["invoice"]
            products = self.user_data[chat_id]["processed_products"]

            # Guardar factura en base de datos
            self.invoice_service.save_invoice(invoice, products, False)

            # Generar PDF
            pdf_path = self.invoice_service.generate_invoice_pdf(invoice, products)

            if not pdf_path:
                await query.edit_message_text("❌ Error al generar el PDF de la factura.")
                return ConversationHandler.END

            # Guardar en el chat la ruta del PDF
            self.user_data[chat_id]["pdf_path"] = pdf_path

            # Enviar PDF al usuario
            await query.edit_message_text("✅ PDF generado. Enviando documento...")

            try:
                await context.bot.send_document(
                    chat_id=chat_id,
                    document=open(pdf_path, "rb"),
                    filename=os.path.basename(pdf_path),
                    caption=f"Factura #{invoice.factura_id} generada correctamente.",
                )

                # Preguntar si guardar en Google Sheets
                await query.message.reply_text(
                    "¿Deseas guardar esta factura en el historial de Google Sheets?",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "✅ Sí, guardar en Sheets", callback_data="save_sheets"
                                )
                            ],
                            [InlineKeyboardButton("❌ No guardar", callback_data="skip_sheets")],
                        ]
                    ),
                )

                return CONFIRM_SHEETS

            except Exception as e:
                logger.error(f"Error al enviar PDF: {e}")
                await query.edit_message_text(
                    f"❌ Error al enviar el PDF: {str(e)}\n" f"El archivo se guardó en: {pdf_path}"
                )
                return ConversationHandler.END

    # -------------------------------------------------------------------------
    # GOOGLE SHEETS
    # -------------------------------------------------------------------------

    async def confirm_sheets_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la confirmación para guardar en Google Sheets"""
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id

        if query.data == "save_sheets":
            # Guardar en Google Sheets
            await query.edit_message_text("⏳ Guardando factura en Google Sheets...")

            invoice = self.user_data[chat_id]["invoice"]

            try:
                saved = self.invoice_service.sheets_client.save_invoice_to_sheet(invoice.to_dict())

                if saved:
                    msg = "✅ Factura guardada correctamente en Google Sheets."
                else:
                    msg = "❌ Error al guardar la factura en Google Sheets."

                # Verificar si Siigo está disponible
                if self.invoice_service.is_siigo_available():
                    await query.edit_message_text(
                        f"{msg}\n\n¿Deseas generar factura electrónica en Siigo?",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Sí, crear factura en Siigo", callback_data="create_siigo"
                                    )
                                ],
                                [InlineKeyboardButton("❌ No, finalizar", callback_data="skip_siigo")],
                            ]
                        ),
                    )
                    return CONFIRM_SIIGO
                else:
                    await query.edit_message_text(
                        f"{msg}\n\n✅ Proceso completado. Puedes iniciar una nueva factura con /start."
                    )
                    return ConversationHandler.END

            except Exception as e:
                logger.error(f"Error al guardar en Sheets: {e}")
                await query.edit_message_text(f"❌ Error al guardar en Google Sheets: {str(e)}")

                # Verificar si Siigo está disponible
                if self.invoice_service.is_siigo_available():
                    await query.message.reply_text(
                        "¿Deseas generar factura electrónica en Siigo?",
                        reply_markup=InlineKeyboardMarkup(
                            [
                                [
                                    InlineKeyboardButton(
                                        "✅ Sí, crear factura en Siigo", callback_data="create_siigo"
                                    )
                                ],
                                [InlineKeyboardButton("❌ No, finalizar", callback_data="skip_siigo")],
                            ]
                        ),
                    )
                    return CONFIRM_SIIGO
                else:
                    return ConversationHandler.END

        elif query.data == "skip_sheets":
            # No guardar en Sheets, verificar si Siigo está disponible
            if self.invoice_service.is_siigo_available():
                await query.edit_message_text(
                    "¿Deseas generar factura electrónica en Siigo?",
                    reply_markup=InlineKeyboardMarkup(
                        [
                            [
                                InlineKeyboardButton(
                                    "✅ Sí, crear factura en Siigo", callback_data="create_siigo"
                                )
                            ],
                            [InlineKeyboardButton("❌ No, finalizar", callback_data="skip_siigo")],
                        ]
                    ),
                )
                return CONFIRM_SIIGO
            else:
                await query.edit_message_text(
                    "✅ Proceso completado. Puedes iniciar una nueva factura con /start."
                )
                return ConversationHandler.END

    # -------------------------------------------------------------------------
    # SIIGO
    # -------------------------------------------------------------------------

    async def confirm_siigo_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la confirmación para crear factura en Siigo"""
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id

        if query.data == "create_siigo":
            # Preguntar si enviar a la DIAN
            await query.edit_message_text(
                "¿Deseas enviar la factura directamente a la DIAN?",
                reply_markup=InlineKeyboardMarkup(
                    [
                        [
                            InlineKeyboardButton("✅ Sí, enviar a DIAN", callback_data="send_dian")
                        ],
                        [
                            InlineKeyboardButton(
                                "❌ No enviar a DIAN", callback_data="skip_dian"
                            )
                        ],
                    ]
                ),
            )
            return CONFIRM_DIAN

        elif query.data == "skip_siigo":
            await query.edit_message_text(
                "✅ Proceso completado. Puedes iniciar una nueva factura con /start."
            )
            return ConversationHandler.END

    # -------------------------------------------------------------------------
    # DIAN
    # -------------------------------------------------------------------------

    async def confirm_dian_handler(
        self, update: Update, context: ContextTypes.DEFAULT_TYPE
    ) -> int:
        """Maneja la confirmación para enviar a la DIAN"""
        query = update.callback_query
        await query.answer()
        chat_id = update.effective_chat.id

        invoice = self.user_data[chat_id]["invoice"]
        products = self.user_data[chat_id]["processed_products"]
        client_data = self.user_data[chat_id]["client_data"]

        send_to_dian = query.data == "send_dian"

        await query.edit_message_text(
            f"⏳ Generando factura electrónica en Siigo{' y enviando a DIAN' if send_to_dian else ' (sin enviar a DIAN)'}..."
        )

        try:
            siigo_id = self.invoice_service.generate_siigo_invoice(
                invoice, products, client_data, send_to_dian
            )

            if siigo_id:
                await query.edit_message_text(
                    f"✅ Factura electrónica generada con éxito en Siigo con ID: {siigo_id}\n\n"
                    "Proceso completado. Puedes iniciar una nueva factura con /start."
                )
            else:
                await query.edit_message_text(
                    "❌ No se pudo generar la factura electrónica en Siigo.\n\n"
                    "Proceso completado con errores. Puedes iniciar una nueva factura con /start."
                )
        except Exception as e:
            logger.error(f"Error al generar factura en Siigo: {e}")
            await query.edit_message_text(
                f"❌ Error al generar factura en Siigo: {str(e)}\n\n"
                "Proceso completado con errores. Puedes iniciar una nueva factura con /start."
            )

        return ConversationHandler.END
