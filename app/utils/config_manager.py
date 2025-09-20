# app/utils/config_manager.py

import json
import os

# Definimos una ruta consistente para el archivo de configuración
CONFIG_FILE = "config.json"


def save_credentials(url: str, token: str, gemini_api_key: str = None):
    """Guarda las credenciales en el archivo de configuración."""
    credentials = {
        "canvas_url": url,
        "api_token": token,
        "gemini_api_key": gemini_api_key or ""
    }
    try:
        with open(CONFIG_FILE, 'w', encoding="utf-8") as f:
            json.dump(credentials, f, indent=4)
        return True
    except IOError as e:
        print(f"Error al guardar el archivo de configuración: {e}")
        return False


def load_credentials():
    """Carga la URL y el token desde el archivo de configuración."""
    if not os.path.exists(CONFIG_FILE):
        return None

    try:
        with open(CONFIG_FILE, 'r', encoding="utf-8") as f:
            credentials = json.load(f)
            if "canvas_url" in credentials and "api_token" in credentials:
                return credentials
            else:
                return None
    except (IOError, json.JSONDecodeError) as e:
        print(f"Error al leer o procesar el archivo de configuración: {e}")
        return None