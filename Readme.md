# Canvas Auto

Aplicación de escritorio para automatizar tareas en la plataforma Canvas LMS, construida con Python y CustomTkinter.

## Características Actuales ✨

*   **Interfaz Gráfica Moderna**: Uso de `customtkinter` para una apariencia atractiva y fluida.
*   **Menú Principal tipo Dashboard**: Una vez seleccionado un curso, se presenta un menú principal de tarjetas interactivas y visuales que mejoran la experiencia de usuario.
*   **Iconos Personalizados**: Cada opción del menú cuenta con iconos únicos que representan su función.
*   **Gestión de Credenciales Simplificada**: Solicitud y almacenamiento local de las credenciales necesarias: URL de Canvas, token de API y clave de API de Google Gemini, todo desde la interfaz de inicio.
*   **Conexión y Verificación**: El cliente de API verifica que las credenciales sean válidas al conectarse.
*   **Selección de Cursos**: Muestra una lista de los cursos activos del usuario para que seleccione con cuál desea trabajar, con la opción de cambiar de curso sin reiniciar la aplicación.
*   **Módulos de Gestión por Submenús**:
    *   **Gestión de Quizzes**:
        *   Crear **Quizzes Clásicos** o **Nuevos Quizzes (New Quizzes)**.
        *   **Creación masiva de preguntas** para "Nuevos Quizzes" a partir de un formato JSON. El proceso ha sido actualizado para seguir las especificaciones más recientes de la API de Canvas, solucionando errores de creación y asegurando que las preguntas se añadan correctamente.
        *   Visualizar una lista completa de los quizzes existentes, manejando la paginación de la API para garantizar que no falte ninguno.
    *   **Gestión de Rúbricas**:
        *   Crear rúbricas a partir de texto, CSV o JSON.
        *   Soporte para **criterios con múltiples niveles de logro** (ratings).
        *   Admite **valores decimales** en puntuaciones, con coma o punto.
        *   Importar rúbricas desde **CSV exportados de Canvas** o creados manualmente.
        *   Exportar rúbricas existentes del curso a **CSV compatible** para su reutilización.
    *   **Gestión de Actividades**:
        *   Crear tareas definiendo nombre, puntos, descripción y tipos de entrega online.
        *   **Descarga Inteligente de Entregas**:
            *   Visualización de actividades **agrupadas por categorías** tal como en la plataforma.
            *   Al seleccionar una actividad, se muestra un **resumen previo** con el número de entregas, cuántas tienen PDF y si hay una rúbrica asociada.
            *   **Descarga automática de rúbricas** asociadas en formatos JSON y CSV.
            *   **Nombres de carpeta abreviados** y saneados para cursos y tareas, evitando errores de rutas largas en Windows.
        *   **Evaluación Asistida por IA (Gemini)**:
            *   Opción para evaluar automáticamente las entregas en PDF que tengan una rúbrica asociada.
            *   Utiliza un modelo multimodal (Gemini 1.5) para analizar el contenido del documento.
            *   **Selección de Modelo de IA**: Permite seleccionar el modelo de Gemini a utilizar (`gemini-1.5-pro` por defecto).
            *   Genera un archivo `evaluaciones_gemini.csv` con las puntuaciones y justificaciones detalladas para cada criterio.
        *   **Revisión y Carga de Calificaciones**:
            *   Nueva pestaña "Revisar y Cargar Notas" para gestionar el ciclo de calificación final.
            *   Permite cargar el archivo `evaluaciones_gemini.csv` generado por la IA.
            *   Muestra las evaluaciones en una tabla editable donde el profesor puede revisar y ajustar las puntuaciones y comentarios antes de publicarlos.
            *   Sube las calificaciones y comentarios seleccionados directamente a Canvas, aplicando la puntuación de la rúbrica a cada entrega.
*   **Registro de Eventos Detallado**: Posibilidad de activar un log que registra cada acción del usuario en `logs/gui_events.log`, ideal para depuración.

### Formato JSON para Preguntas de Quiz

Para usar la creación masiva de preguntas, proporciona un JSON con la siguiente estructura. Puedes pegar una lista de preguntas `[...]` o un objeto `{"items": [...]}`.

```json
{
  "items": [
    {
      "question": "Texto de la pregunta principal (ej: ¿Cuál es la capital de España?)",
      "choices": [
        "Barcelona",
        "Madrid",
        "Lisboa",
        "Sevilla"
      ],
      "correct": "B",
      "points": 1.5
    }
  ]
}
```

### Estructura del Proyecto

```
canvas_auto/
├── app/
│ ├── api/
│ │ ├── canvas_client.py    # Cliente para interactuar con la API de Canvas
│ │ └── gemini_client.py    # Cliente para la API de Google Gemini
│ ├── assets/
│ │ └── icons/
│ ├── gui/
│ │ ├── activities_menu.py  # Pantalla de gestión de actividades y calificaciones
│ │ ├── course_window.py    # Pantalla de selección de curso
│ │ ├── login_window.py     # Pantalla de inicio de sesión
│ │ ├── main_window.py      # Ventana principal del dashboard
│ │ ├── quizzes_menu.py     # Pantalla de gestión de quizzes
│ │ └── rubrics_menu.py     # Pantalla de gestión de rúbricas
│ └── utils/
│ ├── config_manager.py     # Gestión de configuración y credenciales
│ ├── event_logger.py       # Módulo para el registro de eventos de la GUI
│ └── logger_config.py      # Configuración del sistema de logs
├── logs/
│ └── canvas_auto.log
├── config.json
├── main.py
├── Readme.md
└── requirements.txt
```

## Instalación y Ejecución 🚀

1.  **Clonar el repositorio:**
    ```bash
    git clone <URL-de-tu-repositorio>
    cd canvas_auto
    ```

2.  **Crear y activar un entorno virtual (recomendado):**
    ```bash
    # Windows
    python -m venv .venv
    .venv\Scripts\activate

    # macOS / Linux
    python3 -m venv .venv
    source .venv/bin/activate
    ```

3.  **Instalar las dependencias:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Configurar las credenciales:**
    La primera vez que ejecutes la aplicación, se abrirá una ventana de configuración donde se te pedirá:
    *   Tu URL de Canvas.
    *   Un Token de API de Canvas.
    *   Tu clave de API de Google Gemini (opcional, para la evaluación con IA).
    
    Estos datos se guardarán en un archivo `config.json` para futuras sesiones. Opcionalmente, puedes editar este archivo más tarde para ajustar configuraciones avanzadas como el nivel de logs:
    ```json
    {
        "canvas_url": "https://tu-institucion.instructure.com",
        "api_token": "tu_token_de_api_de_canvas",
        "gemini_api_key": "tu_api_key_de_google_gemini",
        "enable_event_logging": true,
        "log_level": "DEBUG"
    }
    ```

5.  **Ejecutar la aplicación:**
    ```bash
    python main.py
    ```
