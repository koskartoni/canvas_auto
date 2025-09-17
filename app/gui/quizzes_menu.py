# app/gui/quizzes_menu.py

import customtkinter as ctk
from tkinter import messagebox, Toplevel, scrolledtext
import json
import os
import pyperclip
from app.utils.logger_config import logger

from app.utils.path_utils import resource_path

class QuizzesMenu(ctk.CTkFrame):
    def __init__(self, parent, client, course_id, back_callback):
        super().__init__(parent)
        self.client = client
        self.course_id = course_id
        self.back_callback = back_callback

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(0, weight=1)

        # Botón para volver al menú principal
        back_button = ctk.CTkButton(self, text="< Volver al Menú Principal", command=self.back_callback)
        back_button.pack(anchor="nw", padx=10, pady=10)

        # Pestañas para Quizzes
        self.tab_view = ctk.CTkTabview(self, anchor="w")
        self.tab_view.pack(expand=True, fill="both", padx=10, pady=(0, 10))

        self.tab_view.add("Crear Quiz")
        self.tab_view.add("Ver Quizzes")

        self.setup_quiz_tab()
        self.setup_view_quizzes_tab()

    def setup_quiz_tab(self):
        quiz_tab = self.tab_view.tab("Crear Quiz")
        quiz_tab.grid_columnconfigure(1, weight=1)

        # Título
        ctk.CTkLabel(quiz_tab, text="Título del Quiz:").grid(row=0, column=0, padx=20, pady=(20, 10), sticky="w")
        self.quiz_title_entry = ctk.CTkEntry(quiz_tab, width=400)
        self.quiz_title_entry.grid(row=0, column=1, padx=20, pady=(20, 10), sticky="ew")

        # Tipo
        ctk.CTkLabel(quiz_tab, text="Tipo de Quiz:").grid(row=1, column=0, padx=20, pady=10, sticky="w")
        self.quiz_type_combobox = ctk.CTkComboBox(quiz_tab, values=["Quiz Clásico", "Nuevo Quiz"])
        self.quiz_type_combobox.set("Nuevo Quiz")
        self.quiz_type_combobox.grid(row=1, column=1, padx=20, pady=10, sticky="w")

        # Descripción
        ctk.CTkLabel(quiz_tab, text="Descripción / Instrucciones:").grid(row=2, column=0, padx=20, pady=10, sticky="nw")
        self.quiz_desc_textbox = ctk.CTkTextbox(quiz_tab, height=120)
        self.quiz_desc_textbox.grid(row=2, column=1, padx=20, pady=10, sticky="nsew")
        quiz_tab.grid_rowconfigure(2, weight=1)

        # Área para pegar JSON de preguntas (opcional)
        ctk.CTkLabel(quiz_tab, text="Preguntas (JSON de IA):").grid(row=3, column=0, padx=20, pady=(10, 0), sticky="nw")
        self.ai_json_textbox = ctk.CTkTextbox(quiz_tab, height=220)
        self.ai_json_textbox.grid(row=3, column=1, padx=20, pady=(10, 10), sticky="nsew")
        quiz_tab.grid_rowconfigure(3, weight=1)

        # Botonera inferior
        btns = ctk.CTkFrame(quiz_tab, fg_color="transparent")
        btns.grid(row=4, column=1, padx=20, pady=10, sticky="e")

        prompt_btn = ctk.CTkButton(btns, text="📋 Prompt IA", command=self._show_quiz_prompt)
        prompt_btn.pack(side="left", padx=(0, 10))

        create_button = ctk.CTkButton(btns, text="Crear Quiz", command=self.handle_create_quiz)
        create_button.pack(side="left")

    def handle_create_quiz(self):
        logger.info("Botón 'Crear Quiz' pulsado.")
        title = self.quiz_title_entry.get().strip()
        description = self.quiz_desc_textbox.get("1.0", "end-1c")
        quiz_type_selection = self.quiz_type_combobox.get()

        if not title:
            messagebox.showwarning("Campo Requerido", "El título del quiz no puede estar vacío.")
            return

        settings = {"title": title, "description": description, "published": False}

        raw = self.ai_json_textbox.get("1.0", "end-1c").strip()
        items = []
        if raw:
            try:
                data = json.loads(raw)
                if isinstance(data, dict) and "items" in data:
                    items = data["items"]
                elif isinstance(data, list):
                    items = data
                else:
                    raise ValueError("JSON no válido: usa lista de preguntas o {'items': [...]}.")

                for i, q in enumerate(items, start=1):
                    if not all(k in q for k in ["question", "choices", "correct"]):
                        raise ValueError(f"Pregunta {i} incompleta: debe tener 'question', 'choices' y 'correct'.")
                    if not q["choices"]:
                        raise ValueError(f"Pregunta {i}: 'choices' no puede estar vacío.")
                    if not str(q["correct"]).strip():
                        raise ValueError(f"Pregunta {i}: 'correct' no puede estar vacío.")

            except Exception as exc:
                messagebox.showerror("JSON inválido", f"No se pudo leer el JSON de preguntas:\n{exc}")
                return

        success = False
        if quiz_type_selection == "Nuevo Quiz":
            if items:
                success = self.client.create_new_quiz_and_items(self.course_id, settings, items)
            else:
                quiz_obj = self.client._create_new_quiz_base(self.course_id, settings)
                success = quiz_obj is not None
        else:
            settings["quiz_type"] = "assignment"
            success = self.client.create_quiz(self.course_id, settings)

        if success:
            messagebox.showinfo("Éxito", f"El quiz '{title}' ha sido creado correctamente.")
            self.quiz_title_entry.delete(0, "end")
            self.quiz_desc_textbox.delete("1.0", "end")
            self.ai_json_textbox.delete("1.0", "end")
        else:
            messagebox.showerror("Error", self.client.error_message or "Ocurrió un error al crear el quiz.")

    def _show_quiz_prompt(self):
        prompt_path = resource_path("app/resources/prompt_ai_quiz.txt")
        if not os.path.exists(prompt_path):
            messagebox.showerror("Error", f"No se encontró el archivo:\n{prompt_path}")
            return

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_text = f.read()

        win = Toplevel(self)
        win.title("Prompt IA para New Quiz")
        win.geometry("760x520")

        txt = scrolledtext.ScrolledText(win, wrap="word", font=("Consolas", 10))
        txt.insert("1.0", prompt_text)
        txt.configure(state="disabled")
        txt.pack(expand=True, fill="both", padx=10, pady=10)

        def copy_to_clipboard():
            pyperclip.copy(prompt_text)
            messagebox.showinfo("Copiado", "Prompt copiado al portapapeles.")

        ctk.CTkButton(win, text="📋 Copiar al portapapeles", command=copy_to_clipboard).pack(pady=6)

    def setup_view_quizzes_tab(self):
        view_tab = self.tab_view.tab("Ver Quizzes")
        view_tab.grid_columnconfigure(0, weight=1)
        view_tab.grid_rowconfigure(1, weight=1)
        action_frame = ctk.CTkFrame(view_tab)
        action_frame.grid(row=0, column=0, padx=20, pady=10, sticky="ew")
        refresh_button = ctk.CTkButton(action_frame, text="Cargar Todos los Quizzes", command=self.handle_view_quizzes)
        refresh_button.pack(side="left")
        self.quiz_list_frame = ctk.CTkScrollableFrame(view_tab, label_text="Quizzes en el Curso")
        self.quiz_list_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")

    def _display_quiz_list(self, header_text, quiz_list, first_list=False):
        """Crea un encabezado y una lista de quizzes en el frame de la lista."""
        padding_top = (5, 2) if first_list else (15, 2)
        header = ctk.CTkLabel(self.quiz_list_frame, text=header_text,
                              font=ctk.CTkFont(weight="bold"))
        header.pack(anchor="w", padx=10, pady=padding_top)
        for quiz in quiz_list:
            label_text = f"• {quiz.get('title', 'Sin título')} (ID: {quiz.get('id', 'N/A')})"
            label = ctk.CTkLabel(self.quiz_list_frame, text=label_text)
            label.pack(anchor="w", padx=20, pady=2)

    def handle_view_quizzes(self):
        logger.info("Botón 'Cargar Todos los Quizzes' pulsado.")
        for widget in self.quiz_list_frame.winfo_children():
            widget.destroy()

        classic_quizzes = self.client.get_quizzes(self.course_id)
        new_quizzes = self.client.get_new_quizzes(self.course_id)

        if classic_quizzes is None or new_quizzes is None:
            messagebox.showerror("Error", self.client.error_message or "No se pudo cargar la lista de quizzes.")
            return

        if not classic_quizzes and not new_quizzes:
            label = ctk.CTkLabel(self.quiz_list_frame, text="No se encontraron quizzes en este curso.")
            label.pack(pady=10)
            return

        if classic_quizzes:
            self._display_quiz_list("Quizzes Clásicos", classic_quizzes, first_list=True)

        if new_quizzes:
            self._display_quiz_list("Nuevos Quizzes", new_quizzes)
