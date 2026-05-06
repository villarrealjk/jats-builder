import os
import bleach
from dotenv import load_dotenv
from flask import Flask, render_template, request, redirect, url_for, send_file, flash, jsonify, abort
from flask_migrate import Migrate
from models import db, User, Article, Author, Section, Figure, TableWrap, Reference, ReferenceAuthor, CrossRef, Journal, ArticleTitle, ArticleAbstract, ArticleKeyword
from jats_export import build_jats_xml
from seed_journals import seed
from werkzeug.utils import secure_filename
from sqlalchemy.orm import selectinload
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from functools import wraps
from uuid import uuid4
from validators import validate_article_for_jats

# === Config de uploads (figuras) ===
ALLOWED_IMG = {"png", "jpg", "jpeg", "gif", "svg", "webp"}
BASE_DIR = os.path.dirname(__file__)
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
load_dotenv()

JATS_PUB_TYPES = [
    ("journal", "Journal Article"),
    ("book", "Book"),
    ("book-chapter", "Book Chapter"),
    ("confproc", "Conference Proceedings"),
    ("confpaper", "Conference Paper"),
    ("thesis", "Thesis/Dissertation"),
    ("report", "Report/Technical Report"),
    ("web", "Web Page"),
    ("dataset", "Dataset"),
    ("software", "Software"),
    ("standard", "Standard"),
    ("preprint", "Preprint"),
    ("patent", "Patent"),
    ("magazine", "Magazine Article"),
    ("newspaper", "Newspaper Article"),
    ("other", "Other (custom)"),
]

JATS_PUB_TYPE_KEYS = [v for (v, _label) in JATS_PUB_TYPES]


def allowed_file(filename: str) -> bool:
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_IMG

def create_app():
    app = Flask(__name__, instance_relative_config=True)
    database_url = os.getenv("DATABASE_URL", "sqlite:///app.db")

    if database_url.startswith("postgres://"):
        database_url = database_url.replace("postgres://", "postgresql://", 1)

    app.config["SQLALCHEMY_DATABASE_URI"] = database_url
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False
    app.config["SECRET_KEY"] = os.getenv("SECRET_KEY", "dev-only-change-me")
    os.makedirs(app.instance_path, exist_ok=True)
    os.makedirs(UPLOAD_DIR, exist_ok=True)  # <--- importante para subir imágenes
    db.init_app(app)
    Migrate(app, db)
    
    login_manager = LoginManager()
    login_manager.login_view = "login"
    login_manager.login_message = "Debes iniciar sesión."
    login_manager.init_app(app)

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    def superuser_required(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not current_user.is_authenticated:
                return redirect(url_for("login"))
            if not current_user.is_superuser:
                abort(403)
            return f(*args, **kwargs)
        return decorated_function

    def get_article_or_403(article_id):
        article = Article.query.get_or_404(article_id)

        if current_user.is_superuser:
            return article

        if article.user_id != current_user.id:
            abort(403)

        return article

    @app.route("/login", methods=["GET", "POST"])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for("index"))

        if request.method == "POST":
            username = request.form.get("username", "").strip()
            password = request.form.get("password", "")

            user = User.query.filter_by(username=username).first()

            if not user or not user.check_password(password):
                flash("Usuario o contraseña incorrectos.")
                return redirect(url_for("login"))

            if not user.is_active_user:
                flash("Tu usuario está desactivado.")
                return redirect(url_for("login"))

            login_user(user)
            flash("Sesión iniciada.")
            return redirect(url_for("index"))

        return render_template("login.html")

    @app.route("/logout")
    @login_required
    def logout():
        logout_user()
        flash("Sesión cerrada.")
        return redirect(url_for("login"))

    @app.route("/")
    @login_required
    def index():
        if current_user.is_superuser:
            articles = Article.query.order_by(Article.id.desc()).all()
        else:
            articles = Article.query.filter_by(user_id=current_user.id).order_by(Article.id.desc()).all()

        return render_template("index.html", articles=articles)

    # --- Crear/editar artículo (datos front/metadata) ---
    @app.route("/article/new", methods=["GET", "POST"])
    @login_required
    def article_new():
        journals = Journal.query.order_by(Journal.name.asc()).all()
        if request.method == "POST":
            a = Article(
                user_id=current_user.id,
                journal_id = int(request.form.get("journal_id") or 0) or None,
                doi = request.form.get("doi"),
                language = request.form.get("language") or "es",
                fpage = request.form.get("fpage") or None,
                lpage = request.form.get("lpage") or None,
                elocation_id = request.form.get("elocation_id") or None,
            )
            db.session.add(a)
            db.session.flush()  # tenemos a.id

            # Títulos n-idiomas
            titles = request.form.getlist("title_text[]")
            titles_lang = request.form.getlist("title_lang[]")
            for txt, lg in zip(titles, titles_lang):
                if txt.strip():
                    db.session.add(ArticleTitle(article_id=a.id, lang=lg.strip() or "es", text=txt.strip()))

            # Resúmenes n-idiomas
            abss = request.form.getlist("abs_text[]")
            abss_lang = request.form.getlist("abs_lang[]")
            for txt, lg in zip(abss, abss_lang):
                if txt.strip():
                    db.session.add(ArticleAbstract(article_id=a.id, lang=lg.strip() or "es", text=txt.strip()))

            # Palabras clave n-idiomas (cada input puede traer separadas por coma)
            kwds = request.form.getlist("kwd_text[]")
            kwds_lang = request.form.getlist("kwd_lang[]")
            for raw, lg in zip(kwds, kwds_lang):
                lang = lg.strip() or "es"
                for token in [k.strip() for k in raw.split(",") if k.strip()]:
                    db.session.add(ArticleKeyword(article_id=a.id, lang=lang, kwd=token))

            db.session.commit()
            flash("Artículo creado con metadatos multilingües.")
            return redirect(url_for("article_edit", article_id=a.id))
        return render_template("article_form.html", article=None, journals=journals)

    @app.route("/article/<int:article_id>/edit", methods=["GET", "POST"])
    @login_required
    def article_edit(article_id):
        a = (Article.query
            .options(
                selectinload(Article.titles),
                selectinload(Article.abstracts),
                selectinload(Article.keywords),
                selectinload(Article.authors),
                selectinload(Article.sections),
                selectinload(Article.figures),
                selectinload(Article.tables),
                selectinload(Article.references),
                selectinload(Article.journal),
            )
            .filter(Article.id == article_id)
            .first_or_404()
        )

        if not current_user.is_superuser and a.user_id != current_user.id:
            abort(403)

        journals = Journal.query.order_by(Journal.name.asc()).all()

        if request.method == "POST":
            a.journal_id = int(request.form.get("journal_id") or 0) or None
            a.doi = request.form.get("doi") or None
            a.language = request.form.get("language") or "es"
            a.fpage = request.form.get("fpage") or None
            a.lpage = request.form.get("lpage") or None
            a.elocation_id = request.form.get("elocation_id") or None

            # Limpiar títulos anteriores
            a.titles.clear()

            titles = request.form.getlist("title_text[]")
            titles_lang = request.form.getlist("title_lang[]")

            for txt, lg in zip(titles, titles_lang):
                txt = (txt or "").strip()
                lg = (lg or "").strip() or "es"

                if txt:
                    a.titles.append(ArticleTitle(
                        lang=lg,
                        text=txt
                    ))

            # Limpiar resúmenes anteriores
            a.abstracts.clear()

            abss = request.form.getlist("abs_text[]")
            abss_lang = request.form.getlist("abs_lang[]")

            for txt, lg in zip(abss, abss_lang):
                txt = (txt or "").strip()
                lg = (lg or "").strip() or "es"

                if txt:
                    a.abstracts.append(ArticleAbstract(
                        lang=lg,
                        text=txt
                    ))

            # Limpiar palabras clave anteriores
            a.keywords.clear()

            kwds = request.form.getlist("kwd_text[]")
            kwds_lang = request.form.getlist("kwd_lang[]")

            for raw, lg in zip(kwds, kwds_lang):
                raw = (raw or "").strip()
                lang = (lg or "").strip() or "es"

                for token in [k.strip() for k in raw.split(",") if k.strip()]:
                    a.keywords.append(ArticleKeyword(
                        lang=lang,
                        kwd=token
                    ))

            db.session.commit()

            flash("Metadatos actualizados.")
            return redirect(url_for("article_edit", article_id=a.id))

        return render_template("article_form.html", article=a, journals=journals)


    # --- API para precargar datos de revista ---
    @app.route("/api/journals/<int:jid>")
    def api_journal(jid):
        j = Journal.query.get_or_404(jid)
        return jsonify({
            "id": j.id, "name": j.name, "abbrev_title": j.abbrev_title,
            "issn_print": j.issn_print, "issn_electronic": j.issn_electronic,
            "publisher": j.publisher, "country": j.country, "default_lang": j.default_lang
        })
        
    # --- Autores ---
    @app.route("/article/<int:article_id>/authors/new", methods=["GET", "POST"])
    @login_required
    def author_new(article_id):
        article = get_article_or_403(article_id)

        if request.method == "POST":
            a = Author(
                article_id=article.id,
                given_names=request.form["given_names"],
                surname=request.form["surname"],
                orcid=request.form.get("orcid"),
                affiliation=request.form.get("affiliation"),
                email=request.form.get("email")
            )
            db.session.add(a)
            db.session.commit()

            flash("Autor agregado correctamente.")
            return redirect(url_for("article_edit", article_id=article.id))

        return render_template("author_form.html", article=article, author=None)

    @app.route("/author/<int:author_id>/edit", methods=["GET", "POST"])
    @login_required
    def author_edit(author_id):
        author = Author.query.get_or_404(author_id)
        article = get_article_or_403(author.article_id)

        if request.method == "POST":
            author.given_names = request.form["given_names"]
            author.surname = request.form["surname"]
            author.orcid = request.form.get("orcid")
            author.affiliation = request.form.get("affiliation")
            author.email = request.form.get("email")

            db.session.commit()
            flash("Autor actualizado.")
            return redirect(url_for("article_edit", article_id=article.id))

        return render_template("author_form.html", article=article, author=author)

    @app.route("/author/<int:author_id>/delete", methods=["POST"])
    @login_required
    def author_delete(author_id):
        author = Author.query.get_or_404(author_id)
        article = get_article_or_403(author.article_id)

        db.session.delete(author)
        db.session.commit()

        flash("Autor eliminado.")
        return redirect(url_for("article_edit", article_id=article.id))

    # --- Secciones ---
    @app.route("/article/<int:article_id>/sections/new", methods=["GET", "POST"])
    @login_required
    def section_new(article_id):
        a = get_article_or_403(article_id)

        if request.method == "POST":
            s = Section(
                article_id=a.id,
                title=request.form.get("title"),
                slug=request.form.get("slug") or None,
                content_md=request.form.get("content_md") or ""
            )
            db.session.add(s)
            db.session.commit()

            flash("Sección agregada.")
            return redirect(url_for("article_edit", article_id=a.id))

        _ = (a.sections, a.figures, a.tables, a.references)

        return render_template(
            "section_form.html",
            article=a,
            section=None,
            references=a.references
        )


    @app.route("/section/<int:section_id>/edit", methods=["GET", "POST"])
    @login_required
    def section_edit(section_id):
        s = Section.query.get_or_404(section_id)
        a = get_article_or_403(s.article_id)

        if request.method == "POST":
            s.title = request.form.get("title")
            s.slug = request.form.get("slug") or None
            s.content_md = request.form.get("content_md") or ""

            db.session.commit()

            flash("Sección actualizada.")
            return redirect(url_for("article_edit", article_id=a.id))

        _ = (a.sections, a.figures, a.tables, a.references)

        return render_template(
            "section_form.html",
            article=a,
            section=s,
            references=a.references
        )


    @app.route("/section/<int:section_id>/delete", methods=["POST"])
    @login_required
    def section_delete(section_id):
        s = Section.query.get_or_404(section_id)
        a = get_article_or_403(s.article_id)

        db.session.delete(s)
        db.session.commit()

        flash("Sección eliminada.")
        return redirect(url_for("article_edit", article_id=a.id))

    # --- Figuras ---
    @app.route("/article/<int:article_id>/figures/new", methods=["GET", "POST"])
    @login_required
    def figure_new(article_id):
        a = get_article_or_403(article_id)

        if request.method == "POST":
            file = request.files.get("graphic_file")
            href = request.form.get("graphic_href")
            final_href = None

            if file and allowed_file(file.filename):
                original_name = secure_filename(file.filename)
                ext = original_name.rsplit(".", 1)[1].lower()
                fname = f"{uuid4().hex}.{ext}"

                save_path = os.path.join(UPLOAD_DIR, fname)
                file.save(save_path)

                final_href = f"/static/uploads/{fname}"

            elif href:
                final_href = href.strip() or None

            f = Figure(
                article_id=a.id,
                label=request.form.get("label"),
                caption=request.form.get("caption"),
                graphic_href=final_href
            )

            db.session.add(f)
            db.session.commit()

            flash("Figura agregada.")
            return redirect(url_for("article_edit", article_id=a.id))

        return render_template("figure_form.html", article=a, figure=None)


    @app.route("/figure/<int:figure_id>/edit", methods=["GET", "POST"])
    @login_required
    def figure_edit(figure_id):
        f = Figure.query.get_or_404(figure_id)
        a = get_article_or_403(f.article_id)

        if request.method == "POST":
            file = request.files.get("graphic_file")
            href = request.form.get("graphic_href")
            final_href = f.graphic_href

            if file and allowed_file(file.filename):
                original_name = secure_filename(file.filename)
                ext = original_name.rsplit(".", 1)[1].lower()
                fname = f"{uuid4().hex}.{ext}"

                save_path = os.path.join(UPLOAD_DIR, fname)
                file.save(save_path)

                final_href = f"/static/uploads/{fname}"

            elif href:
                final_href = href.strip() or final_href

            f.label = request.form.get("label")
            f.caption = request.form.get("caption")
            f.graphic_href = final_href

            db.session.commit()

            flash("Figura actualizada.")
            return redirect(url_for("article_edit", article_id=a.id))

        return render_template("figure_form.html", article=a, figure=f)


    @app.route("/figure/<int:figure_id>/delete", methods=["POST"])
    @login_required
    def figure_delete(figure_id):
        f = Figure.query.get_or_404(figure_id)
        a = get_article_or_403(f.article_id)

        db.session.delete(f)
        db.session.commit()

        flash("Figura eliminada.")
        return redirect(url_for("article_edit", article_id=a.id))


    # --- Tablas ---
    @app.route("/article/<int:article_id>/tables/new", methods=["GET", "POST"])
    @login_required
    def table_new(article_id):
        a = get_article_or_403(article_id)

        if request.method == "POST":
            html = request.form.get("html_table") or ""
            safe_html = bleach.clean(
                html,
                tags=["table","thead","tbody","tr","th","td"],
                strip=True
            )

            t = TableWrap(
                article_id=a.id,
                label=request.form.get("label"),
                caption=request.form.get("caption"),
                html_table=safe_html,
            )

            db.session.add(t)
            db.session.commit()

            flash("Tabla agregada.")
            return redirect(url_for("article_edit", article_id=a.id))

        return render_template("table_form.html", article=a, table=None)


    @app.route("/table/<int:table_id>/edit", methods=["GET", "POST"])
    @login_required
    def table_edit(table_id):
        t = TableWrap.query.get_or_404(table_id)
        a = get_article_or_403(t.article_id)

        if request.method == "POST":
            t.label = request.form.get("label")
            t.caption = request.form.get("caption")
            html = request.form.get("html_table") or ""
            safe_html = bleach.clean(
                html,
                tags=["table","thead","tbody","tr","th","td"],
                strip=True
            )

            t.html_table = safe_html

            db.session.commit()

            flash("Tabla actualizada.")
            return redirect(url_for("article_edit", article_id=a.id))

        return render_template("table_form.html", article=a, table=t)


    @app.route("/table/<int:table_id>/delete", methods=["POST"])
    @login_required
    def table_delete(table_id):
        t = TableWrap.query.get_or_404(table_id)
        a = get_article_or_403(t.article_id)

        db.session.delete(t)
        db.session.commit()

        flash("Tabla eliminada.")
        return redirect(url_for("article_edit", article_id=a.id))

    # --- Referencias bibliográficas ---
    @app.route("/article/<int:article_id>/references/new", methods=["GET", "POST"])
    @login_required
    def reference_new(article_id):
        a = get_article_or_403(article_id)

        if request.method == "POST":
            key = (request.form.get("key") or "").strip() or None
            mixed = (request.form.get("mixed_citation") or "").strip() or None
            doi = (request.form.get("doi") or "").strip() or None
            pmid = (request.form.get("pmid") or "").strip() or None

            pub_type = (request.form.get("pub_type") or "journal").strip()
            if pub_type == "other":
                pub_type = (request.form.get("pub_type_other") or "").strip() or "other"

            label = (request.form.get("label") or "").strip() or None
            article_title = (request.form.get("article_title") or "").strip() or None
            source = (request.form.get("source") or "").strip() or None
            volume = (request.form.get("volume") or "").strip() or None
            issue = (request.form.get("issue") or "").strip() or None
            fpage = (request.form.get("fpage") or "").strip() or None
            lpage = (request.form.get("lpage") or "").strip() or None
            year = (request.form.get("year") or "").strip() or None

            if key and Reference.query.filter_by(article_id=a.id, key=key).first():
                flash("La clave (key) ya existe en este artículo. Usa otra.", "error")
                return render_template(
                    "reference_form.html",
                    article=a,
                    ref=None,
                    JATS_PUB_TYPES=JATS_PUB_TYPES,
                    JATS_PUB_TYPE_KEYS=JATS_PUB_TYPE_KEYS,
                )

            ref = Reference(
                article_id=a.id,
                key=key,
                mixed_citation=mixed,
                doi=doi,
                pmid=pmid,
                pub_type=pub_type or "journal",
                label=label,
                article_title=article_title,
                source=source,
                volume=volume,
                issue=issue,
                fpage=fpage,
                lpage=lpage,
                year=year,
            )

            db.session.add(ref)
            db.session.commit()

            if not ref.key:
                ref.key = f"ref-{ref.id}"
                db.session.commit()

            surnames = request.form.getlist("ref_author_surname[]")
            givens = request.form.getlist("ref_author_given[]")

            for idx, (sn, gn) in enumerate(zip(surnames, givens), start=1):
                sn = (sn or "").strip()
                gn = (gn or "").strip()

                if not sn and not gn:
                    continue

                db.session.add(ReferenceAuthor(
                    reference_id=ref.id,
                    surname=sn,
                    given_names=gn,
                    seq=idx,
                ))

            db.session.commit()

            flash("Referencia agregada.")
            return redirect(url_for("article_edit", article_id=a.id))

        return render_template(
            "reference_form.html",
            article=a,
            ref=None,
            JATS_PUB_TYPES=JATS_PUB_TYPES,
            JATS_PUB_TYPE_KEYS=JATS_PUB_TYPE_KEYS,
        )


    @app.route("/reference/<int:ref_id>/edit", methods=["GET", "POST"])
    @login_required
    def reference_edit(ref_id):
        ref = Reference.query.get_or_404(ref_id)
        a = get_article_or_403(ref.article_id)

        if request.method == "POST":
            new_key = (request.form.get("key") or "").strip() or None
            mixed = (request.form.get("mixed_citation") or "").strip() or None
            doi = (request.form.get("doi") or "").strip() or None
            pmid = (request.form.get("pmid") or "").strip() or None

            pub_type = (request.form.get("pub_type") or "journal").strip()
            if pub_type == "other":
                pub_type = (request.form.get("pub_type_other") or "").strip() or "other"

            label = (request.form.get("label") or "").strip() or None
            article_title = (request.form.get("article_title") or "").strip() or None
            source = (request.form.get("source") or "").strip() or None
            volume = (request.form.get("volume") or "").strip() or None
            issue = (request.form.get("issue") or "").strip() or None
            fpage = (request.form.get("fpage") or "").strip() or None
            lpage = (request.form.get("lpage") or "").strip() or None
            year = (request.form.get("year") or "").strip() or None

            if new_key and Reference.query.filter(
                Reference.article_id == a.id,
                Reference.key == new_key,
                Reference.id != ref.id
            ).first():
                flash("La clave (key) ya existe en este artículo. Usa otra.", "error")
                return render_template(
                    "reference_form.html",
                    article=a,
                    ref=ref,
                    JATS_PUB_TYPES=JATS_PUB_TYPES,
                    JATS_PUB_TYPE_KEYS=JATS_PUB_TYPE_KEYS,
                )

            ref.key = new_key or ref.key or f"ref-{ref.id}"
            ref.mixed_citation = mixed
            ref.doi = doi
            ref.pmid = pmid
            ref.pub_type = pub_type or "journal"
            ref.label = label
            ref.article_title = article_title
            ref.source = source
            ref.volume = volume
            ref.issue = issue
            ref.fpage = fpage
            ref.lpage = lpage
            ref.year = year

            for ra in list(ref.authors):
                db.session.delete(ra)

            db.session.flush()

            surnames = request.form.getlist("ref_author_surname[]")
            givens = request.form.getlist("ref_author_given[]")

            for idx, (sn, gn) in enumerate(zip(surnames, givens), start=1):
                sn = (sn or "").strip()
                gn = (gn or "").strip()

                if not sn and not gn:
                    continue

                db.session.add(ReferenceAuthor(
                    reference_id=ref.id,
                    surname=sn,
                    given_names=gn,
                    seq=idx,
                ))

            db.session.commit()

            flash("Referencia actualizada.")
            return redirect(url_for("article_edit", article_id=a.id))

        return render_template(
            "reference_form.html",
            article=a,
            ref=ref,
            JATS_PUB_TYPES=JATS_PUB_TYPES,
            JATS_PUB_TYPE_KEYS=JATS_PUB_TYPE_KEYS,
        )


    @app.route("/reference/<int:ref_id>/delete", methods=["POST"])
    @login_required
    def reference_delete(ref_id):
        ref = Reference.query.get_or_404(ref_id)
        a = get_article_or_403(ref.article_id)

        db.session.delete(ref)
        db.session.commit()

        flash("Referencia eliminada.")
        return redirect(url_for("article_edit", article_id=a.id))


    @app.route("/article/<int:article_id>/xref/add", methods=["POST"])
    @login_required
    def xref_add(article_id):
        a = get_article_or_403(article_id)

        cr = CrossRef(
            article_id=a.id,
            source_section_id=request.form.get("source_section_id"),
            target_type=request.form.get("target_type"),
            target_id=int(request.form.get("target_id")),
            label_text=request.form.get("label_text"),
        )

        db.session.add(cr)
        db.session.commit()

        flash("Referencia cruzada agregada.")
        return redirect(url_for("article_edit", article_id=a.id))


    # --- Vista previa (HTML simple) ---
    @app.route("/article/<int:article_id>/preview")
    @login_required
    def preview(article_id):
        article = get_article_or_403(article_id)

        return render_template("preview.html", article=article)


    @app.route("/api/article/<int:article_id>/xref-options")
    @login_required
    def api_xref_options(article_id):
        a = get_article_or_403(article_id)

        sections = [
            {"id": s.id, "slug": s.slug, "title": s.title or f"Sección {s.id}"}
            for s in (a.sections or [])
        ]

        figures = [
            {"id": f.id, "label": f.label or f"Fig. {f.id}", "href": f.graphic_href}
            for f in (a.figures or [])
        ]

        tables = [
            {"id": t.id, "label": t.label or f"Tabla {t.id}"}
            for t in (a.tables or [])
        ]

        references = [
            {"id": r.id, "key": (r.key or f"ref-{r.id}"), "preview": (r.mixed_citation or "")[:140]}
            for r in (a.references or [])
        ]

        return jsonify({
            "sections": sections,
            "figures": figures,
            "tables": tables,
            "references": references
        })


    # --- Exportar JATS XML ---
    @app.route("/article/<int:article_id>/export/jats.xml")
    @login_required
    def export_jats(article_id):
        a = get_article_or_403(article_id)

        validation = validate_article_for_jats(a)

        if not validation["is_valid"]:
            for error in validation["errors"]:
                flash(f"Error: {error}")

            for warning in validation["warnings"]:
                flash(f"Advertencia: {warning}")

            return redirect(url_for("article_edit", article_id=a.id))

        for warning in validation["warnings"]:
            flash(f"Advertencia: {warning}")

        xml_bytes = build_jats_xml(a)

        path = os.path.join(app.instance_path, f"article_{a.id}.xml")

        with open(path, "wb") as f:
            f.write(xml_bytes)

        return send_file(
            path,
            as_attachment=True,
            download_name=f"article_{a.id}.xml",
            mimetype="application/xml"
        )

    @app.cli.command("create-superuser")
    def create_superuser():
        username = input("Usuario: ").strip()
        email = input("Email: ").strip()
        password = input("Contraseña: ").strip()

        if User.query.filter_by(username=username).first():
            print("Ese usuario ya existe.")
            return

        user = User(
            username=username,
            email=email,
            is_superuser=True,
            is_active_user=True
        )
        user.set_password(password)

        db.session.add(user)
        db.session.commit()

        print("Superusuario creado correctamente.")

    @app.route("/admin/users")
    @login_required
    @superuser_required
    def admin_users():
        users = User.query.order_by(User.id.asc()).all()
        return render_template("admin_users.html", users=users)


    @app.route("/admin/users/new", methods=["GET", "POST"])
    @login_required
    @superuser_required
    def admin_user_new():
        if request.method == "POST":
            username = request.form.get("username", "").strip()
            email = request.form.get("email", "").strip() or None
            password = request.form.get("password", "").strip()
            is_superuser = request.form.get("is_superuser") == "on"

            if not username or not password:
                flash("Usuario y contraseña son obligatorios.")
                return redirect(url_for("admin_user_new"))

            if User.query.filter_by(username=username).first():
                flash("Ese usuario ya existe.")
                return redirect(url_for("admin_user_new"))

            user = User(
                username=username,
                email=email,
                is_superuser=is_superuser,
                is_active_user=True
            )
            user.set_password(password)

            db.session.add(user)
            db.session.commit()

            flash("Usuario creado correctamente.")
            return redirect(url_for("admin_users"))

        return render_template("admin_user_form.html")


    @app.route("/admin/users/<int:user_id>/toggle-active", methods=["POST"])
    @login_required
    @superuser_required
    def admin_user_toggle_active(user_id):
        user = User.query.get_or_404(user_id)

        if user.id == current_user.id:
            flash("No puedes desactivar tu propio usuario.")
            return redirect(url_for("admin_users"))

        user.is_active_user = not user.is_active_user
        db.session.commit()

        flash("Estado del usuario actualizado.")
        return redirect(url_for("admin_users"))


    @app.route("/admin/users/<int:user_id>/toggle-superuser", methods=["POST"])
    @login_required
    @superuser_required
    def admin_user_toggle_superuser(user_id):
        user = User.query.get_or_404(user_id)

        if user.id == current_user.id:
            flash("No puedes quitarte tus propios permisos de superusuario.")
            return redirect(url_for("admin_users"))

        user.is_superuser = not user.is_superuser
        db.session.commit()

        flash("Permisos del usuario actualizados.")
        return redirect(url_for("admin_users"))
    
    
    return app

if __name__ == "__main__":
    app = create_app()
    with app.app_context():
        db.create_all()
        seed()
    app.run(debug=os.getenv("FLASK_DEBUG", "0") == "1")
