"""Tests unitarios para el módulo RGPD."""

from python.rgpd import anonimizar, desanonimizar


def test_anonimizar_dni():
    texto = "El DNI del titular es 12345678A y el de su cónyuge 87654321B."
    resultado, mapeo = anonimizar(texto)
    assert "12345678A" not in resultado
    assert "87654321B" not in resultado
    assert "[DNI_1]" in resultado
    assert "[DNI_2]" in resultado


def test_anonimizar_email():
    texto = "Contactar en garcia.lopez@gmail.com o en mperez@outlook.es."
    resultado, mapeo = anonimizar(texto)
    assert "garcia.lopez@gmail.com" not in resultado
    assert "mperez@outlook.es" not in resultado
    assert "[EMAIL_1]" in resultado
    assert "[EMAIL_2]" in resultado


def test_anonimizar_telefono():
    texto = "Llamar al 612 345 678 o al +34 698 765 432."
    resultado, mapeo = anonimizar(texto)
    assert "612 345 678" not in resultado
    assert "698 765 432" not in resultado
    assert "[TELEFONO_1]" in resultado
    assert "[TELEFONO_2]" in resultado


def test_anonimizar_iban():
    texto = "Domiciliación en ES6621000418401234567891."
    resultado, mapeo = anonimizar(texto)
    assert "ES6621000418401234567891" not in resultado
    assert "[IBAN_1]" in resultado


def test_anonimizar_nombre():
    texto = "La familia de Carlos García tiene una deuda pendiente."
    resultado, mapeo = anonimizar(texto)
    assert "Carlos García" not in resultado
    assert "[NOMBRE_1]" in resultado


def test_anonimizar_multiples_tipos():
    texto = (
        "María López (DNI 23456789C, tel. 654 321 987, "
        "email maria.lopez@correo.com, IBAN ES7620770024003102575766) "
        "solicita devolución."
    )
    resultado, mapeo = anonimizar(texto)
    assert "23456789C" not in resultado
    assert "654 321 987" not in resultado
    assert "maria.lopez@correo.com" not in resultado
    assert "ES7620770024003102575766" not in resultado
    assert "María López" not in resultado


def test_desanonimizar_restaura_original():
    texto_original = "Pedro Martínez con DNI 11223344E y email pedro@mail.com."
    anonimizado, mapeo = anonimizar(texto_original)
    restaurado = desanonimizar(anonimizado, mapeo)
    assert restaurado == texto_original


def test_desanonimizar_multiples():
    texto_original = (
        "Ana Ruiz (87654321B) y Luis Fernández (12345678Z) "
        "deben 1.200€. Contacto: ana@mail.com, 611 222 333."
    )
    anonimizado, mapeo = anonimizar(texto_original)
    restaurado = desanonimizar(anonimizado, mapeo)
    assert restaurado == texto_original


def test_palabras_comunes_no_se_anonimizan():
    texto = "Estimado Don Ricardo, Buenos días."
    resultado, mapeo = anonimizar(texto)
    assert "Estimado" in resultado
    assert "Buenos" in resultado
