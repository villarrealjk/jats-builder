from flask_sqlalchemy import SQLAlchemy
from datetime import datetime
from slugify import slugify
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin

db = SQLAlchemy()


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)

    username = db.Column(db.String(80), unique=True, nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=True)

    password_hash = db.Column(db.String(255), nullable=False)

    is_superuser = db.Column(db.Boolean, default=False)
    is_active_user = db.Column(db.Boolean, default=True)

    articles = db.relationship("Article", backref="user", lazy=True)

    @property
    def is_active(self):
        return self.is_active_user

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

# --- Catálogo de revistas (para precarga) ---
class Journal(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(255), nullable=False)          # Título de la revista
    abbrev_title = db.Column(db.String(255))                  # Abreviatura opcional
    issn_print = db.Column(db.String(32))
    issn_electronic = db.Column(db.String(32))
    publisher = db.Column(db.String(255))
    country = db.Column(db.String(64))
    default_lang = db.Column(db.String(8), default="es")

# --- Artículo ---
class Article(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    journal_id = db.Column(db.Integer, db.ForeignKey("journal.id"), nullable=True)
    doi = db.Column(db.String(255))
    language = db.Column(db.String(16), default="es")  # idioma principal
    pub_date = db.Column(db.Date, default=datetime.utcnow)

    # Paginación / localización
    fpage = db.Column(db.String(32))         # página inicial (impreso)
    lpage = db.Column(db.String(32))         # página final (impreso)
    elocation_id = db.Column(db.String(64))  # para artículos electrónicos

    journal = db.relationship("Journal", backref="articles")

    authors = db.relationship("Author", backref="article", cascade="all, delete-orphan")
    sections = db.relationship("Section", backref="article", cascade="all, delete-orphan", order_by="Section.order")
    figures = db.relationship("Figure", backref="article", cascade="all, delete-orphan")
    tables = db.relationship("TableWrap", backref="article", cascade="all, delete-orphan")
    references = db.relationship("Reference", backref="article", cascade="all, delete-orphan")

    # nuevo: colecciones multilingües
    titles = db.relationship("ArticleTitle", backref="article", cascade="all, delete-orphan")
    abstracts = db.relationship("ArticleAbstract", backref="article", cascade="all, delete-orphan")
    keywords = db.relationship("ArticleKeyword", backref="article", cascade="all, delete-orphan")

class ArticleTitle(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    lang = db.Column(db.String(8), nullable=False)  # ISO 639-1 o 639-2
    text = db.Column(db.String(1024), nullable=False)

class ArticleAbstract(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    lang = db.Column(db.String(8), nullable=False)
    text = db.Column(db.Text, nullable=False)

class ArticleKeyword(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    lang = db.Column(db.String(8), nullable=False)
    kwd = db.Column(db.String(255), nullable=False)

class Author(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    given_names = db.Column(db.String(255))
    surname = db.Column(db.String(255))
    orcid = db.Column(db.String(64))
    affiliation = db.Column(db.String(512))
    email = db.Column(db.String(255))

class Section(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    title = db.Column(db.String(512))
    slug = db.Column(db.String(256), index=True)
    content_md = db.Column(db.Text)  # guardamos texto con marcas ligeras
    order = db.Column(db.Integer, default=0)

    def ensure_slug(self):
        if not self.slug:
            self.slug = slugify(self.title or f"sec-{self.id}")

class Figure(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    label = db.Column(db.String(64))   # p.ej. "Fig. 1"
    caption = db.Column(db.Text)
    graphic_href = db.Column(db.String(512))  # ruta/URL del archivo

class TableWrap(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    label = db.Column(db.String(64))   # p.ej. "Tabla 1"
    caption = db.Column(db.Text)
    html_table = db.Column(db.Text)    # guardamos tabla como HTML simple

class Reference(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey('article.id'), nullable=False)
    key = db.Column(db.String(64), nullable=True)
    mixed_citation = db.Column(db.Text, nullable=True)
    doi = db.Column(db.String(128), nullable=True)
    pmid = db.Column(db.String(64), nullable=True)
    pub_type = db.Column(db.String(32), nullable=True, default='journal')

    # NUEVOS CAMPOS ESTRUCTURADOS
    label = db.Column(db.String(16), nullable=True)
    article_title = db.Column(db.Text, nullable=True)
    source = db.Column(db.String(255), nullable=True)
    volume = db.Column(db.String(32), nullable=True)
    issue = db.Column(db.String(32), nullable=True)
    fpage = db.Column(db.String(32), nullable=True)
    lpage = db.Column(db.String(32), nullable=True)
    year = db.Column(db.String(8), nullable=True)

    authors = db.relationship(
        "ReferenceAuthor",
        backref="reference",
        order_by="ReferenceAuthor.seq",
        cascade="all, delete-orphan"
    )

class ReferenceAuthor(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    reference_id = db.Column(db.Integer, db.ForeignKey('reference.id'), nullable=False)
    surname = db.Column(db.String(128), nullable=True)
    given_names = db.Column(db.String(128), nullable=True)
    seq = db.Column(db.Integer, default=1)  # orden dentro de la referencia

# Referencias cruzadas (xref) declarativas:
# - origen: dónde aparece la mención (p.ej. en una sección)
# - target_type: "fig" | "table" | "bibr" | "sec"
# - target_id: id real en su tabla
class CrossRef(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    article_id = db.Column(db.Integer, db.ForeignKey("article.id"), nullable=False)
    source_section_id = db.Column(db.Integer, db.ForeignKey("section.id"), nullable=True)
    target_type = db.Column(db.String(16), nullable=False)
    target_id = db.Column(db.Integer, nullable=False)
    label_text = db.Column(db.String(128))  # p.ej. "Fig. 1", "Tabla 2", "[23]"
