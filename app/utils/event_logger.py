import logging
import functools
from . import config_manager
import os
import sys

# Creamos un logger específico para eventos de la GUI
event_logger = logging.getLogger("event_logger")

# --- Solución al problema del .exe ---
# Determinar la ruta base de la aplicación.
# Si está compilado ('frozen'), la base es el directorio del .exe.
# Si no, es la raíz del proyecto (asumiendo que este archivo está en app/utils/).
if getattr(sys, 'frozen', False):
    application_path = os.path.dirname(sys.executable)
else:
    application_path = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))

log_dir = os.path.join(application_path, "logs")
os.makedirs(log_dir, exist_ok=True)  # Crea el directorio 'logs' si no existe.

# Configuramos un handler para que estos logs vayan a un archivo separado
log_file_path = os.path.join(log_dir, "gui_events.log")
file_handler = logging.FileHandler(log_file_path, encoding='utf-8')
formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
file_handler.setFormatter(formatter)
event_logger.addHandler(file_handler)
event_logger.setLevel(logging.INFO)

# Variable para cachear si el logging está activo y no leer el archivo constantemente
_event_logging_enabled = None

def is_event_logging_enabled():
    """Comprueba si el registro de eventos está habilitado en config.json."""
    global _event_logging_enabled
    if _event_logging_enabled is None:
        # Usamos la función correcta 'load_credentials' y manejamos el caso de que no exista config.
        config = config_manager.load_credentials()
        if config:
            _event_logging_enabled = config.get("enable_event_logging", False)
        else:
            _event_logging_enabled = False # Si no hay config, el logging está desactivado.
    return _event_logging_enabled

def log_action(func):
    """
    Decorador que registra la ejecución de una función (típicamente un comando de botón).
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if is_event_logging_enabled():
            # Intentamos obtener información útil del widget que llamó a la función
            # 'self' suele ser la instancia de la clase del menú (e.g., ActivitiesMenu)
            widget_name = func.__name__
            class_name = self.__class__.__name__
            
            log_message = f"ACTION: Se ejecutó '{widget_name}' en la clase '{class_name}'."
            event_logger.info(log_message)
            
        return func(self, *args, **kwargs)
    return wrapper