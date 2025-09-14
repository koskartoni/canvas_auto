"""
Cliente para la API de Gemini con logging y gestión de errores mejorados.
"""
from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from typing import List, Optional, Any, Dict, Union, Tuple
import json
import logging
import math
import os
import re
import hashlib
import time

try:
    import google.generativeai as genai
except ImportError:
    genai = None

try:
    from PIL import Image
except ImportError:
    Image = None

# Usar un logger específico para este módulo
logger = logging.getLogger(__name__)

@dataclass
class GenerationConfig:
    temperature: float = 0.2
    top_p: float = 0.9
    top_k: int = 32
    max_output_tokens: int = 2048

DEFAULT_SAFETY = [
    {"category": "HARM_CATEGORY_HARASSMENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_HATE_SPEECH", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_SEXUAL", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
    {"category": "HARM_CATEGORY_DANGEROUS_CONTENT", "threshold": "BLOCK_MEDIUM_AND_ABOVE"},
]

class HybridEvaluator:
    """Cliente unificado para evaluaciones con Gemini, con logging integrado."""

    def __init__(
        self,
        api_key: Optional[str] = None,
        gen: Optional[GenerationConfig] = None,
        safety: Optional[List[dict]] = None,
        logger: Optional[logging.Logger] = None,
        max_retries: int = 4,
        base_delay: float = 1.2,
        cache_path: Optional[str] = ".gemini_file_cache.json",
        **kwargs # Captura argumentos no usados como text_model, vision_model
    ) -> None:
        self.logger = logger or logging.getLogger(__name__)
        if genai is None:
            raise ImportError("Falta google-generativeai. Instala con: pip install google-generativeai")

        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError("No se encontró la API Key de Gemini.")
        
        genai.configure(api_key=self.api_key)
        self.logger.info("Cliente de Gemini configurado.")

        self.gen_cfg = gen or GenerationConfig()
        self.safety = safety or DEFAULT_SAFETY
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.cache_path = cache_path
        self._cache: Dict[str, str] = {}
        self._load_cache()

    def _load_cache(self):
        if self.cache_path and os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
                self.logger.info(f"Caché de archivos de Gemini cargado desde '{self.cache_path}' con {len(self._cache)} entradas.")
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(f"No se pudo cargar el caché de archivos de Gemini: {e}")

    def list_evaluation_models(self) -> Tuple[List[str], str]:
        """Devuelve una lista de modelos de Gemini recomendados para evaluación y el modelo por defecto."""
        recommended_models = [
            "gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite",
            "gemini-2.0-flash", "gemini-2.0-flash-lite", "gemini-1.5-pro",
            "gemini-1.5-flash", "gemini-1.0-pro", "gemini-pro-vision",
        ]
        default_model = "gemini-2.5-pro"
        self.logger.debug(f"Modelos de evaluación disponibles: {recommended_models}. Por defecto: {default_model}")
        return recommended_models, default_model

    def _hash_file(self, path: str) -> str:
        """Calcula el hash SHA256 de un archivo."""
        self.logger.debug(f"Calculando hash SHA256 para: {path}")
        h = hashlib.sha256()
        try:
            with open(path, "rb") as f:
                for chunk in iter(lambda: f.read(4096), b""):
                    h.update(chunk)
            return h.hexdigest()
        except IOError as e:
            self.logger.error(f"No se pudo leer el archivo {path} para calcular el hash: {e}", exc_info=True)
            raise

    def _save_cache(self):
        """Guarda el diccionario de caché en un archivo JSON."""
        if self.cache_path:
            try:
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    json.dump(self._cache, f, indent=2)
                self.logger.info(f"Caché de archivos de Gemini guardado en '{self.cache_path}'.")
            except IOError as e:
                self.logger.error(f"Error al guardar el caché de archivos de Gemini: {e}", exc_info=True)

    def upload_or_get_cached(self, pdf_path: str) -> "genai.File":
        """Sube un archivo si no está en caché, o recupera la referencia cacheada."""
        file_hash = self._hash_file(pdf_path)
        if file_hash in self._cache:
            file_name = self._cache[file_hash]
            self.logger.info(f"Cache hit para archivo '{os.path.basename(pdf_path)}'. Usando archivo de Gemini: {file_name}")
            try:
                return genai.get_file(name=file_name)
            except Exception as e:
                self.logger.warning(f"El archivo cacheado {file_name} no se encontró en Gemini. Se volverá a subir. Error: {e}")
                # Eliminar la entrada de caché rota
                del self._cache[file_hash]
        
        self.logger.info(f"Cache miss para '{os.path.basename(pdf_path)}'. Subiendo archivo a Gemini.")
        uploaded_file = self._upload_file_to_gemini(pdf_path)
        self._cache[file_hash] = uploaded_file.name
        self._save_cache()
        return uploaded_file

    def _upload_file_to_gemini(self, pdf_path: str) -> "genai.File":
        """Sube un archivo a la API de Gemini y devuelve el objeto File."""
        self.logger.info(f"Subiendo archivo '{os.path.basename(pdf_path)}' a la API de Gemini...")
        try:
            pdf_file = genai.upload_file(path=pdf_path, display_name=os.path.basename(pdf_path))
            self.logger.info(f"Archivo subido con éxito. Nombre: {pdf_file.name}, URI: {pdf_file.uri}")
            return pdf_file
        except Exception as e:
            self.logger.error(f"Fallo al subir el archivo '{pdf_path}' a Gemini: {e}", exc_info=True)
            raise

    def prepare_pdf_evaluation_request(self, pdf_file_uri: str, rubric_json: dict) -> List[Any]:
        """Prepara el contenido de una única petición de evaluación para ser usada en un lote."""
        self.logger.debug(f"Preparando petición para el archivo URI: {pdf_file_uri}")
        prompt = self._build_rubric_based_prompt(rubric_json)
        uploaded_file = genai.get_file(name=pdf_file_uri)
        return [prompt, uploaded_file]

    def execute_single_request(self, contents: List[Any], model_name: Optional[str] = None) -> Dict[str, Any]:
        """Ejecuta una única petición de evaluación y devuelve el JSON parseado."""
        model_to_use_name = model_name or "gemini-1.5-flash" # Fallback por si no se pasa
        self.logger.info(f"Ejecutando petición única con el modelo: {model_to_use_name}")
        try:
            model_instance = genai.GenerativeModel(model_to_use_name)
        except Exception as e:
            self.logger.error(f"No se pudo inicializar el modelo '{model_to_use_name}'. Error: {e}", exc_info=True)
            # Devolver un error estructurado que el hilo de trabajo pueda procesar
            return {"error": f"Failed to initialize model: {model_to_use_name}"}

        final_text = self._call_with_retry(model_instance, contents)
        return self._json_from_text(final_text)

    def _call_with_retry(self, model: "genai.GenerativeModel", parts: List[Any]) -> str:
        """Llama al modelo con reintentos y backoff exponencial."""
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                self.logger.debug(f"Enviando petición a Gemini (intento {attempt}/{self.max_retries}), modelo: {model.model_name}")
                resp = model.generate_content(parts, generation_config=asdict(self.gen_cfg), safety_settings=self.safety)
                
                # Extraer texto de la respuesta
                text = getattr(resp, "text", None)
                if not text and getattr(resp, "candidates", None):
                    text = resp.candidates[0].content.parts[0].text

                if text:
                    self.logger.debug(f"Respuesta de Gemini recibida (snippet): {text[:250]}...")
                    return text
                else:
                    # Esto puede ocurrir si el contenido es bloqueado por seguridad
                    self.logger.warning(f"Respuesta de Gemini vacía. Prompt Feedback: {resp.prompt_feedback}")
                    raise RuntimeError("Respuesta vacía del modelo, posiblemente bloqueada por filtros de seguridad.")

            except Exception as e:
                last_err = e
                msg = str(e).lower()
                self.logger.warning(f"Intento {attempt}/{self.max_retries} para el modelo {model.model_name} falló: {e}")
                
                if attempt < self.max_retries:
                    if any(code in msg for code in ["429", "rate", "quota"]):
                        delay = self.base_delay * (2 ** attempt) + random.uniform(0, 1)
                        self.logger.info(f"Límite de tasa detectado. Reintentando en {delay:.2f} segundos.")
                    else:
                        delay = self.base_delay * (1.5 ** (attempt - 1))
                    time.sleep(delay)
                else:
                    self.logger.error(f"Fallo definitivo tras {self.max_retries} intentos para el modelo {model.model_name}.")
                    raise RuntimeError(f"Fallo tras reintentos: {last_err}") from last_err
        return "" # No debería alcanzarse

    _FENCE_RE = re.compile(r"^```(?:json)?\n|\n```$", re.IGNORECASE)

    def _json_from_text(self, text: str) -> Dict[str, Any]:
        """Intenta parsear texto a JSON dict, con limpieza y correcciones."""
        if not text:
            self.logger.error("Se intentó parsear una cadena de texto vacía a JSON.")
            return {"error": "Respuesta vacía del modelo"}
        
        self.logger.debug(f"Parseando texto a JSON. Snippet: {text[:200]}")
        cleaned = self._FENCE_RE.sub("", text.strip()).strip()

        if not cleaned.startswith("{"):
            match = re.search(r"\{[\s\S]*\}\s*$", cleaned)
            if match:
                self.logger.debug("Se encontró un objeto JSON anidado. Extrayéndolo.")
                cleaned = match.group(0)

        try:
            return json.loads(cleaned)
        except json.JSONDecodeError as e:
            self.logger.warning(f"Fallo al parsear JSON: {e}. Intentando corregir errores comunes.")
            # Corregir comas finales, booleanos/nulos de Python
            fixed = re.sub(r",\s*([}\]])", r"\1", cleaned)
            fixed = re.sub(r"\bTrue\b", "true", fixed)
            fixed = re.sub(r"\bFalse\b", "false", fixed)
            fixed = re.sub(r"\bNone\b", "null", fixed)
            try:
                data = json.loads(fixed)
                self.logger.info("JSON parseado con éxito después de correcciones.")
                return data
            except json.JSONDecodeError as final_e:
                self.logger.error(f"Fallo definitivo al parsear JSON. Error: {final_e}. Texto original (limpio):\n{cleaned}")
                return {"error": "Formato de respuesta JSON inválido", "details": str(final_e)}

    def _build_rubric_based_prompt(self, rubric_json: dict) -> str:
        # ... (el contenido de este método no necesita logging intensivo, se mantiene igual)
        criteria_data = []
        for crit in rubric_json.get('data', []):
            ratings_info = []
            for r in crit.get('ratings', []):
                ratings_info.append({"categoria": r.get('description', 'N/A'), "puntuacion": r.get('points', 0.0)})
            criteria_data.append({
                "criterio_nombre": crit.get('description', 'Criterio sin nombre'),
                "puntuacion_maxima": crit.get('points', 0.0),
                "posibles_ratings": ratings_info
            })
        rubric_text = json.dumps(criteria_data, ensure_ascii=False, indent=2)
        new_schema = '''{
  "evaluacion": [
    {
      "criterio": "Nombre exacto del criterio de la rúbrica",
      "categoria": "Nombre exacto de la categoría elegida (ej. Excelente, Bien...)",
      "puntuacion": "Puntuación numérica exacta correspondiente a la categoría elegida",
      "justificacion": "Justificación concisa basada en el documento."
    }
  ],
  "resumen_cualitativo": "Un resumen de 3-4 frases sobre las fortalezas y debilidades generales del trabajo, con una recomendación de mejora."
}'''
        return (
            "Eres un asistente de profesor universitario experto. Tu tarea es evaluar la entrega de un alumno (archivo PDF adjunto) "
            "utilizando ESTRICTAMENTE la siguiente rúbrica de evaluación. Debes ser objetivo y basar tu puntuación y justificación "
            "únicamente en el contenido del documento y los criterios de la rúbrica.\n\n"
            "RÚBRICA OFICIAL (en formato JSON):\n"
            f"{rubric_text}\n\n"
            "INSTRUCCIONES DETALLADAS Y OBLIGATORIAS:\n"
            "1. **Analiza el PDF adjunto** en su totalidad para comprender el trabajo del alumno.\n"
            "2. **Evalúa CADA UNO de los criterios listados en la rúbrica**: Para cada criterio, debes elegir UNA de las 'posibles_ratings' (categorías) que mejor se ajuste al contenido del PDF. Asigna la 'puntuacion' exacta de esa categoría.\n"
            "3. **Formato de Salida OBLIGATORIO**: Devuelve un ÚNICO objeto JSON válido y minificado. No incluyas explicaciones, comentarios, ni ```json ... ```. La respuesta debe ser exclusivamente el JSON.\n"
            "4. **Esquema del JSON de Salida**: El JSON debe seguir este esquema exacto:\n"
            f"{new_schema}\n"
            "5. **Consistencia de Nombres**: En tu respuesta, la clave 'criterio' debe contener el valor exacto de 'criterio_nombre' de la rúbrica. La clave 'categoria' debe contener el valor exacto de la 'categoria' elegida de la rúbrica.\n"
            "6. **INSTRUCCIÓN CRÍTICA PARA CRITERIOS SIN EVIDENCIA**: Si en el documento no encuentras NINGUNA evidencia para poder evaluar un criterio específico, DEBES asignarle la categoría y puntuación más bajas disponibles en la rúbrica para ese criterio (normalmente 0 puntos) y usar una justificación clara como: 'No se encontró evidencia en el documento para evaluar este criterio.'\n"
            "7. **Resumen Cualitativo**: Al final, proporciona un resumen general en la clave 'resumen_cualitativo'."
        )
