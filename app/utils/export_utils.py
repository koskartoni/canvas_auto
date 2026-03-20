from pathlib import Path
import csv

def rubric_to_csv(rubric_obj, dest: Path):
    """Recibe un objeto rubric de canvasapi y guarda CSV compatible Canvas."""
    max_ratings = max(len(c.ratings) for c in rubric_obj.data)
    headers = ["Rubric Name", "Criteria Name", "Criteria Description", "Criteria Points"]
    for i in range(max_ratings):
        headers += [f"Rating {i+1} Name", f"Rating {i+1} Description", f"Rating {i+1} Points"]

    with dest.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f); w.writerow(headers)
        for c in rubric_obj.data:
            row = [rubric_obj.title, c["description"], c.get("long_description", ""), c["points"]]
            for r in c["ratings"]:
                row += [r["description"], r.get("long_description", ""), r["points"]]
            w.writerow(row)


def gradebook_preview_to_csv(preview_data: dict, dest: Path):
    """Guarda un CSV a partir de la estructura normalizada de la previsualización."""
    selected_assignments = preview_data.get("selected_assignments", [])
    rows = preview_data.get("rows", [])

    headers = ["Alumno"] + [
        assignment.get("column_label") or assignment.get("name") or f"Actividad {assignment.get('id')}"
        for assignment in selected_assignments
    ]

    with dest.open("w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(headers)

        for row in rows:
            csv_row = [row.get("student_name", "")]
            grades_by_assignment_id = row.get("grades_by_assignment_id", {})
            for assignment in selected_assignments:
                csv_row.append(grades_by_assignment_id.get(assignment.get("id"), ""))
            writer.writerow(csv_row)
