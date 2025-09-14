# app/gui/activities_menu.py

import customtkinter as ctk
from tkinter import messagebox, filedialog
import logging
from app.utils.event_logger import log_action
from pathlib import Path
import os
import threading
import urllib.parse
import json
import queue
import csv
import concurrent.futures
import random
import time

try:
    import google.generativeai as genai
except ImportError:
    genai = None

import re

# Usar un logger específico para este módulo
logger = logging.getLogger(__name__)

class RateController:
    """Controlador para limitar QPS y gestionar la concurrencia de forma adaptativa."""
    def __init__(self, max_qps: float = 1.5, max_workers: int = 8):
        self.tokens = 0.0
        self.rate = max_qps
        self.capacity = max(1.0, max_qps * 2.0)
        self.lock = threading.Lock()
        self.last = time.monotonic()
        self.max_workers = max_workers
        self._current_workers = max_workers

    def leak_and_refill(self):
        now = time.monotonic()
        with self.lock:
            elapsed = max(0.0, now - self.last)
            self.last = now
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)

    def acquire(self):
        while True:
            self.leak_and_refill()
            with self.lock:
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    return
            time.sleep(0.05)

    def downgrade_workers(self):
        with self.lock:
            if self._current_workers > 1:
                self._current_workers = max(1, self._current_workers // 2)
        logger.info(f"Concurrencia de la API reducida a {self._current_workers} workers.")
        return self._current_workers

    def current_workers(self):
        with self.lock:
            return self._current_workers

def _call_with_backoff_and_rate(controller: RateController, fn, *args, **kwargs):
    """Envuelve una llamada a la IA respetando QPS."""
    controller.acquire()
    return fn(*args, **kwargs)

SUBMISSION_TYPES = {
    "online_upload": "Subir archivo",
    "online_text_entry": "Entrada de texto",
    "online_url": "URL de un sitio web",
}

class ActivitiesMenu(ctk.CTkFrame):
    def __init__(self, parent, client, gemini_evaluator, course_id, main_window):
        super().__init__(parent)
        self.client = client
        self.gemini_evaluator = gemini_evaluator
        self.course_id = course_id
        self.main_window = main_window
        self.submission_checkboxes = {}
        self.assignments = {}
        self.assignment_buttons = {}
        self.selected_assignment_id = None
        self.active_thread = None
        self.queue = queue.Queue()
        self.cancel_event = threading.Event()
        self.stop_polling = False

        logger.debug("Inicializando ActivitiesMenu.")

        back_button = ctk.CTkButton(self, text="< Volver al Menú Principal", command=self.main_window.show_main_menu)
        back_button.pack(anchor="nw", padx=10, pady=10)

        container = ctk.CTkFrame(self)
        container.pack(expand=True, fill="both", padx=10, pady=(0, 10))

        self.tab_view = ctk.CTkTabview(container, anchor="w")
        self.tab_view.pack(expand=True, fill="both")

        self.tab_view.add("Crear Actividad")
        self.tab_view.add("Descargar Entregas")
        self.setup_activity_tab()
        self.setup_download_tab()

    def setup_activity_tab(self):
        activity_tab = self.tab_view.tab("Crear Actividad")
        activity_tab.grid_columnconfigure(1, weight=1)

        # --- Nombre y Puntos ---
        name_label = ctk.CTkLabel(activity_tab, text="Nombre de la Actividad:")
        name_label.grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        self.activity_name_entry = ctk.CTkEntry(activity_tab)
        self.activity_name_entry.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="ew")

        points_label = ctk.CTkLabel(activity_tab, text="Puntos Posibles:")
        points_label.grid(row=1, column=0, padx=20, pady=10, sticky="w")
        self.activity_points_entry = ctk.CTkEntry(activity_tab)
        self.activity_points_entry.grid(row=1, column=1, padx=20, pady=10, sticky="w")

        # --- Tipos de Entrega (Dinámico) ---
        submission_label = ctk.CTkLabel(activity_tab, text="Tipos de Entrega Online:")
        submission_label.grid(row=2, column=0, padx=20, pady=10, sticky="nw")
        submission_frame = ctk.CTkFrame(activity_tab)
        submission_frame.grid(row=2, column=1, padx=20, pady=10, sticky="w")

        for key, text in SUBMISSION_TYPES.items():
            var = ctk.StringVar(value="0")
            chk = ctk.CTkCheckBox(submission_frame, text=f"{text} ({key})", variable=var, onvalue="1", offvalue="0")
            chk.pack(anchor="w", padx=10, pady=5)
            self.submission_checkboxes[key] = var

        # --- Descripción y Botón ---
        desc_label = ctk.CTkLabel(activity_tab, text="Descripción:")
        desc_label.grid(row=3, column=0, padx=20, pady=10, sticky="nw")
        self.activity_desc_textbox = ctk.CTkTextbox(activity_tab, height=150)
        self.activity_desc_textbox.grid(row=3, column=1, padx=20, pady=10, sticky="nsew")
        activity_tab.grid_rowconfigure(3, weight=1)

        create_button = ctk.CTkButton(activity_tab, text="Crear Actividad", command=self.handle_create_activity)
        create_button.grid(row=4, column=1, padx=20, pady=20, sticky="e")

    def setup_download_tab(self):
        download_tab = self.tab_view.tab("Descargar Entregas")
        download_tab.grid_columnconfigure(0, weight=1)
        download_tab.grid_rowconfigure(1, weight=1)

        info_frame = ctk.CTkFrame(download_tab)
        info_frame.grid(row=0, column=0, sticky="ew", padx=10, pady=10)
        info_frame.grid_columnconfigure(0, weight=1)

        self.selected_assignment_label = ctk.CTkLabel(info_frame, text="Selecciona una actividad de la lista para ver detalles y descargar.", anchor="w")
        self.selected_assignment_label.grid(row=0, column=0, padx=10, pady=5, sticky="ew")

        actions_frame = ctk.CTkFrame(info_frame, fg_color="transparent")
        actions_frame.grid(row=1, column=0, sticky="ew", pady=(5,0))
        actions_frame.grid_columnconfigure(3, weight=1)

        self.download_button = ctk.CTkButton(actions_frame, text="Descargar Entregas", state="disabled", command=self._prompt_download_location)
        self.download_button.pack(side="left", padx=10)

        self.evaluate_button = ctk.CTkButton(actions_frame, text="Evaluar con IA", state="disabled", command=self._start_evaluation_thread)
        self.evaluate_button.pack(side="left", padx=10)

        self.model_selector_label = ctk.CTkLabel(actions_frame, text="Modelo:")
        self.model_selector_label.pack(side="left", padx=(10, 0))

        self.model_selector = ctk.CTkOptionMenu(actions_frame, values=["Cargando..."])
        self.model_selector.pack(side="left", padx=5)
        self._populate_model_selector()

        self.cancel_button = ctk.CTkButton(actions_frame, text="Cancelar", state="disabled", command=self._cancel_running_task, fg_color="firebrick", hover_color="darkred")
        self.cancel_button.pack(side="right", padx=10)

        self.assignments_frame = ctk.CTkScrollableFrame(download_tab, label_text="Actividades del Curso")
        self.assignments_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        self.assignments_frame.grid_columnconfigure(0, weight=1)

        self.loading_label = ctk.CTkLabel(self.assignments_frame, text="Cargando, por favor espera...")
        self.loading_label.pack(pady=20)

        threading.Thread(target=self._load_assignments, daemon=True).start()

    def _populate_model_selector(self):
        logger.debug("Poblando el selector de modelos de IA.")
        if not self.gemini_evaluator:
            self.model_selector.configure(values=["Evaluador no disp."], state="disabled")
            return
        try:
            models, default_model = self.gemini_evaluator.list_evaluation_models()
            if models:
                self.model_selector.configure(values=models, state="normal")
                self.model_selector.set(default_model)
                logger.info(f"Selector de modelos poblado. Por defecto: {default_model}")
            else:
                self.model_selector.configure(values=["No hay modelos"], state="disabled")
                logger.warning("No se encontraron modelos de evaluación en el cliente de Gemini.")
        except Exception as e:
            logger.error(f"No se pudieron cargar los modelos de Gemini: {e}", exc_info=True)
            self.model_selector.configure(values=["Error"], state="disabled")

    def _load_assignments(self):
        """Carga las actividades en un hilo secundario."""
        logger.info("Iniciando carga de actividades del curso.")
        self.after(0, self.main_window.update_status, "Cargando lista de actividades...")
        try:
            assignment_groups = self.client.get_assignment_groups_with_assignments(self.course_id)
            self.after(0, self._populate_assignments_list, assignment_groups)
            self.after(0, self.main_window.update_status, "Listo", 3000)
            logger.info("Carga de actividades completada.")
        except Exception as e:
            error_msg = f"No se pudieron cargar las actividades: {e}"
            logger.error(error_msg, exc_info=True)
            self.after(0, self.main_window.update_status, "Error al cargar actividades.", 5000)
            self.after(0, messagebox.showerror, "Error", error_msg)
            self.after(0, self.loading_label.configure, {"text": "Error al cargar."})

    def _populate_assignments_list(self, assignment_groups):
        """Puebla la lista de actividades en el hilo principal."""
        self.loading_label.pack_forget() # Ocultar el mensaje de "cargando"

        if not assignment_groups:
            no_groups_label = ctk.CTkLabel(self.assignments_frame, text="No se encontraron grupos de actividades.")
            no_groups_label.pack(pady=10)
            return

        for group in assignment_groups:
            group_label = ctk.CTkLabel(
                self.assignments_frame,
                text=group['name'],
                font=ctk.CTkFont(size=14, weight="bold"),
                anchor="w"
            )
            group_label.pack(fill="x", padx=5, pady=(10, 5))

            assignments_in_group = group.get('assignments', [])
            if not assignments_in_group:
                no_assign_label = ctk.CTkLabel(
                    self.assignments_frame,
                    text=" (Sin actividades en este grupo)",
                    font=ctk.CTkFont(size=11, slant="italic"),
                    anchor="w"
                )
                no_assign_label.pack(fill="x", padx=20, pady=(0, 5))

            for assignment in assignments_in_group:
                assignment_id = assignment['id']
                self.assignments[assignment_id] = assignment
                btn = ctk.CTkButton(
                    self.assignments_frame,
                    text=assignment['name'],
                    command=lambda a_id=assignment_id: self._select_assignment(a_id)
                )
                btn.pack(fill="x", padx=(20, 5), pady=2)
                self.assignment_buttons[assignment_id] = btn

    def _enable_assignment_buttons(self, enable=True):
        """Helper para (des)activar los botones de actividad en el hilo principal."""
        state = "normal" if enable else "disabled"
        for btn in self.assignment_buttons.values():
            btn.configure(state=state)
        self.download_button.configure(state="disabled")
        self.evaluate_button.configure(state="disabled")
        self.cancel_button.configure(state="disabled")
        self.model_selector.configure(state="disabled")

    def _select_assignment(self, assignment_id):
        if self.active_thread and self.active_thread.is_alive():
            logger.warning("Se intentó seleccionar una actividad mientras un proceso estaba en curso.")
            messagebox.showwarning("Proceso en curso", "Espera a que termine el proceso actual.")
            return

        self.selected_assignment_id = assignment_id
        assignment_name = self.assignments[assignment_id]["name"]
        logger.info(f"Actividad seleccionada: '{assignment_name}' (ID: {assignment_id}).")
        self.selected_assignment_label.configure(text=f"Actividad seleccionada: {assignment_name}")
        
        self.main_window.update_status("Obteniendo resumen de entregas...")
        self.main_window.show_progress_bar(indeterminate=True)
        self._enable_assignment_buttons(False)

        self.active_thread = threading.Thread(target=self._fetch_and_display_summary, args=(assignment_id,))
        self.active_thread.start()

    def _fetch_and_display_summary(self, assignment_id):
        """Obtiene el resumen de la actividad y actualiza la UI."""
        logger.info(f"Obteniendo resumen para la actividad {assignment_id}.")
        try:
            summary = self.client.get_assignment_submission_summary(self.course_id, assignment_id)
            if not summary:
                raise Exception(self.client.error_message or "La API no devolvió un resumen.")

            self.assignments[assignment_id]['summary'] = summary
            self.after(0, self._update_ui_with_summary, assignment_id, summary)

        except Exception as e:
            error_msg = f"Error al obtener resumen de la actividad {assignment_id}: {e}"
            logger.error(error_msg, exc_info=True)
            self._on_task_error(error_msg)

    def _update_ui_with_summary(self, assignment_id, summary):
        self.main_window.hide_progress_bar()
        self._enable_assignment_buttons(True)
        assignment_name = self.assignments[assignment_id]["name"]
        info_message = (
            f"Actividad: {assignment_name}\n\n"
            f"• Total de entregas: {summary['submission_count']}\n"
            f"• Entregas con PDF (aprox): {summary['pdf_submission_count']}\n"
            f"• Tiene rúbrica asociada: {'Sí' if summary['has_rubric'] else 'No'}"
        )
        self.selected_assignment_label.configure(text=info_message)
        self.main_window.update_status("Resumen cargado. Selecciona una acción.", 5000)
        self._update_action_buttons(summary)

    def _update_action_buttons(self, summary: dict):
        """Actualiza el estado de los botones de acción basado en el resumen."""
        self.download_button.configure(state="normal")
        
        if summary.get("has_rubric") and self.gemini_evaluator:
            self.evaluate_button.configure(state="normal")
            self.model_selector.configure(state="normal")
        else:
            self.evaluate_button.configure(state="disabled")
            self.model_selector.configure(state="disabled")
            if not self.gemini_evaluator:
                self.main_window.update_status("Evaluación no disponible: Módulo Gemini no cargado.", 5000)
            elif not summary.get("has_rubric"):
                 self.main_window.update_status("Evaluación no disponible: La actividad no tiene rúbrica.", 5000)

    @log_action
    def _prompt_download_location(self):
        """Pide al usuario una carpeta y luego inicia la descarga."""
        if not self.selected_assignment_id: return

        base_dir = filedialog.askdirectory(title="Selecciona la carpeta base para las descargas")
        if not base_dir:
            self.main_window.update_status("Descarga cancelada.", clear_after_ms=4000)
            return

        self._start_download_thread(self.selected_assignment_id, base_dir)

    def _start_download_thread(self, assignment_id, base_dir):
        """Inicia el proceso de descarga de archivos en un nuevo hilo."""
        logger.info(f"Iniciando hilo de descarga para actividad {assignment_id}.")
        self.main_window.update_status("Iniciando descarga...")
        self.main_window.show_progress_bar()
        self._enable_assignment_buttons(False)
        self.cancel_button.configure(state="normal")

        self.active_thread = threading.Thread(
            target=self._handle_download_submissions, args=(assignment_id, base_dir),
            daemon=True
        )
        self.active_thread.start()
        self.stop_polling = False
        self._process_queue()

    @log_action
    def _start_evaluation_thread(self):
        if not self.selected_assignment_id: return
        
        base_dir = filedialog.askdirectory(title="Selecciona la carpeta base para las descargas y evaluaciones")
        if not base_dir:
            logger.info("El usuario canceló la selección de carpeta para la evaluación.")
            self.main_window.update_status("Evaluación cancelada.", 4000)
            return

        while not self.queue.empty(): self.queue.get_nowait()

        model_name = self.model_selector.get()
        logger.info(f"Iniciando hilo de evaluación para actividad {self.selected_assignment_id} con modelo '{model_name}'.")

        self.main_window.update_status("Iniciando evaluación con IA...")
        self.main_window.show_progress_bar()
        self._enable_assignment_buttons(False)
        self.cancel_button.configure(state="normal")

        self.active_thread = threading.Thread(
            target=self._handle_evaluation, 
            args=(self.selected_assignment_id, base_dir, model_name),
            daemon=True
        )
        self.active_thread.start()
        self.stop_polling = False
        self._process_queue()

    def _cancel_running_task(self):
        if self.active_thread and self.active_thread.is_alive():
            logger.info("Solicitud de cancelación de proceso recibida.")
            self.cancel_event.set()
            self.cancel_button.configure(state="disabled", text="Cancelando...")

    def _process_queue(self):
        """Procesa mensajes de la cola para actualizar la GUI de forma segura."""
        if self.stop_polling:
            return
        try:
            while not self.queue.empty():
                message_type, data = self.queue.get_nowait()

                if message_type == "update_status":
                    self.main_window.update_status(data[0], data[1] if len(data) > 1 else 0)
                elif message_type == "update_progress":
                    self.main_window.update_progress(data)
                elif message_type == "show_progress_bar":
                    self.main_window.show_progress_bar(**data)
                elif message_type == "hide_progress_bar":
                    self.main_window.hide_progress_bar()
                elif message_type == "task_success":
                    self._on_task_success(data)
                elif message_type == "task_error":
                    self._on_task_error(data)
                elif message_type == "task_finished":
                    self.stop_polling = True
                    self._enable_assignment_buttons(True)
                    self.cancel_button.configure(state="disabled", text="Cancelar")
                    self.cancel_event.clear()
                    self.main_window.update_status("Proceso finalizado.", 5000)

        except queue.Empty:
            pass
        finally:
            if not self.stop_polling:
                self.after(100, self._process_queue)

    def _handle_download_submissions(self, assignment_id, base_dir):
        """Maneja la lógica de descarga en un hilo separado para no bloquear la UI."""
        try:
            assignment = self.assignments[assignment_id]
            summary = assignment['summary']
            activity_path = self._setup_activity_folder(base_dir, assignment_id, assignment['name'])

            self.queue.put(("update_status", ("Obteniendo lista completa de entregas...",)))
            submissions = self.client.get_all_submissions(self.course_id, assignment_id)
            if not submissions:
                self.queue.put(("update_status", ("No se encontraron entregas para esta actividad.", 5000)))
                self.queue.put(("task_success", "No se encontraron entregas para descargar."))
                return

            downloaded_files, error_count = self._download_all_attachments(submissions, activity_path)

            if summary.get("has_rubric") and summary.get("rubric_id"):
                self._export_rubric(activity_path, assignment['name'], summary["rubric_id"])

            final_message = f"Descarga completada.\n\nArchivos descargados: {downloaded_files}\nErrores: {error_count}"
            if summary.get("has_rubric"):
                final_message += "\nLa rúbrica asociada ha sido guardada en formato JSON y CSV."
            self.queue.put(("task_success", final_message))

        except InterruptedError as e:
            logger.info(str(e))
            self.queue.put(("update_status", (str(e), 5000)))
        except Exception as e:
            error_msg = f"Ocurrió un error durante la descarga: {e}"
            logger.error(error_msg, exc_info=True)
            self.queue.put(("task_error", error_msg))
        finally:
            self.queue.put(("task_finished", None))

    def _handle_evaluation(self, assignment_id: int, base_dir: str, model_name: str):
        """Lógica de evaluación con Gemini que se ejecuta en un hilo."""
        uploaded_files = {}
        try:
            assignment = self.assignments[assignment_id]
            summary = assignment['summary']
            activity_path = self._setup_activity_folder(base_dir, assignment_id, assignment['name'])
            
            results_cache_path = activity_path / "evaluaciones_cache.json"
            results_cache = self._load_json_cache(results_cache_path)

            rubric_path = activity_path / f"rubrica_{assignment_id}.json"
            self._export_rubric(activity_path, assignment['name'], summary["rubric_id"])
            with open(rubric_path, 'r', encoding='utf-8') as f: rubric_json = json.load(f)

            submissions = self.client.get_all_submissions(self.course_id, assignment_id)

            self._prepare_submission_files(submissions, activity_path, uploaded_files)
            if self.cancel_event.is_set(): raise InterruptedError("Proceso cancelado por el usuario.")

            evaluations = self._run_evaluations_in_parallel(uploaded_files, results_cache, rubric_json, model_name)
            if self.cancel_event.is_set(): raise InterruptedError("Proceso cancelado por el usuario.")

            self.queue.put(("update_status", ("Guardando resultados...",)))
            self._save_evaluations_to_csv(evaluations, activity_path / "evaluaciones_gemini.csv", rubric_json)
            self._save_json_cache(results_cache_path, results_cache)
            
            final_message = f"Se han evaluado {len(evaluations)} entregas con PDF.\nEl resultado se ha guardado en 'evaluaciones_gemini.csv' en la carpeta de la actividad."
            self.queue.put(("task_success", final_message))

        except InterruptedError as e:
            logger.info(str(e))
            self.queue.put(("update_status", (str(e), 5000)))
        except Exception as e:
            error_msg = f"Ocurrió un error durante la evaluación: {e}"
            logger.error(error_msg, exc_info=True)
            self.queue.put(("task_error", error_msg))
        finally:
            self._cleanup_gemini_files(list(uploaded_files.values()))
            self.queue.put(("task_finished", None))

    def _on_task_success(self, message: str):
        self.main_window.hide_progress_bar()
        messagebox.showinfo("Proceso Completado", message)

    def _on_task_error(self, error_msg: str):
        """Maneja errores de hilos en la GUI."""
        self.main_window.hide_progress_bar()
        self.cancel_event.clear()
        messagebox.showerror("Error en el Proceso", error_msg)

    def _setup_activity_folder(self, base_dir: str, assignment_id: int, assignment_name: str) -> Path:
        course = self.client.get_course(self.course_id)
        course_abbreviation = self._create_abbreviation(course.name)
        assignment_abbreviation = self._create_abbreviation(assignment_name)
        activity_path = Path(base_dir) / f"{self.course_id} - {course_abbreviation}" / f"{assignment_id} - {assignment_abbreviation}"
        activity_path.mkdir(parents=True, exist_ok=True)
        logger.info(f"Carpeta de la actividad preparada en: {activity_path}")
        return activity_path

    def _download_all_attachments(self, submissions: list, activity_path: Path) -> (int, int):
        downloaded_files = 0
        error_count = 0
        total_submissions = len(submissions)
        for i, sub in enumerate(submissions):
            if self.cancel_event.is_set(): raise InterruptedError("Descarga cancelada.")
            progress = (i + 1) / total_submissions
            student_name = self._sanitize_filename(sub.get("user", {}).get("name", "sin_nombre"))
            self.queue.put(("update_status", (f"Procesando {i+1}/{total_submissions}: {student_name}",)))
            self.queue.put(("update_progress", progress))

            attachments = sub.get("attachments", [])
            if sub.get("submission_history"):
                for history_item in sub.get("submission_history", []):
                    attachments.extend(history_item.get("attachments", []))
            attachments = [dict(t) for t in {tuple(d.items()) for d in attachments}] # Deduplicar

            if not attachments:
                logger.warning(f"Sin adjuntos para {student_name} en la entrega {sub.get('id')}")
                continue

            for att in attachments:
                student_folder = activity_path / student_name
                filename = self._sanitize_filename(att["filename"], decode_url=True)
                self.queue.put(("update_status", (f"Descargando '{filename}' ({i+1}/{total_submissions})",)))
                if self.client.download_file(att["url"], student_folder, filename):
                    downloaded_files += 1
                else:
                    error_count += 1
        return downloaded_files, error_count

    def _export_rubric(self, activity_path: Path, assignment_name: str, rubric_id: int):
        self.queue.put(("update_status", ("Descargando rúbrica asociada...",)))
        rubric_base_name = f"rubrica_{self._create_abbreviation(assignment_name)}"
        self.client.export_rubric_to_json(self.course_id, rubric_id, activity_path / f"{rubric_base_name}.json")
        self.client.export_rubric_to_csv(self.course_id, rubric_id, activity_path / f"{rubric_base_name}.csv")

    def _load_json_cache(self, cache_path: Path) -> dict:
        if cache_path.exists():
            try:
                with open(cache_path, "r", encoding="utf-8") as f:
                    return json.load(f)
            except (FileNotFoundError, json.JSONDecodeError) as e:
                logger.warning(f"No se pudo cargar el caché de resultados desde {cache_path}: {e}")
        return {}

    def _save_json_cache(self, cache_path: Path, cache_data: dict):
        try:
            with open(cache_path, "w", encoding="utf-8") as f:
                json.dump(cache_data, f, indent=2)
        except IOError as e:
            logger.error(f"No se pudo guardar el caché de resultados en {cache_path}: {e}")

    def _prepare_submission_files(self, submissions: list, activity_path: Path, uploaded_files: dict):
        total_submissions = len(submissions)
        self.queue.put(("update_progress", 0))
        for i, sub in enumerate(submissions):
            if self.cancel_event.is_set(): break
            progress = (i + 1) / total_submissions
            student_name = self._sanitize_filename(sub.get("user", {}).get("name", "sin_nombre"))
            self.queue.put(("update_status", (f"Preparando a {student_name} ({i+1}/{total_submissions})",)))
            self.queue.put(("update_progress", progress))

            all_attachments = sub.get("attachments", [])
            if sub.get("submission_history"):
                for history_item in sub["submission_history"]:
                    all_attachments.extend(history_item.get("attachments", []))

            pdf_attachment = next((att for att in all_attachments if att.get("filename", "").lower().endswith(".pdf")), None)
            if not pdf_attachment:
                logger.warning(f"Sin PDF para {student_name}, saltando evaluación.")
                continue

            pdf_path = activity_path / student_name / self._sanitize_filename(pdf_attachment["filename"], decode_url=True)
            if not pdf_path.exists():
                self.client.download_file(pdf_attachment["url"], pdf_path.parent, pdf_path.name)

            if pdf_path.exists():
                gemini_file = self.gemini_evaluator.upload_or_get_cached(str(pdf_path))
                file_sha = self.gemini_evaluator._hash_file(str(pdf_path))
                uploaded_files[student_name] = {"file": gemini_file, "sha": file_sha, "path": str(pdf_path)}

    def _run_evaluations_in_parallel(self, uploaded_files: dict, results_cache: dict, rubric_json: dict, model_name: str) -> list:
        evaluations = []
        items_to_evaluate = []
        for student_name, data in uploaded_files.items():
            if data["sha"] in results_cache:
                cached_result = results_cache[data["sha"]].copy()
                cached_result['alumno'] = student_name
                evaluations.append(cached_result)
                logger.info(f"Resultado para {student_name} (SHA: {data['sha'][:8]}...) encontrado en caché.")
            else:
                items_to_evaluate.append((student_name, data))

        if not items_to_evaluate:
            self.queue.put(("update_status", ("Todos los resultados ya estaban en caché.", 3000)))
            return evaluations

        self.queue.put(("show_progress_bar", {"indeterminate": True}))
        controller = RateController(max_workers=8)

        def _one_eval(student_name, data):
            contents = self.gemini_evaluator.prepare_pdf_evaluation_request(data["file"].name, rubric_json)
            return _call_with_backoff_and_rate(controller, self.gemini_evaluator.execute_single_request, contents, model_name=model_name)

        with concurrent.futures.ThreadPoolExecutor(max_workers=controller.max_workers) as executor:
            future_to_student = {executor.submit(_one_eval, name, data): (name, data) for name, data in items_to_evaluate}

            for future in concurrent.futures.as_completed(future_to_student):
                if self.cancel_event.is_set(): break
                student_name, data = future_to_student[future]
                try:
                    result_json = future.result()
                    if "error" in result_json:
                        logger.error(f"Error en la respuesta de la IA para {student_name}: {result_json['error']}")
                    else:
                        result_json['alumno'] = student_name
                        evaluations.append(result_json)
                        results_cache[data["sha"]] = {k: v for k, v in result_json.items() if k != 'alumno'}
                except Exception as e:
                    logger.error(f"Error en la evaluación de {student_name}: {e}", exc_info=True)
                    if "429" in str(e).lower(): controller.downgrade_workers()
                finally:
                    progress = len(evaluations) / len(uploaded_files)
                    self.queue.put(("update_status", (f"Procesando resultados ({len(evaluations)}/{len(uploaded_files)})",)))
                    self.queue.put(("update_progress", progress))
        return evaluations

    def _cleanup_gemini_files(self, uploaded_file_data: list):
        delete_remote_files = False # Podría ser una opción de la UI
        if not delete_remote_files: return

        self.queue.put(("update_status", ("Limpiando archivos temporales de la API...",)))
        for data in uploaded_file_data:
            try:
                file_name = data.get("file").name
                logger.info(f"Eliminando archivo remoto de Gemini: {file_name}")
                genai.delete_file(file_name)
            except Exception as e:
                logger.error(f"No se pudo eliminar el archivo remoto {data.get('file').name}: {e}")

    def _save_evaluations_to_csv(self, evaluations: list, csv_path: Path, rubric_json: dict):
        if not evaluations: return
        # ... (implementación sin cambios)
        pass

    def _create_abbreviation(self, text: str) -> str:
        # ... (implementación sin cambios)
        pass

    def _sanitize_filename(self, name, decode_url=False):
        # ... (implementación sin cambios)
        pass

    @log_action
    def handle_create_activity(self):
        # ... (implementación sin cambios)
        pass
