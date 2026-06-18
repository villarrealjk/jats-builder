# jats_export.py
import os
from lxml import etree
from models import (
    Author, Section, Figure, TableWrap, Reference, CrossRef,
    ArticleTitle, ArticleAbstract, ArticleKeyword
)

XML_NS = "http://www.w3.org/XML/1998/namespace"
XLINK_NS = "http://www.w3.org/1999/xlink"

# Estilo global de citas: "numeric" (IEEE/Vancouver) o "apa" (autor-año)
DEFAULT_CITATION_STYLE = "apa"

def _el(name, text=None, **attrs):
    """
    Crea un elemento lxml Element con atributos serializados a str.
    Reemplaza '_' por '-' en los nombres de atributo normales
    (journal_id_type -> journal-id-type, pub_id_type -> pub-id-type, etc.).
    No toca las claves en notación de namespace ({...}lang, {…}href).
    """
    fixed_attrs = {}
    for k, v in attrs.items():
        if v is None:
            continue
        if k.startswith("{"):  # atributos con namespace explícito
            fixed_attrs[k] = str(v)
        else:
            fixed_attrs[k.replace("_", "-")] = str(v)

    e = etree.Element(name, **fixed_attrs)
    if text is not None:
        e.text = text
    return e


def _append_mixed_content(p_el, parts):
    if not parts:
        return
    if not isinstance(parts[0], str):
        parts = [""] + parts

    p_el.text = parts[0]
    for item in parts[1:]:
        if isinstance(item, str):
            if len(p_el) > 0:
                last = p_el[-1]
                last.tail = (last.tail or "") + item
            else:
                p_el.text = (p_el.text or "") + item
        else:
            p_el.append(item)

def normalize_table_for_jats(table_el):
    """
    Normaliza una tabla HTML para que sea más compatible con JATS:
    - mantiene <table>, <thead>, <tbody>, <tr>, <th>, <td>
    - agrega <colgroup>
    - agrega align="left"
    - limpia atributos no deseados
    - convierte textos internos correctamente
    """

    allowed_tags = {"table", "thead", "tbody", "tr", "th", "td", "colgroup", "col"}

    def clean_node(node):
        # Si hay etiquetas no permitidas dentro de celdas, conservar texto
        for child in list(node):
            if child.tag not in allowed_tags:
                text = "".join(child.itertext()).strip()

                if text:
                    if node.text:
                        node.text += " " + text
                    else:
                        node.text = text

                node.remove(child)
            else:
                clean_node(child)

        # Limpiar atributos no deseados
        allowed_attrs = {"align", "colspan", "rowspan"}
        for attr in list(node.attrib.keys()):
            if attr not in allowed_attrs:
                del node.attrib[attr]

    clean_node(table_el)

    # Agregar align="left" a th y td
    for cell in table_el.xpath(".//th|.//td"):
        if "align" not in cell.attrib:
            cell.set("align", "left")

    # Crear colgroup si no existe
    if table_el.find("colgroup") is None:
        first_row = table_el.find(".//tr")

        if first_row is not None:
            cells = first_row.findall("./th") or first_row.findall("./td")
            col_count = 0

            for cell in cells:
                colspan = cell.get("colspan")

                if colspan and colspan.isdigit():
                    col_count += int(colspan)
                else:
                    col_count += 1

            if col_count > 0:
                colgroup = etree.Element("colgroup")

                for _ in range(col_count):
                    colgroup.append(etree.Element("col"))

                table_el.insert(0, colgroup)

    # Si no tiene thead/tbody, intenta separar primera fila como thead
    has_thead = table_el.find("thead") is not None
    has_tbody = table_el.find("tbody") is not None

    direct_rows = table_el.findall("tr")

    if direct_rows and not has_thead and not has_tbody:
        first_row = direct_rows[0]
        remaining_rows = direct_rows[1:]

        table_el.remove(first_row)

        thead = etree.Element("thead")
        thead.append(first_row)

        tbody = etree.Element("tbody")

        for row in remaining_rows:
            table_el.remove(row)
            tbody.append(row)

        table_el.append(thead)

        if len(tbody):
            table_el.append(tbody)

    return table_el

def _build_ref_maps(article, citation_style="numeric"):
    """
    Devuelve:
      ref_key_map: key -> { rid, label, cite_text, number, ref }
      ref_id_map:  id  -> { rid, label, cite_text, number, ref }

    cite_text = lo que se verá en el <xref> dentro del cuerpo
      - numeric: "[n]"
      - apa: "(Apellido, Año)"
    label = lo que va en <label> dentro de <ref>. Para APA podemos seguir usando [n]
            si quieres mantener numeración en la lista, o dejarla vacía.
    """
    ref_key_map = {}
    ref_id_map = {}

    refs = list(article.references or [])
    for idx, r in enumerate(refs, start=1):
        key = (r.key or "").strip()
        rid = f"ref-{r.id}"

        # --- determinar label (para ref-list) ---
        label = r.label or f"[{idx}]"

        # --- determinar cite_text (lo que se ve en el cuerpo) ---
        if citation_style == "apa":
            # Autor-año sencillo
            authors = list(getattr(r, "authors", []) or [])
            surnames = [a.surname for a in authors if a.surname] if authors else []
            year = (r.year or "").strip() if getattr(r, "year", None) else ""

            if surnames:
                if len(surnames) == 1:
                    author_part = surnames[0]
                elif len(surnames) == 2:
                    author_part = f"{surnames[0]} & {surnames[1]}"
                else:
                    author_part = f"{surnames[0]} et al."
            else:
                # fallback si no hay autores: usa fuente o key
                author_part = r.source or key or "Autor"

            if year:
                core = f"{author_part}, {year}"
            else:
                core = author_part

            cite_text = f"({core})"
        else:
            # numeric
            cite_text = label

        info = {
            "rid": rid,
            "label": label,
            "cite_text": cite_text,
            "number": idx,
            "ref": r,
        }

        if key:
            ref_key_map[key] = info
        ref_id_map[r.id] = info

    return ref_key_map, ref_id_map

def _parse_inline_xrefs(text, article, ref_key_map=None):
    import re

    parts = []
    targets = []
    pos = 0

    pattern = re.compile(r'\[(xref|cite):(fig|table|sec)?\:?(.*?)\]')

    for m in pattern.finditer(text or ""):
        start, end = m.span()

        if start > pos:
            parts.append(text[pos:start])

        kind = (m.group(1) or "").strip()
        subtype = (m.group(2) or "").strip() if m.group(2) else None
        payload = (m.group(3) or "").strip()

        if kind == "cite":
            info = (ref_key_map or {}).get(payload)

            if info:
                x = _el(
                    "xref",
                    info["cite_text"],
                    ref_type="bibr",
                    rid=info["rid"]
                )
                parts.append(x)
            else:
                parts.append(f"[{payload}]")

        elif kind == "xref":
            if subtype == "fig":
                try:
                    fid = int(payload)
                    f = next((ff for ff in (article.figures or []) if ff.id == fid), None)

                    if f:
                        label = f.label or f"Figura {f.id}"
                        x = _el("xref", label, ref_type="fig", rid=f"fig-{f.id}")
                        parts.append(x)
                        targets.append(("fig", f.id))
                    else:
                        parts.append(f"[Fig {payload}]")
                except Exception:
                    parts.append(f"[Fig {payload}]")

            elif subtype == "table":
                try:
                    tid = int(payload)
                    t = next((tt for tt in (article.tables or []) if tt.id == tid), None)

                    if t:
                        label = t.label or f"Tabla {t.id}"
                        x = _el("xref", label, ref_type="table", rid=f"tbl-{t.id}")
                        parts.append(x)
                        targets.append(("table", t.id))
                    else:
                        parts.append(f"[Tabla {payload}]")
                except Exception:
                    parts.append(f"[Tabla {payload}]")

            elif subtype == "sec":
                target = None

                for s in (article.sections or []):
                    if str(s.id) == payload or (s.slug and s.slug == payload):
                        target = s
                        break

                if target:
                    label = target.title or "Sección"
                    slug = target.slug

                    if not slug or str(slug).lower() == "none":
                        slug = target.id

                    rid = f"sec-{slug}"
                    x = _el("xref", label, ref_type="sec", rid=rid)
                    parts.append(x)
                else:
                    parts.append(f"[Sección {payload}]")
            else:
                parts.append(m.group(0))
        else:
            parts.append(m.group(0))

        pos = end

    if text and pos < len(text):
        parts.append(text[pos:])

    if not parts:
        parts = [text or ""]
    elif not isinstance(parts[0], str):
        parts = [""] + parts

    return parts, targets

def build_fig_element(f):
    fig = _el("fig", id=f"fig-{f.id}")

    if f.label:
        fig.append(_el("label", f.label))

    if f.caption:
        cap = _el("caption")
        cap.append(_el("title", f.caption))
        fig.append(cap)

    if f.graphic_href:
        href = os.path.basename(f.graphic_href)
        g = _el("graphic", **({f"{{{XLINK_NS}}}href": href}))
        fig.append(g)

    return fig


def build_table_element(t):
    tw = _el("table-wrap", id=f"tbl-{t.id}")

    if t.label:
        tw.append(_el("label", t.label))

    if t.caption:
        cap = _el("caption")
        cap.append(_el("title", t.caption))
        tw.append(cap)

    if t.html_table:
        try:
            table_el = etree.fromstring(t.html_table.encode("utf-8"))
            table_el = normalize_table_for_jats(table_el)
            tw.append(table_el)
        except Exception:
            tw.append(_el("p", t.html_table))

    return tw


def build_jats_xml(article):
    # ---------- RAÍZ <article> con namespace xlink ----------
    nsmap = {"xlink": XLINK_NS}
    root = etree.Element("article", nsmap=nsmap)

    # Atributos básicos de artículo (puedes ajustar según tu modelo)
    root.set("article-type", getattr(article, "article_type", None) or "research")
    root.set("dtd-version", "1.1")
    root.set("specific-use", "production")
    if getattr(article, "language", None):
        root.set(f"{{{XML_NS}}}lang", article.language)

    # ---------- FRONT ----------
    front = _el("front")
    root.append(front)

    jm = _el("journal-meta")
    if article.journal:
        # 🔹 journal-id similar al XML ejemplo
        jcode = article.journal.abbrev_title or article.journal.issn_print or article.journal.name
        if jcode:
            jm.append(_el("journal-id", jcode, journal_id_type="publisher"))

        # Título y abreviatura
        jt = _el("journal-title-group")
        jt.append(_el("journal-title", article.journal.name))
        if article.journal.abbrev_title:
            jt.append(_el("abbrev-journal-title", article.journal.abbrev_title, abbrev_type="publisher"))
        jm.append(jt)

        # ISSN
        if article.journal.issn_print:
            jm.append(_el("issn", article.journal.issn_print, pub_type="ppub"))
        if article.journal.issn_electronic:
            jm.append(_el("issn", article.journal.issn_electronic, pub_type="epub"))

        # Publisher
        if article.journal.publisher:
            pub = _el("publisher")
            pub.append(_el("publisher-name", article.journal.publisher))
            # si quieres, puedes añadir aquí un publisher-loc con el país
            # if article.journal.country:
            #     pub.append(_el("publisher-loc", article.journal.country))
            jm.append(pub)

    front.append(jm)


    am = _el("article-meta")

    # 🔹 ID interno del artículo (publisher-id)
    am.append(_el("article-id", str(article.id), pub_id_type="publisher-id"))

    if article.titles:
        tg = _el("title-group")
        for t in article.titles:
            tg.append(_el("article-title", t.text, **({f"{{{XML_NS}}}lang": t.lang})))
        am.append(tg)

    if article.doi:
        am.append(_el("article-id", article.doi, pub_id_type="doi"))

    # ---------- AUTORES / CONTRIB-GROUP ----------
    if article.authors:
        contrib_group = _el("contrib-group")

        # Crear mapa de afiliaciones únicas
        aff_map = {}
        aff_counter = 1

        for au in article.authors:
            aff_text = (au.affiliation or "").strip()

            if aff_text and aff_text not in aff_map:
                aff_id = f"aff-{aff_counter}"
                aff_map[aff_text] = aff_id
                aff_counter += 1

        # Autores
        for au in article.authors:
            contrib = _el("contrib", contrib_type="author")

            # ORCID
            if au.orcid:
                orcid = au.orcid.strip()

                if orcid:
                    if not orcid.startswith("http"):
                        orcid = "https://orcid.org/" + orcid

                    contrib.append(_el(
                        "contrib-id",
                        orcid,
                        contrib_id_type="orcid"
                    ))

            # Nombre
            name = _el("name")

            if au.surname:
                name.append(_el("surname", au.surname))

            if au.given_names:
                name.append(_el("given-names", au.given_names))

            contrib.append(name)

            # Afiliación del autor
            aff_text = (au.affiliation or "").strip()
            if aff_text and aff_text in aff_map:
                aff_id = aff_map[aff_text]
                xref = _el("xref", ref_type="aff", rid=aff_id)
                xref.append(_el("sup", aff_id.replace("aff-", "")))
                contrib.append(xref)

            # Email
            if au.email:
                contrib.append(_el("email", au.email))

            contrib_group.append(contrib)

        # Afiliaciones
        for aff_text, aff_id in aff_map.items():
            aff = _el("aff", id=aff_id)
            label = aff_id.replace("aff-", "")
            aff.append(_el("label", label))
            aff.append(_el("institution", aff_text))
            contrib_group.append(aff)

        am.append(contrib_group)

    if article.fpage:
        am.append(_el("fpage", article.fpage))
    if article.lpage:
        am.append(_el("lpage", article.lpage))
    if article.elocation_id:
        am.append(_el("elocation-id", article.elocation_id))

    for ab in (article.abstracts or []):
        abs_el = _el("abstract", **({f"{{{XML_NS}}}lang": ab.lang}))
        abs_el.append(_el("p", ab.text))
        am.append(abs_el)

    if article.keywords:
        by_lang = {}
        for k in article.keywords:
            by_lang.setdefault(k.lang, []).append(k.kwd)
        for lg, kwds in by_lang.items():
            kg = _el("kwd-group", **({f"{{{XML_NS}}}lang": lg}))
            for kw in kwds:
                kg.append(_el("kwd", kw))
            am.append(kg)

    front.append(am)

    # ---------- MAPAS DE REFERENCIAS ----------
    citation_style = getattr(article, "citation_style", None) or DEFAULT_CITATION_STYLE
    ref_key_map, ref_id_map = _build_ref_maps(article, citation_style=citation_style)

    # ---------- BODY ----------
    body = _el("body")
    root.append(body)

    inserted_figures = set()
    inserted_tables = set()

    for s in (article.sections or []):
        sec_id = f"sec-{s.slug or s.id}"
        sec_el = _el("sec", id=sec_id)

        if s.title:
            sec_el.append(_el("title", s.title))

        raw_content = s.content_md or ""
        paragraphs = [p.strip() for p in raw_content.split("\n\n") if p.strip()]

        if not paragraphs and raw_content.strip():
            paragraphs = [raw_content.strip()]

        for paragraph in paragraphs:
            p = _el("p")
            parts, targets = _parse_inline_xrefs(
                paragraph,
                article,
                ref_key_map=ref_key_map
            )
            _append_mixed_content(p, parts)
            sec_el.append(p)

            for target_type, target_id in targets:
                if target_type == "fig" and target_id not in inserted_figures:
                    fig_obj = next((f for f in (article.figures or []) if f.id == target_id), None)

                    if fig_obj:
                        sec_el.append(build_fig_element(fig_obj))
                        inserted_figures.add(target_id)

                elif target_type == "table" and target_id not in inserted_tables:
                    table_obj = next((t for t in (article.tables or []) if t.id == target_id), None)

                    if table_obj:
                        sec_el.append(build_table_element(table_obj))
                        inserted_tables.add(target_id)

        body.append(sec_el)


    # ---------- BACK (ref-list) ----------
    if article.references:
        back = _el("back")
        ref_list = _el("ref-list")

        refs = list(article.references or [])
        for r in refs:
            info = ref_id_map.get(r.id, None)
            rid = info["rid"] if info else f"ref-{r.id}"
            label_text = info["label"] if info else (r.label or "")

            ref_el = _el("ref", id=rid)

            # label: para numérico se mantiene [n]; para APA podrías omitirlo si quieres.
            if citation_style == "numeric":
                lab_el = _el("label", label_text or "")
                ref_el.append(lab_el)
            else:
                # APA normalmente no muestra [n], pero puedes dejarlo si tu plataforma lo usa
                # descomenta si quieres:
                # lab_el = _el("label", label_text or "")
                # ref_el.append(lab_el)
                pass

            # mixed-citation
            mc_text = (r.mixed_citation or "").strip()
            if citation_style == "numeric":
                # prefija el número si no está
                if label_text and not mc_text.lstrip().startswith(label_text):
                    mc_text = f"{label_text} {mc_text}".strip()
            # en APA se asume que ya escribes la referencia en formato APA en mixed_citation

            mc_el = _el("mixed-citation", mc_text)
            if r.doi:
                mc_el.append(_el("pub-id", r.doi, pub_id_type="doi"))
            if r.pmid:
                mc_el.append(_el("pub-id", r.pmid, pub_id_type="pmid"))
            ref_el.append(mc_el)

            # element-citation (igual en ambos estilos)
            pubtype = r.pub_type or "journal"
            elcit = _el("element-citation", publication_type=pubtype)

            if hasattr(r, "authors") and r.authors:
                pg = _el("person-group", person_group_type="author")
                for a in r.authors:
                    if not (a.surname or a.given_names):
                        continue
                    name_el = _el("name")
                    if a.surname:
                        name_el.append(_el("surname", a.surname))
                    if a.given_names:
                        name_el.append(_el("given-names", a.given_names))
                    pg.append(name_el)
                elcit.append(pg)

            if getattr(r, "article_title", None):
                elcit.append(_el("article-title", r.article_title))
            if getattr(r, "source", None):
                elcit.append(_el("source", r.source))
            if getattr(r, "volume", None):
                elcit.append(_el("volume", r.volume))
            if getattr(r, "issue", None):
                elcit.append(_el("issue", r.issue))
            if getattr(r, "fpage", None):
                elcit.append(_el("fpage", r.fpage))
            if getattr(r, "lpage", None):
                elcit.append(_el("lpage", r.lpage))
            if getattr(r, "year", None):
                elcit.append(_el("year", r.year))

            if r.doi:
                elcit.append(_el("pub-id", r.doi, pub_id_type="doi"))
            if r.pmid:
                elcit.append(_el("pub-id", r.pmid, pub_id_type="pmid"))

            ref_el.append(elcit)
            ref_list.append(ref_el)

        back.append(ref_list)
        root.append(back)

    return etree.tostring(
        root,
        xml_declaration=True,
        encoding="UTF-8",
        pretty_print=True
    )
