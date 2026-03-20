# Spec: Libro de notas por actividades para Canvas Auto

## Resumen

Se añadirá una nueva pestaña `Libro de notas` dentro de la ventana principal del curso para consultar y exportar calificaciones de alumnos filtradas por actividades o grupos de actividades.

La primera versión no intentará replicar todo el gradebook de Canvas. El objetivo es cubrir el flujo más útil y estable para este proyecto:

- seleccionar uno o varios grupos de actividades y/o actividades concretas;
- previsualizar una tabla simple con una fila por alumno;
- exportar esa misma previsualización a CSV.

## Objetivos

- Añadir una pestaña nueva al nivel de `Actividades`, `Quizzes` y `Rúbricas`.
- Permitir filtrar el libro de notas por grupos de actividades y por actividades individuales.
- Mostrar una previsualización tabular antes de exportar.
- Exportar a CSV exactamente los datos mostrados en la previsualización.

## No Objetivos

- Replicar todos los filtros del gradebook nativo de Canvas.
- Editar o publicar notas desde esta nueva pestaña.
- Soportar filtros por sección, grupo de alumnos u otros criterios no relacionados con actividades.
- Garantizar un formato idéntico al CSV nativo de exportación de Canvas.

## Experiencia de Usuario

### Ubicación

La funcionalidad se expondrá como una nueva pestaña `Libro de notas` en `MainWindow`.

### Flujo

1. El usuario abre la pestaña `Libro de notas`.
2. La aplicación carga los grupos de actividades del curso y sus actividades.
3. El usuario selecciona uno o varios grupos y/o actividades concretas.
4. El usuario pulsa `Previsualizar`.
5. La aplicación construye y muestra una tabla con:
   - columna `Alumno`;
   - una columna por actividad seleccionada;
   - celdas vacías cuando no exista calificación para esa actividad.
6. El usuario pulsa `Exportar CSV` para guardar exactamente esa tabla.

### Controles previstos

- selector de grupos de actividades;
- selector de actividades;
- botón `Previsualizar`;
- botón `Exportar CSV`;
- botón `Limpiar filtros` o `Nueva consulta`.

## Diseño de Interfaz

La pestaña se implementará con una estructura similar al resto de submenús del proyecto:

- franja superior con filtros y acciones;
- zona central con la tabla de previsualización;
- barra de estado y progreso reutilizando la ventana principal cuando proceda.

La tabla de previsualización será deliberadamente simple en esta primera versión. No se incluirán edición inline, ordenación avanzada ni sincronización bidireccional con Canvas.

## Diseño Técnico

### Estructura de archivos

Se añadirán o ampliarán las siguientes piezas:

- `app/gui/main_window.py`
  - registrar la nueva pestaña `Libro de notas`;
  - inicializarla de forma lazy, igual que las demás.
- `app/gui/gradebook_menu.py`
  - nuevo componente de interfaz para filtros, previsualización y exportación.
- `app/api/canvas_client.py`
  - métodos para obtener grupos y actividades relevantes;
  - método para consultar submissions agrupadas por alumno para múltiples actividades;
  - transformación a estructura tabular lista para UI y exportación.
- `app/utils/export_utils.py` o utilidad equivalente
  - escritura del CSV desde la estructura tabular ya preparada.

### API de Canvas

La implementación se apoyará en dos recursos principales de la API:

- `GET /api/v1/courses/:course_id/assignment_groups`
  - para obtener grupos de actividades y sus actividades;
  - se reutilizará el patrón ya existente en el cliente.
- `GET /api/v1/courses/:course_id/students/submissions`
  - con `student_ids[]=all`;
  - con `assignment_ids[]` para limitar a las actividades filtradas;
  - con `grouped=true` para recibir el resultado agrupado por alumno.

Este enfoque evita depender de `Course Reports`, cuyo uso para un export de gradebook equivalente al de la UI no queda suficientemente claro en la documentación pública revisada.

### Modelo de datos interno

La consulta generará una estructura normalizada con:

- `selected_assignments`: lista ordenada de actividades que serán columnas;
- `students`: lista de alumnos detectados en la respuesta;
- `rows`: una fila por alumno con:
  - `student_id`;
  - `student_name`;
  - `grades_by_assignment_id`.

La previsualización y el CSV se construirán desde la misma estructura para asegurar consistencia total entre lo que se ve y lo que se exporta.

### Resolución de filtros

Reglas de filtrado:

- si el usuario selecciona grupos, se expanden a sus actividades;
- si además selecciona actividades individuales, se unen al conjunto resultante;
- se eliminarán duplicados por `assignment_id`;
- si tras resolver filtros no queda ninguna actividad, no se lanzará la consulta.

## Comportamiento de Datos

- Cada fila representa a un alumno.
- Cada columna de actividad usa el nombre visible de la actividad.
- Si una actividad no tiene nota para un alumno, la celda queda vacía.
- Si hay nombres de actividades duplicados, se desambiguarán si fuera necesario, por ejemplo añadiendo el ID.
- La primera versión no forzará una columna de total del curso salvo que se obtenga de forma clara y consistente sin complicar el modelo.

## Concurrencia y Rendimiento

La carga de datos se hará en segundo plano para no bloquear la interfaz.

Consideraciones:

- cursos grandes pueden requerir tiempo de descarga y transformación;
- la pestaña debe mostrar progreso o estado de carga;
- los controles de exportación deben permanecer deshabilitados hasta que exista una previsualización válida.

## Manejo de Errores

Se contemplan estos casos:

- sin filtros seleccionados:
  - mostrar aviso y no consultar;
- error de permisos o red en Canvas:
  - reutilizar `error_message` de `CanvasClient` y mostrar un mensaje claro;
- sin resultados para el filtro:
  - mostrar aviso o tabla vacía y bloquear exportación;
- error al guardar el CSV:
  - informar al usuario sin descartar la previsualización ya calculada.

## Pruebas

Cobertura mínima deseada:

- expansión de grupos a actividades sin duplicados;
- construcción de columnas y filas con celdas vacías cuando falten notas;
- consistencia entre previsualización y exportación CSV;
- alta de la nueva pestaña sin romper las existentes;
- manejo razonable de respuestas vacías o errores de Canvas.

## Implementación por fases

### Fase 1

- nueva pestaña `Libro de notas`;
- carga de grupos y actividades;
- selección de filtros;
- consulta y previsualización;
- exportación CSV.

### Fase 2 opcional

Mejoras futuras posibles, fuera del alcance inicial:

- totales de curso;
- más filtros;
- ordenación de columnas o filas;
- paginación o virtualización para cursos muy grandes;
- compatibilidad más cercana con el CSV nativo de Canvas.

## Preguntas cerradas durante el diseño

- alcance: detalle del libro de notas, no solo resumen del curso;
- filtros iniciales: por actividades o grupos de actividades;
- consulta en app: previsualización simple antes de exportar;
- integración: pestaña nueva llamada `Libro de notas`.

## Decisión final

Se implementará una pestaña nueva `Libro de notas` que consultará calificaciones por alumno para un subconjunto de actividades del curso usando la API de submissions agrupadas por alumno, con previsualización simple y exportación CSV basada en el mismo dataset.
