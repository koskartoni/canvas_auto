# app/utils/logger_config.py

import logging
import os
from logging.handlers import RotatingFileHandler

def setup_logging(log_level="INFO"):
    """Configura el sistema de logging para toda la aplicación."""
    # Crear la carpeta de logs si no existe
    if not os.path.exists('logs'):
        os.makedirs('logs')

    # Formato del log
    log_formatter = logging.Formatter(
        '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    # Configurar el logger raíz
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Limpiar handlers existentes para evitar duplicados
    if root_logger.hasHandlers():
        root_logger.handlers.clear()

    # 1. Handler para guardar todos los logs a un archivo rotativo
    file_handler = RotatingFileHandler(
        'logs/canvas_auto.log', maxBytes=5*1024*1024, backupCount=2, encoding='utf-8'
    )
    file_handler.setFormatter(log_formatter)
    root_logger.addHandler(file_handler)

    # 2. Handler para mostrar logs en la consola (para depuración en tiempo real)
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(log_formatter)
    root_logger.addHandler(console_handler)

    # Silenciar loggers de librerías de terceros que son muy verbosos
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("google.generativeai").setLevel(logging.WARNING)

    logging.info("Sistema de logging configurado.")

# Obtener un logger para un módulo específico
logger = logging.getLogger(__name__)
