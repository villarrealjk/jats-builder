# seed_journals.py (ejecútalo dentro del app context)
from models import db, Journal

def seed():
    if Journal.query.count() == 0:
        db.session.add_all([
            Journal(name="Computer and Electronic Sciences: Theory and Applications", abbrev_title="CESTA",
                    issn_print="", issn_electronic="2745-0090",
                    publisher="Universidad de la Costa", country="Colombia", default_lang="en"),
            Journal(name="Journal of Applied Cognitive Neuroscience", abbrev_title="J. Appl. Cogn. Neurosci.",
                    issn_print="", issn_electronic="2745-0031",
                    publisher="Universidad de la Costa", country="Colombia", default_lang="en"),
            Journal(name="Latin American Developments in Energy Engineering", abbrev_title="LADEE Lat. Am. Dev. Energy Eng.",
                    issn_print="", issn_electronic="2744-9750",
                    publisher="Universidad de la Costa", country="Colombia", default_lang="es"),
            Journal(name="Inge CUC", abbrev_title="Inge CUC",
                    issn_print="0122-6517", issn_electronic="2382-4700",
                    publisher="Universidad de la Costa", country="Colombia", default_lang="es"),
            Journal(name="Económicas CUC", abbrev_title="Económicas CUC",
                    issn_print="0120-3932", issn_electronic="2382-3860",
                    publisher="Universidad de la Costa", country="Colombia", default_lang="es"),
            Journal(name="Módulo arquitectura - CUC", abbrev_title="Módulo arquitectura - CUC",
                    issn_print="0124-6542", issn_electronic="2389-7732",
                    publisher="Universidad de la Costa", country="Colombia", default_lang="es"),
            Journal(name="Jurídicas CUC", abbrev_title=" Jurídicas CUC",
                    issn_print="1692-3030", issn_electronic="2389-7716",
                    publisher="Universidad de la Costa", country="Colombia", default_lang="es"),
            Journal(name="Cultura Educación y Sociedad", abbrev_title="Cult. Educ. Soc.",
                    issn_print="2145-9258", issn_electronic="2389-7724",
                    publisher="Universidad de la Costa", country="Colombia", default_lang="es"),
        ])
        db.session.commit()
