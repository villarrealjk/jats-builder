import re


def validate_article_for_jats(article):
    errors = []
    warnings = []

    # Título
    if not article.titles:
        errors.append("El artículo no tiene título.")

    # Resumen
    if not article.abstracts:
        warnings.append("El artículo no tiene resumen.")

    # Autores
    if not article.authors:
        errors.append("El artículo no tiene autores.")

    for author in article.authors:
        if not author.surname:
            errors.append("Hay un autor sin apellido.")
        if not author.given_names:
            warnings.append(f"El autor {author.surname or ''} no tiene nombres.")

        if author.orcid:
            orcid = author.orcid.replace("https://orcid.org/", "").strip()
            if not re.match(r"^\d{4}-\d{4}-\d{4}-\d{3}[\dX]$", orcid):
                warnings.append(f"ORCID inválido en autor {author.surname or ''}: {author.orcid}")

    # Secciones
    if not article.sections:
        warnings.append("El artículo no tiene secciones.")

    for section in article.sections:
        if not section.title:
            warnings.append("Hay una sección sin título.")
        if not section.content_md:
            warnings.append(f"La sección '{section.title or section.id}' no tiene contenido.")

    # Referencias
    for ref in article.references:
        if not ref.key:
            warnings.append(f"La referencia {ref.id} no tiene key.")
        if not ref.mixed_citation and not ref.article_title:
            warnings.append(f"La referencia {ref.key or ref.id} no tiene cita mixta ni título.")

        if ref.doi and not re.match(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$", ref.doi):
            warnings.append(f"DOI posiblemente inválido en referencia {ref.key or ref.id}: {ref.doi}")

    # DOI del artículo
    if article.doi and not re.match(r"^10\.\d{4,9}/[-._;()/:A-Za-z0-9]+$", article.doi):
        warnings.append(f"DOI del artículo posiblemente inválido: {article.doi}")

    return {
        "errors": errors,
        "warnings": warnings,
        "is_valid": len(errors) == 0
    }