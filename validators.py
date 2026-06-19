import re

def validate_cross_references(article):
    errors = []
    warnings = []

    reference_keys = {
        ref.key for ref in article.references
        if ref.key
    }

    figure_labels = {
        fig.label for fig in article.figures
        if fig.label
    }

    table_labels = {
        table.label for table in article.tables
        if table.label
    }

    section_slugs = {
        section.slug for section in article.sections
        if section.slug
    }

    contents = []

    for section in article.sections:
        if section.content_md:
            contents.append((section.title or f"Sección {section.id}", section.content_md))

    for section_title, content in contents:
        # Citas bibliográficas: [cite:clave]
        cites = re.findall(r"\[cite:([^\]]+)\]", content)

        for cite_key in cites:
            cite_key = cite_key.strip()

            if cite_key not in reference_keys:
                errors.append(
                    f"La sección '{section_title}' cita '[cite:{cite_key}]', pero no existe una referencia con esa key."
                )

        # Figuras: [xref:fig:etiqueta]
        fig_refs = re.findall(r"\[xref:fig:([^\]]+)\]", content)

        for fig_label in fig_refs:
            fig_label = fig_label.strip()

            if fig_label not in figure_labels:
                errors.append(
                    f"La sección '{section_title}' referencia la figura '[xref:fig:{fig_label}]', pero no existe una figura con esa etiqueta."
                )

        # Tablas: [xref:table:etiqueta]
        table_refs = re.findall(r"\[xref:table:([^\]]+)\]", content)

        for table_label in table_refs:
            table_label = table_label.strip()

            if table_label not in table_labels:
                errors.append(
                    f"La sección '{section_title}' referencia la tabla '[xref:table:{table_label}]', pero no existe una tabla con esa etiqueta."
                )

        # Secciones: [xref:sec:slug]
        sec_refs = re.findall(r"\[xref:sec:([^\]]+)\]", content)

        for sec_slug in sec_refs:
            sec_slug = sec_slug.strip()

            if sec_slug not in section_slugs:
                errors.append(
                    f"La sección '{section_title}' referencia la sección '[xref:sec:{sec_slug}]', pero no existe una sección con ese slug."
                )

    return {
        "errors": errors,
        "warnings": warnings,
        "is_valid": len(errors) == 0
    }

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

    crossref_validation = validate_cross_references(article)

    errors.extend(crossref_validation["errors"])
    warnings.extend(crossref_validation["warnings"])

    return {
        "errors": errors,
        "warnings": warnings,
        "is_valid": len(errors) == 0
    }


def validate_article_completion(article):
    errors = []
    warnings = []

    if not article.titles:
        errors.append("El artículo debe tener al menos un título.")

    if not article.abstracts:
        errors.append("El artículo debe tener al menos un resumen.")

    if not article.authors:
        errors.append("El artículo debe tener al menos un autor.")

    if not article.sections:
        errors.append("El artículo debe tener al menos una sección.")

    if not article.references:
        errors.append("El artículo debe tener al menos una referencia bibliográfica.")

    if not article.journal:
        warnings.append("El artículo no tiene revista asociada.")

    if not article.doi:
        warnings.append("El artículo no tiene DOI.")

    if not article.keywords:
        warnings.append("El artículo no tiene palabras clave.")

    if not article.figures:
        warnings.append("El artículo no tiene figuras.")

    if not article.tables:
        warnings.append("El artículo no tiene tablas.")

    return {
        "errors": errors,
        "warnings": warnings,
        "is_valid": len(errors) == 0
    }