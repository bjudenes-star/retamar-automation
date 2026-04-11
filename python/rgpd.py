"""Módulo RGPD: anonimización y desanonimización de datos personales."""

import re


def anonimizar(texto: str) -> tuple[str, dict[str, str]]:
    """Detecta datos personales en texto y los reemplaza con placeholders.

    Returns:
        (texto_anonimizado, mapeo) donde mapeo permite revertir la operación.
    """
    mapeo = {}
    contadores = {}

    def _reemplazar(match, tipo):
        valor = match.group(0)
        if valor in mapeo:
            return mapeo[valor]
        contadores[tipo] = contadores.get(tipo, 0) + 1
        placeholder = f"[{tipo}_{contadores[tipo]}]"
        mapeo[valor] = placeholder
        return placeholder

    # IBAN: ES seguido de 22 dígitos (con o sin espacios)
    texto = re.sub(
        r'\bES\d{2}[\s]?\d{4}[\s]?\d{4}[\s]?\d{2}[\s]?\d{10}\b',
        lambda m: _reemplazar(m, "IBAN"),
        texto,
    )

    # DNI/NIE
    texto = re.sub(
        r'\b[0-9XYZ]\d{7}[A-Z]\b',
        lambda m: _reemplazar(m, "DNI"),
        texto,
    )

    # Email
    texto = re.sub(
        r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b',
        lambda m: _reemplazar(m, "EMAIL"),
        texto,
    )

    # Teléfono español: +34 o prefijo opcional, 9 dígitos
    texto = re.sub(
        r'(?:\+34[\s.-]?)?\b[6-9]\d{2}[\s.-]?\d{3}[\s.-]?\d{3}\b',
        lambda m: _reemplazar(m, "TELEFONO"),
        texto,
    )

    # Nombres propios: secuencias de 2+ palabras capitalizadas (mínimo 2 letras cada una)
    # Excluir placeholders ya insertados y palabras comunes
    palabras_comunes = {
        "El", "La", "Los", "Las", "De", "Del", "En", "Con", "Por", "Para",
        "Un", "Una", "Que", "Se", "No", "Es", "Su", "Al", "Le", "Lo",
        "Don", "Doña", "Estimado", "Estimada", "Buenos", "Buenas", "Muy",
        "Señor", "Señora", "Colegio", "Centro",
    }

    def _es_nombre(match):
        partes = match.group(0).split()
        if any(p in palabras_comunes for p in partes):
            return match.group(0)
        return _reemplazar(match, "NOMBRE")

    texto = re.sub(
        r'\b[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{1,}\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{1,}(?:\s+[A-ZÁÉÍÓÚÑ][a-záéíóúñ]{1,})*\b',
        _es_nombre,
        texto,
    )

    # Invertir mapeo para desanonimizar: placeholder -> valor original
    mapeo_inverso = {v: k for k, v in mapeo.items()}
    return texto, mapeo_inverso


def desanonimizar(texto: str, mapeo: dict[str, str]) -> str:
    """Restaura un texto anonimizado usando el diccionario de mapeo."""
    for placeholder, original in mapeo.items():
        texto = texto.replace(placeholder, original)
    return texto
