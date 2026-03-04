# main.py

import os
import sys

# Corregir rutas de Tcl/Tk para Python 3.14
os.environ['TCL_LIBRARY'] = r"C:\Users\koska\AppData\Local\Programs\Python\Python314\tcl\tcl8.6"
os.environ['TK_LIBRARY'] = r"C:\Users\koska\AppData\Local\Programs\Python\Python314\tcl\tk8.6"

import customtkinter as ctk
from tkinter import messagebox

# Añade el directorio raíz del proyecto al path de Python
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from app.utils.logger_config import setup_logging, logger
from app.utils import config_manager
from app.api.canvas_client import CanvasClient
from app.api.gemini_client import HybridEvaluator
from app.gui.login_window import LoginWindow
from app.gui.course_window import CourseWindow
from app.gui.main_window import MainWindow

def safe_messagebox(func, title, message, **kwargs):
    """Muestra un messagebox de forma segura, capturando TclError si Tcl/Tk no está disponible."""
    try:
        return func(title, message, **kwargs)
    except Exception as e:
        logger.error(f"No se pudo mostrar el mensaje '{title}': {message}. Error de Tcl/Tk: {e}")
        # Si falló el messagebox, al menos imprimimos en consola como último recurso
        print(f"\n[{title.upper()}] {message}\n")

class App:
    def __init__(self):
        logger.info("Iniciando aplicación Canvas Auto...")
        try:
            ctk.set_appearance_mode("System")
            ctk.set_default_color_theme("blue")
        except Exception as e:
            logger.error(f"Error al configurar la apariencia de customtkinter: {e}")

        credentials = self.handle_login()
        if not credentials:
            logger.warning("No se proporcionaron credenciales. Saliendo.")
            return

        # Pasar el logger a los clientes de API
        self.client = CanvasClient(
            credentials['canvas_url'], 
            credentials['api_token'], 
            logger=logger
        )
        if self.client.error_message:
            # El error ya es logueado por el cliente, solo se muestra al usuario
            safe_messagebox(messagebox.showerror, "Error de Conexión", self.client.error_message)
            return

        gemini_api_key = credentials.get('gemini_api_key')
        self.gemini_evaluator = None
        if gemini_api_key:
            try:
                self.gemini_evaluator = HybridEvaluator(api_key=gemini_api_key, logger=logger)
            except (ImportError, ValueError) as e:
                logger.warning(f"No se pudo inicializar Gemini: {e}. La función de evaluación no estará disponible.")
                safe_messagebox(messagebox.showwarning, "Advertencia de Gemini", f"No se pudo inicializar el evaluador de Gemini: {e}")
        else:
            logger.info("No se encontró la clave de API de Gemini. La evaluación con IA estará deshabilitada.")

        self.run_main_flow()

    def handle_login(self):
        """Gestiona la carga de credenciales o solicita nuevas."""
        credentials = config_manager.load_credentials()
        if not credentials:
            try:
                login_win = LoginWindow() 
                login_win.mainloop()
                credentials = config_manager.load_credentials()
            except Exception as e:
                logger.critical(f"Error fatal al abrir la ventana de login: {e}", exc_info=True)
                safe_messagebox(messagebox.showerror, "Error Fatal", f"No se pudo abrir la ventana de login: {e}")
                return None
        return credentials

    def run_main_flow(self):
        """Ejecuta el flujo principal de la aplicación."""
        try:
            while True:
                course_win = CourseWindow(self.client) 
                selected_course_id = course_win.get_selected_course()

                if not selected_course_id:
                    logger.info("No se seleccionó ningún curso. Saliendo de la aplicación.")
                    break

                main_app = MainWindow(client=self.client, course_id=selected_course_id, gemini_evaluator=self.gemini_evaluator)
                main_app.mainloop()

                if not main_app.restart:
                    break
        except Exception as e:
            logger.critical(f"Error inesperado en el flujo principal: {e}", exc_info=True)
            safe_messagebox(messagebox.showerror, "Error en Aplicación", f"Ocurrió un error inesperado: {e}")

        logger.info("Aplicación cerrada.")

if __name__ == "__main__":
    # Configurar el logging para toda la aplicación antes de que nada más se ejecute
    try:
        config = config_manager.load_credentials()
        log_level = config.get("log_level", "INFO") if config else "INFO"
        setup_logging(log_level=log_level)
    except Exception as e:
        # Fallback si falla la lectura de configuración o setup de logs
        import logging
        logging.basicConfig(level=logging.INFO)
        print(f"Error inicializando logging: {e}")

    try:
        app = App()
    except Exception as e:
        logger.critical("Ha ocurrido un error fatal y no controlado en la aplicación.", exc_info=True)
        safe_messagebox(messagebox.showerror, "Error Fatal", f"Ha ocurrido un error no recuperable: {e}\n\nConsulte 'logs/canvas_auto.log' para más detalles.")
