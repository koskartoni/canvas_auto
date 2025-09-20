# app/gui/login_window.py

import customtkinter as ctk
import webbrowser
from app.utils import config_manager
from app.utils.logger_config import logger # Importar el logger
import re

class LoginWindow(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Configuración Inicial - Canvas Auto")
        self.geometry("450x380")
        self.resizable(False, False)
        self.grid_columnconfigure(0, weight=1)
        main_frame = ctk.CTkFrame(self)
        main_frame.grid(row=0, column=0, padx=20, pady=20, sticky="nsew")
        main_frame.grid_columnconfigure(1, weight=1)
        title_label = ctk.CTkLabel(main_frame, text="Conexión con Canvas", font=ctk.CTkFont(size=16, weight="bold"))
        title_label.grid(row=0, column=0, columnspan=2, pady=(0, 20))
        url_label = ctk.CTkLabel(main_frame, text="URL de Canvas:")
        url_label.grid(row=1, column=0, padx=10, pady=5, sticky="w")
        self.url_entry = ctk.CTkEntry(main_frame, placeholder_text="https://canvas.instructure.com")
        self.url_entry.grid(row=1, column=1, padx=10, pady=5, sticky="ew")
        token_label = ctk.CTkLabel(main_frame, text="Token de Acceso:")
        token_label.grid(row=2, column=0, padx=10, pady=5, sticky="w")
        self.token_entry = ctk.CTkEntry(main_frame, show="*")
        self.token_entry.grid(row=2, column=1, padx=10, pady=5, sticky="ew")

        gemini_key_label = ctk.CTkLabel(main_frame, text="API Key de Gemini:")
        gemini_key_label.grid(row=3, column=0, padx=10, pady=5, sticky="w")
        self.gemini_key_entry = ctk.CTkEntry(main_frame, show="*")
        self.gemini_key_entry.grid(row=3, column=1, padx=10, pady=5, sticky="ew")

        self.tutorial_button = ctk.CTkButton(main_frame, text="Ayuda para generar token", command=self.open_token_tutorial)
        self.tutorial_button.grid(row=4, column=0, columnspan=2, pady=(10, 0))
        self.save_button = ctk.CTkButton(main_frame, text="Guardar y Continuar", command=self.save_and_continue)
        self.save_button.grid(row=5, column=0, columnspan=2, pady=(20, 0))
        self.status_label = ctk.CTkLabel(main_frame, text="", text_color="red")
        self.status_label.grid(row=6, column=0, columnspan=2, pady=(10, 0))

    def open_token_tutorial(self):
        webbrowser.open("https://youtu.be/mUoPJSxzMW4")

    def _sanitize_url(self, raw: str) -> str:
        return (raw or "").strip().rstrip("/")

    def _sanitize_token(self, raw: str) -> str:
        """
        Acepta que el usuario pegue 'Bearer ...' o desde PDF con saltos de línea.
        Elimina espacios, tabs y saltos (\r\n) y quita el prefijo 'Bearer ' si viene.
        """
        t = (raw or "").strip()
        if t.lower().startswith("bearer "):
            t = t[7:]
        # quita absolutamente todo el whitespace
        t = re.sub(r"\s+", "", t)
        return t

    def save_and_continue(self):
        logger.info("Botón 'Guardar y Continuar' (Login) pulsado.")

        raw_url = self.url_entry.get()
        raw_token = self.token_entry.get()
        raw_gemini_key = self.gemini_key_entry.get()

        url = self._sanitize_url(raw_url)
        token = self._sanitize_token(raw_token)
        gemini_key = (raw_gemini_key or "").strip()

        if not url or not token:
            self.status_label.configure(text="Error: Ambos campos son obligatorios.")
            logger.warning("Intento de guardado en login con campos vacíos.")
            return

        # validación mínima de forma
        if not re.match(r"^https?://", url):
            self.status_label.configure(text="URL no válida. Debe empezar por http(s)://")
            return
        if len(token) < 20 or "~" not in token:
            # los tokens de Canvas suelen ser 'nnnnn~...' (no es obligatorio, pero ayuda)
            self.status_label.configure(text="Token con formato sospechoso. Revísalo.")
            # no hacemos return: permitimos guardar por si tu instancia usa otro formato

        ok = config_manager.save_credentials(url, token, gemini_api_key=gemini_key)
        if ok:
            logger.info("Credenciales guardadas correctamente.")
            self.destroy()
        else:
            self.status_label.configure(text="Error: No se pudo guardar el archivo.")
            logger.error("Fallo al guardar las credenciales en el archivo de configuración.")
