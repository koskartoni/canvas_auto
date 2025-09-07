"""
HybridEvaluator: fusión de los dos enfoques
- Soporta entrada multimodal (texto + imágenes PIL) y PDFs (por páginas con PyMuPDF/fitz)
- Reintentos con backoff exponencial + logging opcional
- Configuración de generación y safety explícitas
- Ensambla resultados por chunk/página y sintetiza a JSON validado (dict)

Requisitos (opcionales según el uso):
  pip install google-generativeai pillow PyMuPDF

Nota: Sustituye `YOUR_API_KEY` por tu clave o pásala al constructor.
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
except Exception:  # pragma: no cover

    genai = None  # Permite cargar el módulo aunque no esté instalado en el entorno

try:
    from PIL import Image
except Exception:  # pragma: no cover
    Image = None

try:
    import fitz  # PyMuPDF
except Exception:  # pragma: no cover
    fitz = None


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
    """Cliente unificado para evaluaciones con Gemini (texto/visión) y PDFs.

    - evaluate_mixed(text, images)
    - evaluate_pdf(pdf_path)

    Devuelve siempre un dict (JSON) validado. Lanza excepción si no es posible construir JSON.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        text_model: str = "gemini-1.5-pro",
        vision_model: str = "gemini-1.5-flash",  # rápido y multimodal; ajusta si lo prefieres
        gen: Optional[GenerationConfig] = None,
        safety: Optional[List[dict]] = None,
        logger: Optional[logging.Logger] = None,
        max_retries: int = 4,
        base_delay: float = 1.2,
        chunk_chars: int = 7000,
        cache_path: Optional[str] = ".gemini_file_cache.json"
    ) -> None:
        if genai is None:
            raise ImportError("Falta google-generativeai. Instala con: pip install google-generativeai")

        # Prioridad: 1. Argumento directo, 2. Variables de entorno
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY") or os.getenv("GEMINI_API_KEY")
        if not self.api_key:
            raise ValueError(
                "No se encontró la API Key de Gemini. Por favor, configúrala en 'config.json' (con la clave 'gemini_api_key') "
                "o como variable de entorno ('GOOGLE_API_KEY')."
            )
        genai.configure(api_key=self.api_key)

        self.text_model_name = text_model
        self.vision_model_name = vision_model
        self.gen_cfg = gen or GenerationConfig()
        self.safety = safety or DEFAULT_SAFETY
        self.logger = logger or logging.getLogger(__name__)
        self.max_retries = max_retries
        self.base_delay = base_delay
        self.chunk_chars = chunk_chars
        self.cache_path = cache_path
        self._cache: Dict[str, str] = {}
        if self.cache_path and os.path.exists(self.cache_path):
            try:
                with open(self.cache_path, "r", encoding="utf-8") as f:
                    self._cache = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                self.logger.warning(f"No se pudo cargar el caché de archivos de Gemini: {e}")

        # Modelos
        self._text_model = genai.GenerativeModel(self.text_model_name)
        self._vision_model = genai.GenerativeModel(self.vision_model_name)

    # -------------------------- PÚBLICO ----------------------------------
    def list_evaluation_models(self) -> Tuple[List[str], str]:
        """
        Devuelve una lista de modelos de Gemini recomendados para evaluación y el modelo por defecto.
        """
        # Lista de modelos compatibles con la evaluación de texto/PDF/imágenes, basada en la documentación.
        # https://ai.google.dev/gemini-api/docs/models?hl=es-419
        recommended_models = [
            # Modelos más nuevos y potentes
            "gemini-2.5-pro",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
            "gemini-2.0-flash",
            "gemini-2.0-flash-lite",
            
            # Modelos establecidos y fiables
            "gemini-1.5-pro",
            "gemini-1.5-flash",
            "gemini-1.0-pro",
            "gemini-pro-vision",
        ]
        # El 2.5 Pro se establece como el predeterminado por su capacidad de razonamiento superior.
        default_model = "gemini-2.5-pro"

        return recommended_models, default_model

    def evaluate_mixed(self, text: str, images: Optional[List["Image.Image"]] = None, schema_hint: Optional[str] = None) -> Dict[str, Any]:
        """Evalúa entrada multimodal en chunks de texto (+ imágenes solo en el primer chunk).
        """
        chunks = self._chunk_text(text, self.chunk_chars)
        partials: List[Dict[str, Any]] = []

        for idx, chunk in enumerate(chunks):
            parts = []
            if idx == 0 and images:
                # Adjuntamos imágenes al primer turno
                for img in images:
                    parts.append(img)
            parts.append(self._build_chunk_prompt(chunk, idx + 1, len(chunks), schema_hint))

            resp_text = self._call_with_retry(self._vision_model, parts)
            partials.append(self._json_from_text(resp_text))

        # Síntesis final
        synth_prompt = self._build_synthesis_prompt(partials, schema_hint)
        final_text = self._call_with_retry(self._text_model, synth_prompt)
        return self._json_from_text(final_text)

    def _hash_file(self, path: str) -> str:
        """Calcula el hash SHA256 de un archivo."""
        h = hashlib.sha256()
        with open(path, "rb") as f:
            # Leer en chunks para no consumir demasiada memoria
            for chunk in iter(lambda: f.read(4096), b""):
                h.update(chunk)
        return h.hexdigest()

    def _save_cache(self):
        """Guarda el diccionario de caché en un archivo JSON."""
        if self.cache_path:
            try:
                with open(self.cache_path, "w", encoding="utf-8") as f:
                    json.dump(self._cache, f, indent=2)
            except IOError as e:
                self.logger.error(f"Error al guardar el caché de archivos de Gemini: {e}")

    def upload_or_get_cached(self, pdf_path: str) -> "genai.File":
        """Sube un archivo si no está en caché, o recupera la referencia cacheada."""
        file_hash = self._hash_file(pdf_path)
        if file_hash in self._cache:
            try:
                return genai.get_file(name=self._cache[file_hash])
            except Exception:
                self.logger.warning(f"El archivo cacheado {self._cache[file_hash]} no se encontró en Gemini. Se volverá a subir.")
        uploaded_file = self._upload_file_to_gemini(pdf_path)
        self._cache[file_hash] = uploaded_file.name
        self._save_cache()
        return uploaded_file

    def _upload_file_to_gemini(self, pdf_path: str) -> "genai.File":
        """Sube un archivo a la API de Gemini y devuelve el objeto File."""
        self.logger.info(f"Subiendo archivo a la API de Gemini: {pdf_path}")
        # El display_name es opcional, pero útil para la depuración.
        pdf_file = genai.upload_file(path=pdf_path, display_name=os.path.basename(pdf_path))
        self.logger.info(f"Archivo subido con éxito. URI: {pdf_file.uri}")
        return pdf_file

    def evaluate_pdf(self, pdf_path: str, schema_hint: Optional[str] = None) -> Dict[str, Any]:
        """
        Evalúa un PDF completo usando la API de Archivos. NO gestiona la subida/borrado.
        """
        if fitz is None:
            raise ImportError("Falta PyMuPDF. Instala con: pip install PyMuPDF")

        pdf_file = None
        try:
            # 1. Subir el archivo
            pdf_file = self.upload_or_get_cached(pdf_path)

            # 2. Construir el prompt
            # Ya no necesitamos extraer el texto manualmente, el modelo lo hará desde el archivo.
            prompt = self._build_page_prompt("", 1, 1, schema_hint) # Pasamos texto vacío

            # 3. Construir las partes de la petición
            all_parts = [
                prompt,
                pdf_file # ¡Simplemente pasamos el objeto del archivo!
            ]

            # 4. Llamar a la API (una única llamada)
            final_text = self._call_with_retry(self._vision_model, all_parts)
            return self._json_from_text(final_text)
        finally: # pragma: no cover
            pass # No se borra el archivo, se mantiene en caché para ejecuciones futuras

    def _build_rubric_based_prompt(self, rubric_json: dict) -> str:
        """Construye un prompt muy específico basado en la rúbrica oficial."""
        criteria_data = []
        # Extraer los criterios y sus posibles ratings (categoría y puntos)
        for crit in rubric_json.get('data', []):
            ratings_info = []
            for r in crit.get('ratings', []):
                ratings_info.append({
                    "categoria": r.get('description', 'N/A'),
                    "puntuacion": r.get('points', 0.0)
                })
            criteria_data.append({
                "criterio_nombre": crit.get('description', 'Criterio sin nombre'),
                "puntuacion_maxima": crit.get('points', 0.0),
                "posibles_ratings": ratings_info
            })

        rubric_text = json.dumps(criteria_data, ensure_ascii=False, indent=2)

        # El nuevo esquema JSON que esperamos
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

    def prepare_pdf_evaluation_request(self, pdf_file_uri: str, rubric_json: dict) -> List[Any]:
        """
        Prepara el contenido de una única petición de evaluación para ser usada en un lote.
        NO la ejecuta, solo prepara la lista de partes ('contents').
        """
        prompt = self._build_rubric_based_prompt(rubric_json)
        uploaded_file = genai.get_file(name=pdf_file_uri)
        # Devuelve la lista de 'contents' lista para el batch
        return [prompt, uploaded_file]

    def execute_single_request(self, contents: List[Any], model_name: Optional[str] = None) -> Dict[str, Any]:
        """
        Ejecuta una única petición de evaluación y devuelve el JSON parseado.
        Diseñado para ser usado en un bucle o un pool de hilos.
        Permite especificar un modelo a usar para esta petición.
        """
        model_to_use = self._vision_model
        # Si se especifica un nombre de modelo y es diferente al modelo de visión por defecto
        if model_name and model_name != self.vision_model_name:
            try:
                self.logger.info(f"Utilizando modelo de evaluación personalizado: {model_name}")
                # Crea una instancia del modelo solo si es diferente para evitar sobrecarga
                model_to_use = genai.GenerativeModel(model_name)
            except Exception as e:
                self.logger.warning(
                    f"No se pudo inicializar el modelo '{model_name}'. "
                    f"Se usará el modelo por defecto ({self.vision_model_name}). Error: {e}"
                )
        
        # Reutilizamos la lógica de reintentos
        final_text = self._call_with_retry(model_to_use, contents)
        # Reutilizamos la lógica de parseo de JSON
        return self._json_from_text(final_text)
        
    # -------------------------- INTERNOS ---------------------------------
    def _call_with_retry(self, model, parts_or_text: Union[str, List[Any]]) -> str:
        """Llama al modelo con reintentos y backoff. Acepta string o lista multimodal."""
        last_err: Optional[Exception] = None
        for attempt in range(1, self.max_retries + 1):
            try:
                # Log de DEBUG para el contenido enviado a Gemini
                if self.logger.level == logging.DEBUG:
                    log_content = []
                    if isinstance(parts_or_text, list):
                        for part in parts_or_text:
                            if hasattr(part, 'category') and hasattr(part, 'threshold'): # Safety setting
                                continue
                            if isinstance(part, str):
                                log_content.append(f"[Text Snippet: {part[:100]}...]")
                            elif Image and isinstance(part, Image.Image):
                                log_content.append(f"[Image: {part.format} {part.size}]")
                            else:
                                log_content.append(f"[Unknown Part: {type(part)}]")
                    else:
                        log_content.append(f"[Text Snippet: {parts_or_text[:100]}...]")
                    self.logger.debug(f"Sending to Gemini model '{model.model_name}': {' '.join(log_content)}")

                if isinstance(parts_or_text, list):
                    resp = model.generate_content(parts_or_text, generation_config=asdict(self.gen_cfg), safety_settings=self.safety)
                else:
                    resp = model.generate_content(parts_or_text, generation_config=asdict(self.gen_cfg), safety_settings=self.safety)
                if hasattr(resp, "text") and resp.text:
                    self.logger.debug(f"Gemini Response (snippet): {resp.text[:500]}...")
                    return resp.text
                # Algunas versiones exponen candidatos
                if getattr(resp, "candidates", None):
                    text = resp.candidates[0].content.parts[0].text
                    if text:
                        return text
                raise RuntimeError("Respuesta sin texto del modelo")
            except Exception as e:  # pragma: no cover
                last_err = e
                msg = str(e)
                self.logger.warning("Intento %d/%d falló: %s", attempt, self.max_retries, msg)
                # Heurística de rate limit
                if any(code in msg for code in ["429", "rate", "Rate"]):
                    delay = self.base_delay * (2 ** (attempt - 1))
                else:
                    delay = min(self.base_delay * (1.5 ** (attempt - 1)), 8.0)
                time.sleep(delay)
        # Si llegamos aquí, no hubo éxito
        raise RuntimeError(f"Fallo tras reintentos: {last_err}")

    def _chunk_text(self, text: str, size: int) -> List[str]:
        text = text or ""
        if len(text) <= size:
            return [text]
        chunks = []
        start = 0
        while start < len(text):
            end = min(start + size, len(text))
            chunks.append(text[start:end])
            start = end
        return chunks

    def _build_chunk_prompt(self, chunk: str, idx: int, total: int, schema_hint: Optional[str]) -> str:
        return (
            "Eres un evaluador. Analiza este fragmento de una entrega (" f"chunk {idx}/{total})."
            + "\n\nCONTENIDO:\n" + chunk.strip() +
            "\n\nDevuelve SOLO JSON válido y minificado (sin explicaciones). "
            + (f"Ajusta al siguiente esquema si aplica: {schema_hint}\n" if schema_hint else "")
            + "Usa campos consistentes entre chunks."
        )

    def _build_page_prompt(self, page_text: str, page_no: int, total_pages: int, schema_hint: Optional[str]) -> str:
        return (
            "Eres un evaluador. Analiza el siguiente documento PDF completo (imágenes adjuntas y texto a continuación).\n\n"
            "CONTENIDO DEL TEXTO EXTRAÍDO DEL PDF:\n" + page_text.strip() +
            "\n\nDevuelve SOLO JSON válido y minificado (sin explicaciones). "
            + (f"Ajusta al siguiente esquema si aplica: {schema_hint}\n" if schema_hint else "")
        )

    def _build_synthesis_prompt(self, partials: List[Dict[str, Any]], schema_hint: Optional[str]) -> str:
        return (
            "Combina de forma consistente los siguientes JSON parciales en un ÚNICO JSON final, "
            "deduplicando y resolviendo conflictos (preferir evidencias más completas).\n\nPARCIALES:\n"
            + json.dumps(partials, ensure_ascii=False)
            + "\n\nDevuelve SOLO JSON válido y minificado. "
            + (f"Ajusta al siguiente esquema si aplica: {schema_hint}" if schema_hint else "")
        )

    # -------------------------- UTILIDADES JSON --------------------------
    _FENCE_RE = re.compile(r"^```(?:json)?\n|\n```$", re.IGNORECASE)

    def _json_from_text(self, text: str) -> Dict[str, Any]:
        """Intenta parsear texto a JSON dict. Limpia fences y corrige algunos errores comunes.
        Lanza ValueError si no puede devolver un dict.
        """
        if text is None:
            raise ValueError("Respuesta vacía del modelo")
        cleaned = text.strip()
        cleaned = self._FENCE_RE.sub("", cleaned)
        cleaned = cleaned.strip()

        # Heurísticas: si empieza con algo que no es {, intenta localizar el primer {...}
        if not cleaned.startswith("{"):
            m = re.search(r"\{[\s\S]*\}\s*$", cleaned)
            if m:
                cleaned = m.group(0)

        try:
            data = json.loads(cleaned)
        except Exception as e:
            # Último intento: arreglar comas colgantes y true/false/none estilo Python
            fixed = cleaned
            fixed = re.sub(r",\s*([}\]])", r"\1", fixed)
            fixed = re.sub(r"\bTrue\b", "true", fixed)
            fixed = re.sub(r"\bFalse\b", "false", fixed)
            fixed = re.sub(r"\bNone\b", "null", fixed)
            data = json.loads(fixed)

        if not isinstance(data, dict):
            # En caso de lista raíz, lo envolvemos en un objeto estándar
            return {"items": data}
        return data


# ------------------------------ EJEMPLO ---------------------------------
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    evaluator = HybridEvaluator(api_key=os.getenv("GOOGLE_API_KEY", "YOUR_API_KEY"))

    # Ejemplo multimodal
    sample_text = '''Resumen del ejercicio 1 y 2... (texto largo)'''
    images = []
    if Image:
        # Crea una imagen en blanco de ejemplo (opcional)
        img = Image.new("RGB", (200, 100), color=(240, 240, 240))
        images.append(img)
    try:
        result = evaluator.evaluate_mixed(sample_text, images, schema_hint="{'resumen': str, 'puntos': [str]} ")
        print("Resultado multimodal:", json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as e:
        print("Multimodal falló (probablemente por API key de ejemplo):", e)

    # Ejemplo PDF (requiere PyMuPDF y un archivo real)
    pdf_demo = os.getenv("PDF_DEMO_PATH")
    if pdf_demo and os.path.exists(pdf_demo):
        try:
            result_pdf = evaluator.evaluate_pdf(pdf_demo, schema_hint="{'hallazgos': [str]}")
            print("Resultado PDF:", json.dumps(result_pdf, ensure_ascii=False, indent=2))
        except Exception as e:
            print("PDF falló:", e)
