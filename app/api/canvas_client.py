# app/api/canvas_client.py
import json
import csv
import os
import re
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional
import logging

import requests
from canvasapi import Canvas
from canvasapi.exceptions import InvalidAccessToken, Unauthorized, CanvasException

# Usar un logger específico para este módulo
logger = logging.getLogger(__name__)

class CanvasClient:
    """
    Cliente unificado para Canvas LMS, con logging integrado.
    """

    # --------------------------------------------------------------------- #
    # 1. Inicialización y Autenticación
    # --------------------------------------------------------------------- #
    def __init__(self, canvas_url: str, api_token: str, logger: Optional[logging.Logger] = None):
        self.canvas_url = canvas_url.rstrip("/")
        self.api_token = api_token
        self.error_message: str | None = None
        self.logger = logger or logging.getLogger(__name__)

        try:
            self.canvas = Canvas(self.canvas_url, self.api_token)
            user = self.canvas.get_current_user()
            self.logger.info(f"Conectado a Canvas como '{user.name}' (ID: {user.id})")
        except (InvalidAccessToken, Unauthorized):
            self.canvas = None
            self.error_message = "Token de acceso inválido o sin permisos."
            self.logger.critical(self.error_message, exc_info=True)
        except requests.exceptions.RequestException as e:
            self.canvas = None
            self.error_message = f"Error de red al conectar con Canvas: {e}"
            self.logger.critical(self.error_message, exc_info=True)
        except Exception as e:
            self.canvas = None
            self.error_message = f"No se pudo conectar a Canvas: {e}"
            self.logger.critical(self.error_message, exc_info=True)

    def _auth_headers(self) -> dict:
        return {
            "Authorization": f"Bearer {self.api_token}",
            "Content-Type": "application/json",
        }

    def _get_paginated_data(self, url: str, params: Optional[dict] = None) -> list:
        """Realiza peticiones GET a un endpoint paginado y devuelve todos los resultados."""
        if not self.canvas:
            return []
        
        results = []
        next_url = f"{self.canvas_url}{url}"
        self.logger.debug(f"Iniciando paginación para: {next_url} con params: {params}")

        try:
            while next_url:
                response = requests.get(next_url, headers=self._auth_headers(), params=params, timeout=30)
                response.raise_for_status()
                data = response.json()
                results.extend(data)

                # Canvas usa el header 'Link' para la paginación
                next_link = response.links.get("next")
                next_url = next_link["url"] if next_link else None
                if params:
                    params = None # Los parámetros solo se envían en la primera petición

            self.logger.info(f"Paginación completada para {url}. Total de {len(results)} resultados obtenidos.")
            return results
        except requests.exceptions.HTTPError as e:
            self.error_message = f"Error HTTP durante la paginación: {e.response.status_code} para {url}"
            self.logger.error(f"{self.error_message}. Response: {e.response.text}", exc_info=True)
            return []
        except requests.exceptions.RequestException as e:
            self.error_message = f"Error de red durante la paginación para {url}: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return []

    # --------------------------------------------------------------------- #
    # 2. Cursos, Actividades y Entregas
    # --------------------------------------------------------------------- #
    def get_active_courses(self) -> list[dict] | None:
        """Devuelve todos los cursos en los que el usuario está activo."""
        if not self.canvas: return None
        self.logger.info("Obteniendo lista de cursos activos...")
        try:
            courses = self.canvas.get_courses(enrollment_state="active")
            course_list = [{"id": c.id, "name": c.name} for c in courses]
            self.logger.info(f"Se encontraron {len(course_list)} cursos activos.")
            return course_list
        except Exception as e:
            self.error_message = f"Error al obtener cursos: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None

    def get_course(self, course_id: int):
        if not self.canvas: return None
        self.logger.debug(f"Obteniendo objeto curso para ID: {course_id}")
        try:
            return self.canvas.get_course(course_id)
        except Exception as e:
            self.error_message = f"No se pudo obtener el curso {course_id}: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None

    def get_assignment_groups_with_assignments(self, course_id: int) -> List[Dict[str, Any]]:
        """Obtiene los grupos de actividades de un curso, incluyendo las actividades de cada grupo."""
        self.logger.info(f"Obteniendo grupos de actividades con actividades para el curso {course_id}.")
        url = f"/api/v1/courses/{course_id}/assignment_groups"
        params = {"include[]": "assignments", "per_page": 100}
        return self._get_paginated_data(url, params=params)

    def get_assignment_submission_summary(self, course_id: int, assignment_id: int) -> Dict[str, Any] | None:
        """Obtiene un resumen de las entregas para una actividad."""
        self.logger.info(f"Obteniendo resumen de entregas para actividad {assignment_id} en curso {course_id}.")
        try:
            # 1. Obtener detalles de la actividad
            assignment_url = f"/api/v1/courses/{course_id}/assignments/{assignment_id}"
            assignment_response = requests.get(f"{self.canvas_url}{assignment_url}", headers=self._auth_headers(), timeout=30)
            assignment_response.raise_for_status()
            assignment = assignment_response.json()

            # 2. Obtener todas las entregas
            submissions = self.get_all_submissions(course_id, assignment_id)

            # 3. Procesar para el resumen
            students_with_pdf = set()
            for sub in submissions:
                user_id = sub.get("user_id")
                if user_id in students_with_pdf: continue

                all_attachments = sub.get("attachments", [])
                if sub.get("submission_history"):
                    for history_item in sub.get("submission_history", []):
                        all_attachments.extend(history_item.get("attachments", []))
                
                if any(att.get("filename", "").lower().endswith(".pdf") for att in all_attachments):
                    students_with_pdf.add(user_id)

            has_rubric = "rubric" in assignment and assignment["rubric"] is not None
            rubric_id = assignment.get("rubric_settings", {}).get("id") if has_rubric else None

            summary = {
                "submission_count": len(submissions),
                "pdf_submission_count": len(students_with_pdf),
                "has_rubric": has_rubric,
                "rubric_id": rubric_id,
            }
            self.logger.info(f"Resumen para actividad {assignment_id}: {summary}")
            return summary
        except requests.exceptions.RequestException as e:
            self.error_message = f"Error de red al obtener resumen de actividad {assignment_id}: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None
        except Exception as e:
            self.error_message = f"Error inesperado al obtener resumen de actividad {assignment_id}: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None

    def get_all_submissions(self, course_id: int, assignment_id: int) -> List[Dict[str, Any]]:
        """Obtiene todas las entregas para una actividad específica."""
        self.logger.info(f"Obteniendo todas las entregas para actividad {assignment_id} en curso {course_id}.")
        url = f"/api/v1/courses/{course_id}/assignments/{assignment_id}/submissions"
        params = {"include[]": ["user", "submission_history"], "per_page": 100}
        return self._get_paginated_data(url, params=params)

    def download_file(self, url: str, folder_path: Path, filename: str) -> bool:
        """Descarga un único archivo desde una URL y lo guarda en una ruta específica."""
        file_path = folder_path / filename
        self.logger.debug(f"Iniciando descarga de '{url}' a '{file_path}'")
        try:
            os.makedirs(folder_path, exist_ok=True)
            headers = {'Authorization': f'Bearer {self.api_token}'}
            with requests.get(url, headers=headers, stream=True, timeout=60) as r:
                r.raise_for_status()
                with open(file_path, 'wb') as f:
                    for chunk in r.iter_content(chunk_size=8192):
                        f.write(chunk)
            self.logger.info(f"Archivo descargado con éxito: {file_path}")
            return True
        except requests.exceptions.RequestException as e:
            self.error_message = f"Error de red al descargar '{url}': {e}"
            self.logger.error(self.error_message, exc_info=True)
            return False
        except IOError as e:
            self.error_message = f"Error de escritura al guardar '{file_path}': {e}"
            self.logger.error(self.error_message, exc_info=True)
            return False

    # --------------------------------------------------------------------- #
    # 3. Quizzes (Creación y Gestión)
    # --------------------------------------------------------------------- #
    def get_quizzes(self, course_id: int) -> list[dict] | None:
        """Devuelve todos los quizzes clásicos de un curso."""
        if not self.canvas: return None
        self.logger.info(f"Obteniendo quizzes clásicos para el curso {course_id}.")
        try:
            course = self.get_course(course_id)
            if not course: return None
            quizzes = list(course.get_quizzes())
            self.logger.info(f"Se encontraron {len(quizzes)} quizzes clásicos.")
            return [{"id": q.id, "title": q.title} for q in quizzes]
        except Exception as e:
            self.error_message = f"Error al obtener quizzes clásicos: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None

    def get_new_quizzes(self, course_id: int) -> list[dict] | None:
        """Devuelve todos los 'Nuevos Quizzes' (Quizzes.Next) de un curso."""
        if not self.canvas: return None
        self.logger.info(f"Obteniendo 'Nuevos Quizzes' para el curso {course_id}.")
        url = f"/api/quiz/v1/courses/{course_id}/quizzes"
        try:
            response = requests.get(f"{self.canvas_url}{url}", headers=self._auth_headers(), timeout=30)
            response.raise_for_status()
            data = response.json()
            quiz_list = data if isinstance(data, list) else data.get("quizzes", [])
            self.logger.info(f"Se encontraron {len(quiz_list)} 'Nuevos Quizzes'.")
            return [{"id": q.get("id"), "title": q.get("title")} for q in quiz_list]
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                self.logger.warning(f"Endpoint de Nuevos Quizzes no encontrado para curso {course_id} (404). La funcionalidad puede no estar activa.")
                return []
            self.error_message = f"Error HTTP al obtener Nuevos Quizzes: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None
        except requests.exceptions.RequestException as e:
            self.error_message = f"Error de red al obtener Nuevos Quizzes: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None

    def create_quiz(self, course_id: int, quiz_settings: dict) -> bool:
        """Crea un quiz clásico en un curso."""
        if not self.canvas: return False
        self.logger.info(f"Creando quiz clásico en curso {course_id} con título: {quiz_settings.get('title')}")
        try:
            course = self.get_course(course_id)
            if not course: return False
            quiz = course.create_quiz(quiz=quiz_settings)
            self.logger.info(f"Quiz clásico '{quiz.title}' creado con ID {quiz.id}.")
            return True
        except Exception as e:
            self.error_message = f"Error al crear el quiz clásico: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return False

    def _create_new_quiz_base(self, course_id: int, quiz_settings: dict) -> dict | None:
        """[PRIVADO] Crea un 'Nuevo Quiz' base y devuelve sus datos."""
        if not self.canvas: return None
        url = f"{self.canvas_url}/api/quiz/v1/courses/{course_id}/quizzes"
        payload = {"quiz": quiz_settings}
        self.logger.info(f"Creando 'Nuevo Quiz' base en curso {course_id} con título: {quiz_settings.get('title')}")
        self.logger.debug(f"Payload para crear quiz: {json.dumps(payload)}")
        try:
            response = requests.post(url, headers=self._auth_headers(), json=payload, timeout=30)
            response.raise_for_status()
            quiz_data = response.json()
            self.logger.info(f"'Nuevo Quiz' base '{quiz_data.get('title')}' creado con ID {quiz_data.get('id')}.")
            return quiz_data
        except requests.exceptions.RequestException as e:
            self.error_message = f"Error de red al crear 'Nuevo Quiz': {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None

    def create_new_quiz_and_items(self, course_id: int, quiz_settings: dict, items: list) -> bool:
        """Crea un 'Nuevo Quiz' y le añade las preguntas (items) proporcionadas."""
        quiz_data = self._create_new_quiz_base(course_id, quiz_settings)
        if not quiz_data:
            return False

        quiz_id = quiz_data.get("id")
        if not quiz_id:
            self.error_message = "El quiz se creó pero no se pudo obtener su ID."
            self.logger.error(self.error_message)
            return False

        self.logger.info(f"Añadiendo {len(items)} preguntas al 'Nuevo Quiz' {quiz_id}.")

        item_url = f"{self.canvas_url}/api/quiz/v1/courses/{course_id}/quizzes/{quiz_id}/items"

        errors = []
        for i, question_entry_data in enumerate(items, 1):
            self.logger.debug(f"Creando pregunta {i}/{len(items)} para el quiz {quiz_id}.")
            try:
                # --- INICIO: Transformación del JSON simple al formato de la API de New Quizzes ---
                
                # 1. Generar UUIDs para cada opción de respuesta
                choices_with_ids = []
                for pos, choice_text in enumerate(question_entry_data.get("choices", [])):
                    choices_with_ids.append({
                        "id": str(uuid.uuid4()),
                        "position": pos + 1,
                        "itemBody": f"<p>{choice_text}</p>" # Canvas espera HTML
                    })

                # 2. Encontrar el ID de la respuesta correcta
                correct_letter = question_entry_data.get("correct", "").upper()
                correct_index = ord(correct_letter) - ord('A')
                correct_choice_id = None
                if 0 <= correct_index < len(choices_with_ids):
                    correct_choice_id = choices_with_ids[correct_index]["id"]

                # 3. Construir el objeto 'entry' que la API espera
                entry_payload = {
                    "interaction_type_slug": "choice", # Asumimos opción múltiple
                    "title": f"Pregunta {i}", # Título genérico para el item
                    "item_body": f"<p>{question_entry_data.get('question', '')}</p>",
                    "interaction_data": {
                        "choices": choices_with_ids
                    },
                    "scoring_data": {
                        "value": correct_choice_id # El ID de la respuesta correcta
                    },
                    "scoring_algorithm": "Equivalence"
                }

                # --- FIN: Transformación ---

                # 4. Construir el payload final para el item
                item_payload = {
                    "entry_type": "Item",
                    "position": i,
                    "entry": entry_payload # Usamos el payload transformado
                }

                # Mover 'points_possible' al nivel superior si existe en los datos de la pregunta
                if 'points' in question_entry_data:
                    item_payload['points_possible'] = question_entry_data.get('points')

                # El payload final debe estar envuelto en una clave "item"
                payload = {"item": item_payload}
                self.logger.debug(f"Payload para crear item: {json.dumps(payload)}")

                item_response = requests.post(item_url, headers=self._auth_headers(), json=payload, timeout=30)
                item_response.raise_for_status()

            except requests.exceptions.HTTPError as e:
                # Captura errores HTTP para dar un mensaje más claro
                error_detail = f"Error al añadir pregunta {i}: {e.response.status_code}"
                try:
                    # Intenta obtener el mensaje de error específico de la API de Canvas
                    error_detail += f" - {e.response.json().get('errors', [{}])[0].get('message', e.response.text)}"
                except (json.JSONDecodeError, IndexError, KeyError):
                    error_detail += f" - Response: {e.response.text}"
                errors.append(error_detail)
                self.logger.error(error_detail, exc_info=True)
            except requests.exceptions.RequestException as e:
                error_detail = f"Error al añadir pregunta {i}: {e}"
                errors.append(error_detail)
                self.logger.error(error_detail, exc_info=True)

        if errors:
            self.error_message = f"El quiz se creó, pero hubo errores al añadir preguntas: {'; '.join(errors)}"
            return False

        self.logger.info(f"Todas las {len(items)} preguntas se añadieron correctamente al quiz {quiz_id}.")
        return True

    def grade_submission_with_rubric(self, course_id: int, assignment_id: int, user_id: int, rubric_assessment_data: dict, comment: str = None) -> bool:
        """
        Califica la entrega de un estudiante usando los datos de una rúbrica y añade un comentario opcional.
        """
        logger.info(f"Intentando calificar la entrega para user_id {user_id} en assignment_id {assignment_id}.")
        if not self.canvas: return False

        try:
            # Usamos los métodos existentes para obtener los objetos de Canvas
            course = self.get_course(course_id)
            if not course: return False
            
            assignment = course.get_assignment(assignment_id)
            submission = assignment.get_submission(user_id)

            # Preparamos el payload que enviaremos a la API
            edit_payload = {
                'rubric_assessment': rubric_assessment_data
            }
            if comment:
                edit_payload['comment'] = {'text_comment': comment}

            logger.debug(f"Enviando payload de calificación para user_id {user_id}: {json.dumps(edit_payload)}")
            
            # Esta es la llamada clave que actualiza la nota en Canvas
            submission.edit(**edit_payload)
            
            logger.info(f"Entrega para user_id {user_id} calificada con éxito.")
            return True
        except Exception as e:
            self.error_message = f"Error al calificar la entrega para user_id {user_id}: {e}"
            logger.error(self.error_message, exc_info=True)
            return False

    # --------------------------------------------------------------------- #
    # 4. Rúbricas
    # --------------------------------------------------------------------- #
    def get_rubrics(self, course_id: int) -> list[dict] | None:
        if not self.canvas: return None
        self.logger.info(f"Obteniendo rúbricas para el curso {course_id}.")
        try:
            course = self.get_course(course_id)
            if not course: return None
            rubrics = list(course.get_rubrics())
            self.logger.info(f"Se encontraron {len(rubrics)} rúbricas.")
            return [
                {"id": r.id, "title": r.title, "points_possible": r.points_possible}
                for r in rubrics
            ]
        except Exception as e:
            self.error_message = f"Error al listar rúbricas: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return None

    def create_rubric(self, course_id: int, title: str, criteria: list, opts: dict = None) -> bool:
        """Crea una rúbrica en un curso, opcionalmente asociada a una actividad."""
        if not self.canvas: return False
        opts = opts or {}
        logger.info(f"Creando rúbrica '{title}' en el curso {course_id}.")

        try:
            course = self.get_course(course_id)
            if not course: return False

            # La API de Canvas espera un diccionario indexado para los criterios y ratings.
            indexed_criteria = {}
            for i, crit_orig in enumerate(criteria):
                crit = {}
                crit_id = crit_orig.get('id') or f'crit_{i}'
                
                crit['id'] = crit_id
                crit['description'] = crit_orig.get('description') or ''
                crit['long_description'] = crit_orig.get('long_description') or ''
                crit['points'] = float(crit_orig.get('points') or 0.0)
                crit['criterion_use_range'] = crit_orig.get('criterion_use_range', False)
                crit['ignore_for_scoring'] = crit_orig.get('ignore_for_scoring', False)

                if 'ratings' in crit_orig and crit_orig['ratings'] is not None:
                    indexed_ratings = {}
                    for j, rating_orig in enumerate(crit_orig['ratings']):
                        rating = {}
                        rating['id'] = rating_orig.get('id') or f'rating_{i}_{j}'
                        rating['criterion_id'] = crit_id
                        rating['description'] = rating_orig.get('description') or ''
                        rating['long_description'] = rating_orig.get('long_description') or ''
                        rating['points'] = float(rating_orig.get('points') or 0.0)
                        indexed_ratings[j] = rating
                    crit['ratings'] = indexed_ratings
                
                indexed_criteria[i] = crit

            rubric_data = {
                'title': title,
                'free_form_criterion_comments': opts.get('free_form_criterion_comments', True),
                'criteria': indexed_criteria
            }

            rubric_association_data = {}
            if opts.get('assignment_id'):
                rubric_association_data['association_id'] = opts['assignment_id']
                rubric_association_data['association_type'] = 'Assignment'
                rubric_association_data['purpose'] = 'grading'
                rubric_association_data['use_for_grading'] = True
            else:
                rubric_association_data['association_id'] = course_id
                rubric_association_data['association_type'] = 'Course'
                rubric_association_data['purpose'] = 'bookmark'

            if 'hide_score_total' in opts:
                rubric_association_data['hide_score_total'] = opts['hide_score_total']

            logger.debug(f"Payload de la rúbrica: {json.dumps(rubric_data)}")
            logger.debug(f"Payload de la asociación de rúbrica: {json.dumps(rubric_association_data)}")

            response_data = course.create_rubric(
                rubric=rubric_data, 
                rubric_association=rubric_association_data
            )

            # Normaliza la respuesta: puede venir como objeto Rubric, o como dict {"rubric": Rubric|dict, ...}
            rubric_part = None
            if isinstance(response_data, dict):
                rubric_part = response_data.get("rubric")
            else:
                rubric_part = response_data  # ya es un objeto Rubric

            # Extrae título e ID de forma segura, independientemente del tipo
            if hasattr(rubric_part, 'title') and hasattr(rubric_part, 'id'):
                title = rubric_part.title
                rubric_id = rubric_part.id
                logger.info(f"Rúbrica '{title}' creada con ID {rubric_id}.")
            elif isinstance(rubric_part, dict):
                title = rubric_part.get("title", "Sin Título")
                rubric_id = rubric_part.get("id")
                if rubric_id:
                    logger.info(f"Rúbrica '{title}' creada con ID {rubric_id}.")
                else:
                    logger.warning(f"Rúbrica creada, pero no se pudo determinar el ID. Respuesta: {response_data}")
            else:
                logger.warning(f"Rúbrica creada, pero la respuesta tuvo un formato inesperado: {response_data}")

            return True

        except CanvasException as e:
            try:
                message = str(e)
                if hasattr(e, 'response') and e.response.status_code != 500:
                    message = e.response.json().get('errors', str(e))
            except (AttributeError, ValueError, KeyError):
                message = str(e)
            self.error_message = f"Error de la API de Canvas al crear la rúbrica: {message}"
            logger.error(self.error_message, exc_info=True)
            return False
        except Exception as e:
            self.error_message = f"Error inesperado al crear la rúbrica: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return False

    def export_rubric_to_json(self, course_id: int, rubric_id: int, out_path: Path) -> bool:
        """Descarga una rúbrica y la guarda en formato JSON."""
        self.logger.info(f"Exportando rúbrica {rubric_id} a JSON en '{out_path}'")
        url = f"{self.canvas_url}/api/v1/courses/{course_id}/rubrics/{rubric_id}"
        params = {"include[]": "assessments"}
        try:
            response = requests.get(url, headers=self._auth_headers(), params=params, timeout=30)
            response.raise_for_status()
            rubric_data = response.json()

            with out_path.open("w", encoding="utf-8") as f:
                json.dump(rubric_data, f, ensure_ascii=False, indent=4)

            self.logger.info(f"Rúbrica exportada a JSON con éxito: {out_path}")
            return True
        except requests.exceptions.RequestException as e:
            self.error_message = f"Error de red al exportar rúbrica {rubric_id} a JSON: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return False
        except IOError as e:
            self.error_message = f"Error de escritura al guardar JSON de rúbrica en '{out_path}': {e}"
            self.logger.error(self.error_message, exc_info=True)
            return False

    def export_rubric_to_csv(self, course_id: int, rubric_id: int, out_path: Path) -> bool:
        """Descarga una rúbrica y la guarda en formato CSV compatible con Canvas."""
        self.logger.info(f"Exportando rúbrica {rubric_id} a CSV en '{out_path}'")
        try:
            course = self.get_course(course_id)
            if course is None: return False
            rubric = course.get_rubric(rubric_id)

            def get_attr(obj, key, default=""):
                return getattr(obj, key, default) if hasattr(obj, key) else obj.get(key, default)

            max_ratings = max(len(get_attr(c, "ratings", [])) for c in rubric.data)
            headers = ["Rubric Name", "Criteria Name", "Criteria Description", "Criteria Points"]
            for i in range(max_ratings):
                headers.extend([f"Rating {i+1} Name", f"Rating {i+1} Description", f"Rating {i+1} Points"])

            with out_path.open("w", newline="", encoding="utf-8-sig") as f:
                writer = csv.writer(f)
                writer.writerow(headers)
                for c in rubric.data:
                    row = [
                        rubric.title,
                        get_attr(c, "description"),
                        get_attr(c, "long_description"),
                        get_attr(c, "points"),
                    ]
                    for r in get_attr(c, "ratings", []):
                        row.extend([get_attr(r, "description"), get_attr(r, "long_description"), get_attr(r, "points")])
                    writer.writerow(row)

            self.logger.info(f"Rúbrica exportada a CSV con éxito: {out_path}")
            return True
        except Exception as e:
            self.error_message = f"No se pudo exportar la rúbrica {rubric_id} a CSV: {e}"
            self.logger.error(self.error_message, exc_info=True)
            return False
