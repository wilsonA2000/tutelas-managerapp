"""Contexto organizacional de la Secretaría de Educación de Santander.

Este módulo provee información estructurada sobre la SEC para que
el agente de IA pueda responder preguntas sobre la organización,
oficinas responsables y distribución de tutelas.
"""

SEC_INFO = {
    "nombre": "Secretaría de Educación de Santander",
    "secretaria": "Karina Araujo Maestre",
    "cargo_secretaria": "Psicóloga con Maestría en Neuropsicología Clínica",
    "email": "educacion@santander.gov.co",
    "direccion": "Calle 37 No. 10-30, Bucaramanga",
    "telefono": "(607) 6985868 ext. 1420-1491",
    "mision": (
        "Contribuir al crecimiento sostenible garantizando el acceso al servicio educativo "
        "y la permanencia de los estudiantes en los municipios no certificados, con calidad, "
        "eficiencia, equidad e inclusión."
    ),
    "direcciones": {
        "Dirección Administrativa y Financiera": {
            "director": "Luis Jesús Fuentes Muñoz",
            "funcion": "Administración de recursos financieros, presupuesto, contabilidad, tesorería y bienes de la SEC.",
            "grupos": [
                "Equipo de Contabilidad",
                "Equipo de Presupuesto",
                "Equipo de Tesorería",
                "Equipo Fondo de Servicios Educativos",
                "Grupo de Bienes y Servicios",
                "Grupo Financiero",
            ],
        },
        "Dirección Estratégica": {
            "director": "Leilyn Yazmin Gómez Ordoñez",
            "funcion": "Planeación, sistemas de información, atención al ciudadano y desarrollo organizacional.",
            "grupos": [
                "Grupo de Planeación Educativa",
                "Grupo de Sistemas de Información",
                "Grupo de Atención al Ciudadano",
                "Grupo de Desarrollo Organizacional",
            ],
        },
        "Dirección de Permanencia Escolar": {
            "director": "Yenner Uribe Barón",
            "funcion": (
                "Garantizar la permanencia de estudiantes en el sistema educativo. "
                "Maneja inclusión educativa, cobertura, calidad, infraestructura, "
                "inspección y vigilancia."
            ),
            "grupos": [
                "Grupo de Cobertura Educativa",
                "Grupo de Calidad Educativa",
                "Grupo de Infraestructura Educativa",
                "Grupo de Inspección y Vigilancia",
            ],
        },
        "Dirección de Talento Humano Docente": {
            "director": "Rolando Rodríguez Mantilla",
            "funcion": (
                "Administración del recurso humano docente: nombramientos, traslados, "
                "carrera docente, nómina, prestaciones, escalafón, historias laborales."
            ),
            "grupos": [
                "Grupo Administración de Planta",
                "Grupo Carrera Docente",
                "Grupo Desarrollo Docente",
                "Grupo de Nómina",
                "Grupo de Prestaciones Sociales del Magisterio",
                "Grupo de Historias Laborales",
            ],
        },
    },
    "grupo_juridico": {
        "nombre": "Grupo de Apoyo Jurídico",
        "funcion": (
            "Responde TODAS las tutelas que llegan a la Secretaría de Educación. "
            "Coordina con la oficina temática correspondiente para obtener insumos "
            "técnicos y elaborar la respuesta jurídica."
        ),
        "nota": (
            "El Grupo de Apoyo Jurídico SIEMPRE es responsable de la respuesta legal. "
            "La 'oficina responsable' en el cuadro de tutelas indica cuál dependencia "
            "debe proporcionar los insumos técnicos, no quién responde la tutela."
        ),
    },
}


def get_sec_context() -> str:
    """Genera texto de contexto sobre la SEC para inyectar en prompts del agente."""
    lines = [
        f"## {SEC_INFO['nombre']}",
        f"Secretaria: {SEC_INFO['secretaria']}",
        f"Contacto: {SEC_INFO['email']} | {SEC_INFO['telefono']}",
        "",
        "### Estructura organizacional:",
    ]
    for dir_name, dir_info in SEC_INFO["direcciones"].items():
        lines.append(f"- **{dir_name}** ({dir_info['director']}): {dir_info['funcion']}")
        for grupo in dir_info["grupos"]:
            lines.append(f"  - {grupo}")
    lines.append("")
    lines.append(f"### {SEC_INFO['grupo_juridico']['nombre']}")
    lines.append(SEC_INFO["grupo_juridico"]["nota"])
    return "\n".join(lines)
