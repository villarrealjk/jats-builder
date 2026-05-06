# seed_journals.py (ejecútalo dentro del app context)
from models import db, Journal

def seed():
    if Journal.query.count() == 0:
        db.session.add_all([
            Journal(name="Revista Ejemplo A", abbrev_title="RevEjemA",
                    issn_print="1234-5678", issn_electronic="2345-6789",
                    publisher="Editorial Alfa", country="Colombia", default_lang="es"),
            Journal(name="International Sample Journal", abbrev_title="IntSamJ",
                    issn_print="1111-2222", issn_electronic="3333-4444",
                    publisher="Beta Press", country="USA", default_lang="en"),
        ])
        db.session.commit()
