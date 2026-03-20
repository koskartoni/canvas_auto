import logging
import threading
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

logger = logging.getLogger(__name__)


class GradebookMenu(ctk.CTkFrame):
    def __init__(self, parent, client, course_id, main_window):
        super().__init__(parent)
        self.client = client
        self.course_id = course_id
        self.main_window = main_window

        self.filter_options: dict = {"groups": [], "assignments": []}
        self.selected_preview: dict | None = None
        self.active_thread = None

        self.group_vars: dict[str, ctk.StringVar] = {}
        self.assignment_vars: dict[str, ctk.StringVar] = {}
        self.group_checkboxes = []
        self.assignment_checkboxes = []

        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        self._build_layout()
        self._set_controls_enabled(False)
        self._load_filter_placeholders()

        threading.Thread(target=self._load_filter_options, daemon=True).start()

    def _build_layout(self):
        filters_container = ctk.CTkFrame(self)
        filters_container.grid(row=0, column=0, sticky="ew", padx=10, pady=(0, 10))
        filters_container.grid_columnconfigure(0, weight=1)
        filters_container.grid_columnconfigure(1, weight=1)
        filters_container.grid_rowconfigure(0, weight=1)

        self.groups_frame = ctk.CTkScrollableFrame(filters_container, label_text="Grupos de actividades", height=180)
        self.groups_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 5), pady=10)
        self.groups_frame.grid_columnconfigure(0, weight=1)

        self.assignments_frame = ctk.CTkScrollableFrame(filters_container, label_text="Actividades", height=180)
        self.assignments_frame.grid(row=0, column=1, sticky="nsew", padx=(5, 0), pady=10)
        self.assignments_frame.grid_columnconfigure(0, weight=1)

        actions_frame = ctk.CTkFrame(filters_container, fg_color="transparent")
        actions_frame.grid(row=1, column=0, columnspan=2, sticky="ew", padx=10, pady=(0, 10))

        self.preview_button = ctk.CTkButton(actions_frame, text="Previsualizar", command=self._handle_preview)
        self.preview_button.pack(side="left", padx=(0, 8))

        self.clear_button = ctk.CTkButton(
            actions_frame,
            text="Limpiar filtros",
            command=self._clear_filters,
            fg_color="#555555",
            hover_color="#666666",
        )
        self.clear_button.pack(side="left", padx=(0, 8))

        self.export_button = ctk.CTkButton(
            actions_frame,
            text="Exportar CSV",
            command=self._handle_export,
            state="disabled",
        )
        self.export_button.pack(side="right")

        preview_container = ctk.CTkFrame(self)
        preview_container.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        preview_container.grid_columnconfigure(0, weight=1)
        preview_container.grid_rowconfigure(1, weight=1)

        self.preview_info_label = ctk.CTkLabel(
            preview_container,
            text="Selecciona grupos o actividades y pulsa 'Previsualizar'.",
            anchor="w",
        )
        self.preview_info_label.grid(row=0, column=0, sticky="ew", padx=10, pady=(10, 5))

        tree_frame = ctk.CTkFrame(preview_container)
        tree_frame.grid(row=1, column=0, sticky="nsew", padx=10, pady=(0, 10))
        tree_frame.grid_columnconfigure(0, weight=1)
        tree_frame.grid_rowconfigure(0, weight=1)

        self.preview_tree = ttk.Treeview(tree_frame, columns=(), show="headings")
        self.preview_tree.grid(row=0, column=0, sticky="nsew")

        y_scroll = ttk.Scrollbar(tree_frame, orient="vertical", command=self.preview_tree.yview)
        y_scroll.grid(row=0, column=1, sticky="ns")
        x_scroll = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.preview_tree.xview)
        x_scroll.grid(row=1, column=0, sticky="ew")

        self.preview_tree.configure(yscrollcommand=y_scroll.set, xscrollcommand=x_scroll.set)

    def _load_filter_placeholders(self):
        self._set_placeholder(self.groups_frame, "Cargando grupos...")
        self._set_placeholder(self.assignments_frame, "Cargando actividades...")

    def _set_placeholder(self, parent, text: str):
        for widget in parent.winfo_children():
            widget.destroy()
        ctk.CTkLabel(parent, text=text, anchor="w").grid(row=0, column=0, sticky="ew", padx=10, pady=10)

    def _load_filter_options(self):
        logger.info("Cargando filtros del libro de notas.")
        self.after(0, self.main_window.update_status, "Cargando filtros del libro de notas...")
        try:
            filter_options = self.client.get_gradebook_filter_options(self.course_id)
            if filter_options is None:
                raise RuntimeError(self.client.error_message or "No se pudieron cargar los filtros.")

            self.after(0, self._populate_filter_options, filter_options)
            self.after(0, self.main_window.update_status, "Filtros del libro de notas cargados.", 3000)
        except Exception as e:
            logger.error("No se pudieron cargar los filtros del libro de notas.", exc_info=True)
            error_msg = self.client.error_message or str(e)
            self.after(0, self._set_placeholder, self.groups_frame, "Error al cargar grupos.")
            self.after(0, self._set_placeholder, self.assignments_frame, "Error al cargar actividades.")
            self.after(0, self.main_window.update_status, "Error al cargar el libro de notas.", 5000)
            self.after(0, messagebox.showerror, "Error", error_msg)

    def _populate_filter_options(self, filter_options: dict):
        self.filter_options = filter_options

        for widget in self.groups_frame.winfo_children():
            widget.destroy()
        for widget in self.assignments_frame.winfo_children():
            widget.destroy()

        self.group_vars.clear()
        self.assignment_vars.clear()
        self.group_checkboxes.clear()
        self.assignment_checkboxes.clear()

        groups = filter_options.get("groups", [])
        assignments = filter_options.get("assignments", [])

        if not groups:
            self._set_placeholder(self.groups_frame, "No hay grupos de actividades disponibles.")
        else:
            for row_idx, group in enumerate(groups):
                group_id = str(group.get("id"))
                var = ctk.StringVar(value="0")
                checkbox = ctk.CTkCheckBox(
                    self.groups_frame,
                    text=group.get("name") or f"Grupo {group_id}",
                    variable=var,
                    onvalue="1",
                    offvalue="0",
                )
                checkbox.grid(row=row_idx, column=0, sticky="ew", padx=10, pady=4)
                self.group_vars[group_id] = var
                self.group_checkboxes.append(checkbox)

        if not assignments:
            self._set_placeholder(self.assignments_frame, "No hay actividades disponibles.")
        else:
            for row_idx, assignment in enumerate(assignments):
                assignment_id = str(assignment.get("id"))
                var = ctk.StringVar(value="0")
                label = assignment.get("name") or f"Actividad {assignment_id}"
                group_name = assignment.get("group_name")
                if group_name:
                    label = f"{label} [{group_name}]"

                checkbox = ctk.CTkCheckBox(
                    self.assignments_frame,
                    text=label,
                    variable=var,
                    onvalue="1",
                    offvalue="0",
                )
                checkbox.grid(row=row_idx, column=0, sticky="ew", padx=10, pady=4)
                self.assignment_vars[assignment_id] = var
                self.assignment_checkboxes.append(checkbox)

        self._set_controls_enabled(True)

    def _handle_preview(self):
        if self.active_thread and self.active_thread.is_alive():
            messagebox.showwarning("Proceso en curso", "Espera a que termine la consulta actual.")
            return

        selected_group_ids = [group_id for group_id, var in self.group_vars.items() if var.get() == "1"]
        selected_assignment_ids = [
            assignment_id for assignment_id, var in self.assignment_vars.items() if var.get() == "1"
        ]

        if not selected_group_ids and not selected_assignment_ids:
            messagebox.showwarning(
                "Filtros vacíos",
                "Selecciona al menos un grupo de actividades o una actividad.",
            )
            return

        selected_assignments = self.client.resolve_gradebook_assignments(
            self.filter_options,
            selected_group_ids,
            selected_assignment_ids,
        )
        if not selected_assignments:
            messagebox.showwarning(
                "Sin actividades",
                "La selección actual no produjo actividades válidas para consultar.",
            )
            return

        self.selected_preview = None
        self._clear_preview(keep_message=True)
        self._set_controls_enabled(False)
        self.preview_info_label.configure(text="Consultando libro de notas...")
        self.main_window.update_status("Consultando libro de notas...")
        self.main_window.show_progress_bar(indeterminate=True)

        self.active_thread = threading.Thread(
            target=self._load_preview_worker,
            args=(selected_assignments,),
            daemon=True,
        )
        self.active_thread.start()

    def _load_preview_worker(self, selected_assignments: list[dict]):
        try:
            preview = self.client.get_gradebook_preview(self.course_id, selected_assignments)
            if preview is None:
                raise RuntimeError(self.client.error_message or "No se pudo obtener el libro de notas.")
            self.after(0, self._render_preview, preview)
        except Exception as e:
            logger.error("No se pudo obtener la previsualización del libro de notas.", exc_info=True)
            error_msg = self.client.error_message or str(e)
            self.after(0, self._on_preview_error, error_msg)

    def _render_preview(self, preview: dict):
        self.selected_preview = preview
        selected_assignments = preview.get("selected_assignments", [])
        rows = preview.get("rows", [])

        self._clear_preview(keep_message=True)

        columns = ["student_name"] + [f"assignment_{assignment['id']}" for assignment in selected_assignments]
        self.preview_tree.configure(columns=columns)

        self.preview_tree.heading("student_name", text="Alumno")
        self.preview_tree.column("student_name", width=260, minwidth=180, anchor="w", stretch=True)

        for assignment in selected_assignments:
            column_id = f"assignment_{assignment['id']}"
            heading = assignment.get("column_label") or assignment.get("name") or f"Actividad {assignment['id']}"
            self.preview_tree.heading(column_id, text=heading)
            self.preview_tree.column(column_id, width=140, minwidth=110, anchor="center", stretch=False)

        for row in rows:
            values = [row.get("student_name", "")]
            grades_by_assignment_id = row.get("grades_by_assignment_id", {})
            for assignment in selected_assignments:
                values.append(grades_by_assignment_id.get(assignment["id"], ""))
            self.preview_tree.insert("", "end", values=values)

        if rows:
            self.preview_info_label.configure(
                text=f"Previsualización cargada: {len(rows)} alumnos, {len(selected_assignments)} actividades."
            )
            self.export_button.configure(state="normal")
            self.main_window.update_status("Libro de notas cargado.", 4000)
        else:
            self.preview_info_label.configure(
                text="La consulta no devolvió filas para los filtros seleccionados."
            )
            self.export_button.configure(state="disabled")
            self.main_window.update_status("Sin resultados para los filtros seleccionados.", 5000)

        self.main_window.hide_progress_bar()
        self._set_controls_enabled(True)

    def _on_preview_error(self, error_msg: str):
        self.main_window.hide_progress_bar()
        self._set_controls_enabled(True)
        self.preview_info_label.configure(text="No se pudo cargar la previsualización.")
        self.export_button.configure(state="disabled")
        self.main_window.update_status("Error al consultar el libro de notas.", 5000)
        messagebox.showerror("Error", error_msg)

    def _handle_export(self):
        if not self.selected_preview or not self.selected_preview.get("rows"):
            messagebox.showwarning(
                "Sin datos",
                "Primero debes cargar una previsualización con resultados para poder exportar.",
            )
            return

        file_path = filedialog.asksaveasfilename(
            title="Guardar libro de notas",
            defaultextension=".csv",
            filetypes=[("Archivos CSV", "*.csv")],
            initialfile=f"libro_notas_curso_{self.course_id}.csv",
        )
        if not file_path:
            return

        ok = self.client.export_gradebook_preview_to_csv(self.selected_preview, Path(file_path))
        if ok:
            self.main_window.update_status("Libro de notas exportado correctamente.", 4000)
            messagebox.showinfo("Exportación completada", "El libro de notas se exportó correctamente.")
        else:
            messagebox.showerror("Error", self.client.error_message or "No se pudo exportar el CSV.")

    def _clear_filters(self):
        for var in self.group_vars.values():
            var.set("0")
        for var in self.assignment_vars.values():
            var.set("0")

        self.selected_preview = None
        self._clear_preview()
        self.preview_info_label.configure(text="Selecciona grupos o actividades y pulsa 'Previsualizar'.")
        self.main_window.update_status("Filtros limpiados.", 3000)

    def _clear_preview(self, keep_message: bool = False):
        self.preview_tree.delete(*self.preview_tree.get_children())
        self.preview_tree.configure(columns=())
        if not keep_message:
            self.preview_info_label.configure(text="Selecciona grupos o actividades y pulsa 'Previsualizar'.")
        self.export_button.configure(state="disabled")

    def _set_controls_enabled(self, enabled: bool):
        state = "normal" if enabled else "disabled"
        self.preview_button.configure(state=state)
        self.clear_button.configure(state=state)

        for checkbox in self.group_checkboxes:
            checkbox.configure(state=state)
        for checkbox in self.assignment_checkboxes:
            checkbox.configure(state=state)

        if not enabled or not self.selected_preview or not self.selected_preview.get("rows"):
            self.export_button.configure(state="disabled")
        else:
            self.export_button.configure(state="normal")
