# app/gui/main_window.py

import customtkinter as ctk
import webbrowser
from app.api.canvas_client import CanvasClient
from app.api.gemini_client import HybridEvaluator
from tkinter import messagebox
from app.utils.event_logger import log_action
from app.utils.logger_config import logger

import os


# Nombres de las pestañas (constantes)
TAB_ACTIVITIES = "📁 Actividades"
TAB_QUIZZES = "📝 Quizzes"
TAB_RUBRICS = "📊 Rúbricas"


class MainWindow(ctk.CTk):
    def __init__(self, client: CanvasClient, course_id: int, gemini_evaluator: HybridEvaluator | None):
        super().__init__()

        self.client = client
        self.course_id = course_id
        self.gemini_evaluator = gemini_evaluator
        self.restart = False

        # --- CONFIGURACIÓN DE LA VENTANA PRINCIPAL ---
        course = self.client.get_course(self.course_id)
        self.course_name = course.name if course else f"Curso ID: {self.course_id}"
        self.title(f"Canvas Auto - {self.course_name}")
        self.geometry("900x700")
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=0)  # Header
        self.grid_rowconfigure(1, weight=1)  # TabView (contenido principal)
        self.grid_rowconfigure(2, weight=0)  # Barra de estado

        # Interceptar el evento de cierre de la ventana
        self.protocol("WM_DELETE_WINDOW", self.on_closing)

        # --- HEADER: nombre del curso + botón cambiar curso ---
        self._setup_header()

        # --- TABVIEW GLOBAL ---
        self._setup_tabview()

        # --- SUBMENÚS (lazy: se instancian al primer acceso) ---
        self.quizzes_frame = None
        self.rubrics_frame = None
        self.activities_frame = None
        self._initialized_tabs: set[str] = set()

        # --- BARRA DE ESTADO ---
        self.status_frame = ctk.CTkFrame(self, height=25)
        self.status_frame.grid(row=2, column=0, sticky="ew", padx=10, pady=(5, 10))
        self.status_frame.grid_columnconfigure(0, weight=1)

        self.status_label = ctk.CTkLabel(self.status_frame, text="Listo", anchor="w")
        self.status_label.grid(row=0, column=0, padx=10, sticky="ew")

        self.progress_bar = ctk.CTkProgressBar(self.status_frame)
        self.status_timer = None

        # --- ATAJOS DE TECLADO ---
        self.bind("<Control-Key-1>", lambda e: self._switch_to_tab(TAB_ACTIVITIES))
        self.bind("<Control-Key-2>", lambda e: self._switch_to_tab(TAB_QUIZZES))
        self.bind("<Control-Key-3>", lambda e: self._switch_to_tab(TAB_RUBRICS))

        # Inicializar la primera pestaña visible
        self._on_tab_change()

    # ------------------------------------------------------------------ #
    #  SETUP
    # ------------------------------------------------------------------ #

    def _setup_header(self):
        """Crea la cabecera con el nombre del curso y el botón de cambio."""
        header = ctk.CTkFrame(self, fg_color="transparent")
        header.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 0))
        header.grid_columnconfigure(0, weight=1)

        ctk.CTkLabel(
            header, text=self.course_name,
            font=ctk.CTkFont(size=22, weight="bold"), anchor="w"
        ).grid(row=0, column=0, sticky="w", padx=5)

        btn_frame = ctk.CTkFrame(header, fg_color="transparent")
        btn_frame.grid(row=0, column=1, sticky="e")

        ctk.CTkButton(
            btn_frame, text="🔄 Cambiar Curso", width=140,
            command=self.change_course
        ).pack(side="right", padx=(5, 0))

        ctk.CTkButton(
            btn_frame, text="▶ Tutorial", width=100,
            fg_color="transparent", border_width=1,
            command=self.open_main_tutorial
        ).pack(side="right", padx=(5, 0))

    def _setup_tabview(self):
        """Crea el CTkTabview global con las 3 pestañas."""
        self.tab_view = ctk.CTkTabview(self, anchor="w")
        self.tab_view.grid(row=1, column=0, sticky="nsew", padx=10, pady=5)

        self.tab_view.add(TAB_ACTIVITIES)
        self.tab_view.add(TAB_QUIZZES)
        self.tab_view.add(TAB_RUBRICS)

        self.tab_view.configure(command=self._on_tab_change)

    # ------------------------------------------------------------------ #
    #  NAVEGACIÓN ENTRE PESTAÑAS (lazy init)
    # ------------------------------------------------------------------ #

    def _on_tab_change(self):
        """Callback cuando se selecciona una pestaña. Instancia lazy del submenú."""
        current = self.tab_view.get()
        if current in self._initialized_tabs:
            return

        logger.info(f"Inicializando pestaña: {current}")
        self._initialized_tabs.add(current)

        if current == TAB_ACTIVITIES:
            from .activities_menu import ActivitiesMenu
            parent = self.tab_view.tab(TAB_ACTIVITIES)
            self.activities_frame = ActivitiesMenu(parent, self.client, self.gemini_evaluator, self.course_id, self)
            self.activities_frame.pack(expand=True, fill="both")

        elif current == TAB_QUIZZES:
            from .quizzes_menu import QuizzesMenu
            parent = self.tab_view.tab(TAB_QUIZZES)
            self.quizzes_frame = QuizzesMenu(parent, self.client, self.course_id)
            self.quizzes_frame.pack(expand=True, fill="both")

        elif current == TAB_RUBRICS:
            from .rubrics_menu import RubricsMenu
            parent = self.tab_view.tab(TAB_RUBRICS)
            self.rubrics_frame = RubricsMenu(parent, self.client, self.course_id)
            self.rubrics_frame.pack(expand=True, fill="both")

    def _switch_to_tab(self, tab_name: str):
        """Cambia a la pestaña indicada (usado por atajos de teclado)."""
        self.tab_view.set(tab_name)
        self._on_tab_change()

    # ------------------------------------------------------------------ #
    #  EVENTOS DE VENTANA
    # ------------------------------------------------------------------ #

    def on_closing(self):
        """
        Se ejecuta cuando el usuario intenta cerrar la ventana.
        Previene el cierre si hay una descarga en curso.
        """
        if self.activities_frame and self.activities_frame.active_thread and self.activities_frame.active_thread.is_alive():
            messagebox.showwarning("Proceso en Curso", "Hay una descarga en progreso. Por favor, espera a que termine antes de cerrar la aplicación.")
        else:
            self.destroy()

    @log_action
    def open_main_tutorial(self):
        webbrowser.open("https://youtu.be/BqtjFDO0Gwc")

    @log_action
    def change_course(self):
        logger.info("Botón 'Seleccionar otro Curso' pulsado. Reiniciando flujo.")
        self.restart = True
        self.destroy()

    # ------------------------------------------------------------------ #
    #  BARRA DE ESTADO
    # ------------------------------------------------------------------ #

    def update_status(self, message: str, clear_after_ms: int = 0):
        """Actualiza el texto de la barra de estado."""
        self.status_label.configure(text=message)

        if self.status_timer:
            self.after_cancel(self.status_timer)

        if clear_after_ms > 0:
            self.status_timer = self.after(clear_after_ms, lambda: self.status_label.configure(text="Listo"))

    def show_progress_bar(self, indeterminate=False):
        """Muestra la barra de progreso."""
        if indeterminate:
            self.progress_bar.configure(mode='indeterminate')
            self.progress_bar.start()
        else:
            self.progress_bar.configure(mode='determinate')
            self.progress_bar.set(0)

        self.progress_bar.grid(row=0, column=1, padx=10, pady=5, sticky="e")

    def hide_progress_bar(self):
        """Oculta la barra de progreso."""
        self.progress_bar.stop()
        self.progress_bar.grid_forget()

    def update_progress(self, value: float):
        """Actualiza el valor de la barra de progreso (de 0.0 a 1.0)."""
        self.progress_bar.set(value)