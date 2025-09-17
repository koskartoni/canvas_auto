# app/gui/rubrics_menu.py

import customtkinter as ctk
from tkinter import messagebox, filedialog, Toplevel, scrolledtext
import json
import csv
import re
import pyperclip
import os

from canvasapi import rubric

from app.utils.logger_config import logger

from app.utils.path_utils import resource_path


class CriterionFrame(ctk.CTkFrame):
    """
    Sub‑frame que representa un criterio con tabla de niveles (ratings).
    """
    def __init__(self, master, remove_callback):
        super().__init__(master, fg_color="transparent")
        self.remove_callback = remove_callback
        self._ratings: list[dict] = []

        # Entradas de criterio
        self.desc = ctk.CTkEntry(self, placeholder_text="Descripción corta")
        self.desc.grid(row=0, column=0, padx=2, pady=2, sticky="ew")
        self.long = ctk.CTkEntry(self, placeholder_text="Descripción larga")
        self.long.grid(row=0, column=1, padx=2, pady=2, sticky="ew")
        self.points = ctk.CTkEntry(self, width=60, placeholder_text="Pts")
        self.points.grid(row=0, column=2, padx=2, pady=2)

        del_btn = ctk.CTkButton(self, text="🗑", width=30, command=self._on_remove)
        del_btn.grid(row=0, column=3, padx=2)

        # Tabla de niveles
        self.rating_container = ctk.CTkFrame(self)
        self.rating_container.grid(row=1, column=0, columnspan=4, sticky="ew")
        self._add_rating_row()  # Arrancamos con un nivel

        add_rating = ctk.CTkButton(self, text="+ Nivel", command=self._add_rating_row)
        add_rating.grid(row=2, column=0, columnspan=4, pady=4)

    # ---------- private ----------
    def _add_rating_row(self):
        idx = len(self._ratings)
        row = {}
        row_frame = ctk.CTkFrame(self.rating_container, fg_color="transparent")
        row_frame.grid(row=idx, column=0, sticky="ew")

        row["desc"] = ctk.CTkEntry(row_frame, placeholder_text="Nombre nivel")
        row["desc"].grid(row=0, column=0, padx=2, pady=1, sticky="ew")
        row["points"] = ctk.CTkEntry(row_frame, width=60, placeholder_text="Pts")
        row["points"].grid(row=0, column=1, padx=2, pady=1)
        remove = ctk.CTkButton(row_frame, text="—", width=30,
                               command=lambda rf=row_frame: self._delete_rating(rf))
        remove.grid(row=0, column=2, padx=2)
        self._ratings.append((row_frame, row))

    def _delete_rating(self, frame):
        for i, (rf, _) in enumerate(self._ratings):
            if rf == frame:
                rf.destroy()
                self._ratings.pop(i)
                break

    def _on_remove(self):
        self.destroy()
        self.remove_callback(self)

    # ---------- public ----------
    def to_dict(self):
        """
        Convierte el criterio y sus niveles (ratings) a dict listo para enviar a la API de Canvas.
        Soporta puntos decimales con punto o coma.
        """

        def _parse_points(v):
            s = (v or "").strip()
            if not s:
                return 0.0
            s = s.replace(",", ".")
            try:
                return float(s)
            except ValueError:
                return 0.0

        # Recoger niveles desde self._ratings
        ratings = []
        for _, r in self._ratings:
            ratings.append({
                "description": r["desc"].get().strip(),
                "long_description": "",
                "points": _parse_points(r["points"].get())
            })

        return {
            "description": self.desc.get().strip(),
            "long_description": self.long.get().strip(),
            "points": _parse_points(self.points.get()),
            "criterion_use_range": False,
            "ratings": ratings
        }


class RubricsMenu(ctk.CTkFrame):
    def __init__(self, parent, client, course_id, back_callback):
        super().__init__(parent)
        self.client = client
        self.course_id = course_id
        self.back_callback = back_callback
        self.imported_criteria: list[dict] | None = None    # ← almacena lo cargado


        back_button = ctk.CTkButton(self, text="< Volver al Menú Principal", command=self.back_callback)
        back_button.pack(anchor="nw", padx=10, pady=10)

        self.tab_view = ctk.CTkTabview(self, anchor="w")
        self.tab_view.pack(expand=True, fill="both", padx=10, pady=(0, 10))

        self.tab_view.add("Crear Rúbrica")
        self.tab_view.add("Ver Rúbricas")

        self.setup_create_rubric_tab()
        self.setup_view_rubrics_tab()

    def _show_ai_prompt(self):
        prompt_path = resource_path("app/resources/prompt_ai_rubrica.txt")
        if not os.path.exists(prompt_path):
            messagebox.showerror("Error", f"No se encontró el archivo:\n{prompt_path}")
            return

        with open(prompt_path, "r", encoding="utf-8") as f:
            prompt_text = f.read()

        # Ventana emergente
        win = Toplevel(self)
        win.title("Prompt IA para Rúbrica")
        win.geometry("700x500")

        txt = scrolledtext.ScrolledText(win, wrap="word", font=("Consolas", 10))
        txt.insert("1.0", prompt_text)
        txt.configure(state="disabled")
        txt.pack(expand=True, fill="both", padx=10, pady=10)

        def copy_to_clipboard():
            pyperclip.copy(prompt_text)
            messagebox.showinfo("Copiado", "Prompt copiado al portapapeles.")

        btn_copy = ctk.CTkButton(win, text="📋 Copiar al portapapeles", command=copy_to_clipboard)
        btn_copy.pack(pady=5)

    def setup_create_rubric_tab(self):
        rubric_tab = self.tab_view.tab("Crear Rúbrica")
        rubric_tab.grid_columnconfigure(0, weight=1)
        rubric_tab.grid_rowconfigure(2, weight=1)

        # 1. Título
        ctk.CTkLabel(rubric_tab, text="Título de la Rúbrica:").grid(row=0, column=0, sticky="w", padx=8, pady=4)
        self.rubric_title_entry = ctk.CTkEntry(rubric_tab)
        self.rubric_title_entry.grid(row=0, column=1, sticky="ew", padx=8, pady=4)

        # 2. Contenedor de criterios
        self.criteria_frame = ctk.CTkScrollableFrame(rubric_tab, label_text="Criterios")
        self.criteria_frame.grid(row=2, column=0, columnspan=2, sticky="nsew", padx=8, pady=4)

        add_crit_btn = ctk.CTkButton(rubric_tab, text="+ Criterio", command=self._add_criterion_frame)
        add_crit_btn.grid(row=1, column=0, sticky="w", padx=8)

        # 3. Opciones
        self.free_form_comments_check = ctk.CTkCheckBox(rubric_tab, text="Comentarios libres")
        self.free_form_comments_check.select()
        self.free_form_comments_check.grid(row=3, column=0, sticky="w", padx=8, pady=2)

        self.hide_score_check = ctk.CTkCheckBox(rubric_tab, text="Ocultar puntuación total")
        self.hide_score_check.grid(row=3, column=1, sticky="w", padx=8, pady=2)

        ctk.CTkLabel(rubric_tab, text="Propósito:").grid(row=4, column=0, sticky="w", padx=8, pady=2)
        self.purpose_combo = ctk.CTkComboBox(rubric_tab, values=["grading", "bookmark"])
        self.purpose_combo.set("grading")
        self.purpose_combo.grid(row=4, column=1, sticky="w", padx=8, pady=2)

        # 4. Acciones
        btn_frame = ctk.CTkFrame(rubric_tab, fg_color="transparent")
        btn_frame.grid(row=5, column=0, columnspan=2, sticky="ew", pady=10, padx=8)

        # que el frame de botones se estire a lo ancho
        btn_frame.grid_columnconfigure((0, 1, 2), weight=1)

        import_btn = ctk.CTkButton(btn_frame, text="Importar Rúbrica", command=self.handle_import_rubric)
        create_btn = ctk.CTkButton(btn_frame, text="Crear Rúbrica", command=self.handle_create_rubric)
        prompt_btn = ctk.CTkButton(btn_frame, text="📋 Prompt IA", command=self._show_ai_prompt)

        # distribución uniforme en 3 columnas
        import_btn.grid(row=0, column=0, padx=6, pady=5, sticky="ew")
        create_btn.grid(row=0, column=1, padx=6, pady=5, sticky="ew")
        prompt_btn.grid(row=0, column=2, padx=6, pady=5, sticky="ew")

        #  Vista previa mínima (opcional, puedes ampliar)
        self.preview = ctk.CTkLabel(rubric_tab, text="")
        self.preview.grid(row=6, column=0, columnspan=2, sticky="ew", padx=8, pady=4)

    # --------------- helpers (GUI) ---------------- #
    def _add_criterion_frame(self):
        cf = CriterionFrame(self.criteria_frame, self._remove_criterion)
        cf.pack(fill="x", pady=4, padx=4)

    def _remove_criterion(self, crit_frame):
        # nada especial, se destruye desde la propia clase
        pass

    def _num(self, s) -> float:
        """
        Convierte un valor de puntos a float.
        Acepta '2.5', '2,5', '', None. Devuelve 0.0 si no es parseable.
        """
        if s is None:
            return 0.0
        txt = str(s).strip().replace(",", ".")
        try:
            return float(txt) if txt else 0.0
        except ValueError:
            return 0.0

    # -----------------------------------------------------------
    #  IMPORTACIÓN CSV / JSON
    # -----------------------------------------------------------
    def handle_import_rubric(self):
        file_path = filedialog.askopenfilename(
            title="Seleccionar archivo de rúbrica",
            filetypes=[("Archivos JSON", "*.json"), ("Archivos CSV", "*.csv")]
        )
        if not file_path:
            return

        try:
            if file_path.lower().endswith(".json"):
                criteria = self._load_json(file_path)
            else:
                criteria = self._load_csv(file_path)
        except Exception as exc:
            messagebox.showerror("Error", f"No se pudo leer el archivo:\n{exc}")
            logger.exception("Error al importar rúbrica")
            return

        if not criteria:
            messagebox.showwarning("Vacío", "No se encontraron criterios en el archivo.")
            return

        # Guarda la lista para usarla en 'Crear Rúbrica'
        self.imported_criteria = criteria

        # Rellena el constructor visual con los criterios importados
        self._populate_builder(criteria)

        messagebox.showinfo("Importación", "Rúbrica cargada. Revisa / edita y pulsa 'Crear Rúbrica'.")

    def _load_json(self, path: str) -> list[dict]:
        """Lee JSON Canvas clásico o nuestro propio esquema."""
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        rubric = data.get("rubric", data)  # admite {rubric:{...}} o plano
        crit_obj = rubric.get("criteria", [])
        if isinstance(crit_obj, dict):
            return list(crit_obj.values())
        elif isinstance(crit_obj, list):
            return crit_obj
        else:
            return []

    def _load_csv(self, file_path):
        """
        Lee CSVs de rúbricas:
          - Formato oficial Canvas (RubricsApiController#download_rubrics)
          - Cualquier variante que ponga Ratings en bloques de 3 columnas
        Acepta decimales con coma o punto. Si no hay "Criteria Points", usa el
        máximo de los puntos de los ratings como puntos del criterio.
        """

        def _fnum(s):
            s = (s or "").strip()
            if not s:
                return 0.0
            s = s.replace(",", ".")
            try:
                return float(s)
            except ValueError:
                return 0.0

        criteria = {}
        with open(file_path, "r", encoding="utf-8-sig", newline="") as f:
            rdr = csv.reader(f)
            rows = list(rdr)

        if not rows:
            return []

        header = [h.strip() for h in rows[0]]

        # Detectamos si es el CSV "oficial" de Canvas
        is_canvas_official = (
                len(header) >= 4 and
                header[0] == "Rubric Name" and
                header[1] == "Criteria Name" and
                header[2] == "Criteria Description" and
                header[3] == "Criteria Enable Range"
        )

        # También intentamos detectar si hay columnas de "Rating Name/Description/Points"
        # Pueden venir repetidas: Rating Name, Rating Description, Rating Points, Rating Name, ...
        def _rating_triplets_from_header(hdr):
            idxs = []
            i = 0
            while i < len(hdr) - 2:
                if (hdr[i].startswith("Rating Name") and
                        hdr[i + 1].startswith("Rating Description") and
                        hdr[i + 2].startswith("Rating Points")):
                    idxs.append((i, i + 1, i + 2))
                    i += 3
                else:
                    i += 1
            return idxs

        rating_triplets = _rating_triplets_from_header(header) if is_canvas_official else []

        # Recorremos filas de datos
        for row in rows[1:]:
            # Limpieza de longitud
            if not any(cell.strip() for cell in row):
                continue
            # Asegura largo mínimo
            row = row + [""] * max(0, len(header) - len(row))

            if is_canvas_official:
                crit_name = row[1].strip()
                crit_desc = row[2].strip()
                use_range_raw = row[3].strip().lower()
                criterion_use_range = use_range_raw in ("true", "1", "yes", "y", "t", "verdadero", "sí", "si")

                # Construir ratings desde los tripletes
                ratings = []
                for (i_name, i_desc, i_pts) in rating_triplets:
                    name = (row[i_name] if i_name < len(row) else "").strip()
                    desc = (row[i_desc] if i_desc < len(row) else "").strip()
                    pts = _fnum(row[i_pts] if i_pts < len(row) else "")
                    if name or desc or pts:
                        ratings.append({
                            "description": name,
                            "long_description": desc,
                            "points": pts
                        })

                # Puntos del criterio: si no hay columna propia, tomamos el máximo de ratings
                points = max((r["points"] for r in ratings), default=0.0)

            else:
                # Formatos alternativos (tu export antiguo). Intentamos heurística:
                # 0: Rubric Name / 1: Criteria Name / 2: Criteria Description / 3: puede ser points o enable_range
                crit_name = (row[1] if len(row) > 1 else "").strip()
                crit_desc = (row[2] if len(row) > 2 else "").strip()
                col3 = (row[3] if len(row) > 3 else "").strip()

                # ¿col3 parece booleano? entonces es enable_range y no puntos
                if col3.lower() in ("true", "false", "1", "0", "yes", "no", "t", "f", "verdadero", "falso", "sí", "si"):
                    criterion_use_range = col3.lower() in ("true", "1", "yes", "t", "verdadero", "sí", "si")
                    points = 0.0
                    start = 4
                else:
                    criterion_use_range = False
                    points = _fnum(col3)
                    start = 4

                # A partir de 'start', leemos tripletes (name, desc, pts) si existen
                ratings = []
                i = start
                while i + 2 < len(row):
                    name = row[i].strip()
                    desc = row[i + 1].strip()
                    pts = _fnum(row[i + 2])
                    if name or desc or pts:
                        ratings.append({
                            "description": name,
                            "long_description": desc,
                            "points": pts
                        })
                    i += 3

                # Si no hay puntos de criterio, usamos el máximo de ratings
                if points == 0.0 and ratings:
                    points = max((r["points"] for r in ratings), default=0.0)

            # Guardamos el criterio
            criteria[len(criteria)] = {
                "description": crit_name,
                "long_description": crit_desc,
                "points": points,
                "criterion_use_range": criterion_use_range,
                "ratings": ratings,
            }

        # Devolvemos en la misma estructura que espera tu creador
        return [{"id": str(k), **v} for k, v in criteria.items()]

    def import_from_json(self, file_path):
        """
        Carga datos desde un archivo JSON, manejando correctamente tanto
        listas como diccionarios de criterios.
        """
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        rubric_data = data.get('rubric', data)
        association_data = data.get('rubric_association', {})

        self.rubric_title_entry.delete(0, 'end')
        self.rubric_title_entry.insert(0, rubric_data.get('title', ''))

        # --- LÓGICA CORREGIDA ---
        # Obtenemos el objeto de criterios
        criteria_object = rubric_data.get('criteria', {})

        # Comprobamos si es un diccionario (como en tu archivo) o una lista
        if isinstance(criteria_object, dict):
            # Si es un diccionario, nos quedamos con sus valores
            self.imported_criteria = list(criteria_object.values())
        elif isinstance(criteria_object, list):
            # Si ya es una lista, la usamos directamente
            self.imported_criteria = criteria_object
        else:
            # Si no es ninguno, es un formato inválido
            self.imported_criteria = []

        # El resto de la función sigue igual
        criteria_preview = []
        for crit in self.imported_criteria:
            desc = crit.get('description', '')
            points = crit.get('points', 0)
            ratings_count = len(crit.get('ratings', []))
            preview_text = f"{desc} ({ratings_count} niveles, {points} pts max)"
            criteria_preview.append(preview_text)

        self.rubric_criteria_textbox.delete("1.0", "end")
        if criteria_preview:
            self.rubric_criteria_textbox.insert("1.0", "RÚBRICA COMPLEJA IMPORTADA:\n" + "\n".join(criteria_preview))
        else:
            self.rubric_criteria_textbox.insert("1.0", "Error: El JSON no contenía criterios válidos.")

        if rubric_data.get('free_form_criterion_comments'):
            self.free_form_comments_check.select()
        else:
            self.free_form_comments_check.deselect()
        if association_data.get('hide_score_total', False):
            self.hide_score_check.select()
        else:
            self.hide_score_check.deselect()
        self.purpose_combo.set(association_data.get('purpose', 'grading'))

    def import_from_csv(self, file_path):
        criteria_text = []
        with open(file_path, 'r', encoding='utf-8', newline='') as f:
            reader = csv.reader(f)
            next(reader, None)
            for row in reader:
                if len(row) < 3: continue
                criteria_text.append(",".join(row))
        self.rubric_criteria_textbox.delete("1.0", "end")
        self.rubric_criteria_textbox.insert("1.0", "\n".join(criteria_text))
        self.rubric_title_entry.delete(0, 'end')
        self.rubric_title_entry.insert(0, "Rúbrica desde CSV (editar título)")

    def handle_create_rubric(self):
        title = self.rubric_title_entry.get().strip()
        if not title:
            messagebox.showwarning("Título vacío", "Escribe un título para la rúbrica.")
            return

        # ❶ Si se importó un archivo y el usuario no tocó nada más,
        #    usa directamente esa lista de criterios
        if self.imported_criteria:
            criteria = self.imported_criteria
        else:
            # ❷ Recoge lo que haya en el constructor visual usando to_dict() corregido
            criteria = [
                child.to_dict()
                for child in self.criteria_frame.winfo_children()
                if isinstance(child, CriterionFrame) and child.desc.get().strip()
            ]

        if not criteria:
            messagebox.showwarning("Campo obligatorio", "Añade al menos un criterio.")
            return

        opts = {
            "free_form_criterion_comments": bool(self.free_form_comments_check.get()),
            "hide_score_total": bool(self.hide_score_check.get()),
            "purpose": self.purpose_combo.get(),
        }

        ok = self.client.create_rubric(self.course_id, title, criteria, opts)
        if ok:
            messagebox.showinfo("Éxito", "Rúbrica creada en Canvas.")
            self.criteria_frame.destroy()  # limpiar
            self.setup_create_rubric_tab()  # recargar vista
        else:
            messagebox.showerror("Error", self.client.error_message or "Falló la creación.")

    def setup_view_rubrics_tab(self):
        view_tab = self.tab_view.tab("Ver Rúbricas")
        view_tab.grid_columnconfigure(0, weight=1)
        view_tab.grid_rowconfigure(1, weight=1)
        action_frame = ctk.CTkFrame(view_tab)
        action_frame.grid(row=0, column=0, padx=20, pady=10, sticky="ew")
        refresh_button = ctk.CTkButton(action_frame, text="Cargar Rúbricas", command=self.handle_view_rubrics)
        refresh_button.pack(side="left")
        self.rubric_list_frame = ctk.CTkScrollableFrame(view_tab, label_text="Rúbricas en el Curso")
        self.rubric_list_frame.grid(row=1, column=0, padx=20, pady=10, sticky="nsew")

        exp_btn = ctk.CTkButton(self.rubric_list_frame,
                                text="Exportar CSV",
                                width=90,
                                command=lambda r=rubric: self._export_one(r))
        exp_btn.pack(anchor="w", padx=10, pady=2)

    def _export_one(self, rubric):
        path = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            initialfile=f"{rubric['title']}.csv",
        )
        if not path:
            return
        ok = self.client.export_rubric_to_csv(self.course_id, rubric["id"], path)
        if ok:
            messagebox.showinfo("Exportación", "CSV guardado correctamente.")
        else:
            messagebox.showerror("Error", self.client.error_message or "No se pudo exportar.")

    def handle_view_rubrics(self):
        logger.info("Botón 'Cargar Rúbricas' pulsado.")

        # Limpia la lista
        for widget in self.rubric_list_frame.winfo_children():
            widget.destroy()

        rubrics = self.client.get_rubrics(self.course_id)
        if rubrics is None:
            messagebox.showerror("Error", self.client.error_message or
                                 "No se pudo cargar la lista de rúbricas.")
            return

        if not rubrics:
            ctk.CTkLabel(self.rubric_list_frame,
                         text="No se encontraron rúbricas en este curso.").pack(pady=10)
            return

        # Crea un frame por rúbrica → etiqueta + botón exportar
        for rubric in rubrics:
            details = f"• {rubric['title']} (ID {rubric['id']}) – Puntos: {rubric.get('points_possible', 'N/A')}"
            row = ctk.CTkFrame(self.rubric_list_frame, fg_color="transparent")
            row.pack(fill="x", pady=2, padx=4)

            lbl = ctk.CTkLabel(row, text=details)
            lbl.pack(side="left", padx=4, pady=2)

            exp_btn = ctk.CTkButton(row, text="Exportar CSV", width=100,
                                    command=lambda r=rubric: self._export_one(r))
            exp_btn.pack(side="right", padx=4, pady=2)

    def _export_one(self, rubric: dict):
        """Llama a CanvasClient.export_rubric_to_csv y muestra diálogo de guardado."""
        path = filedialog.asksaveasfilename(
            title="Guardar CSV",
            defaultextension=".csv",
            filetypes=[("Archivos CSV", "*.csv")],
            initialfile=f"{rubric['title']}.csv",
        )
        if not path:
            return

        ok = self.client.export_rubric_to_csv(self.course_id, rubric["id"], path)
        if ok:
            messagebox.showinfo("Exportación", "CSV guardado correctamente.")
        else:
            messagebox.showerror("Error", self.client.error_message or
                                 "No se pudo exportar la rúbrica.")

    def _populate_builder(self, criteria: list[dict]):
        """Limpia el constructor visual y crea un CriterionFrame por criterio importado."""
        # Elimina marcos actuales
        for widget in self.criteria_frame.winfo_children():
            widget.destroy()

        for crit in criteria:
            cf = CriterionFrame(self.criteria_frame, self._remove_criterion)
            cf.pack(fill="x", padx=4, pady=4)

            # Rellena campos
            cf.desc.insert(0, crit.get("description", ""))
            cf.long.insert(0, crit.get("long_description", ""))
            cf.points.insert(0, str(crit.get("points", 0)))

            # Rellenar niveles
            ratings = crit.get("ratings", [])
            if ratings:
                # borra el nivel vacío creado por defecto
                cf._delete_rating(cf._ratings[0][0])
                for r in ratings:
                    cf._add_rating_row()
                    _, widgets = cf._ratings[-1]
                    widgets["desc"].insert(0, r.get("description", ""))
                    widgets["points"].insert(0, str(r.get("points", 0)))
