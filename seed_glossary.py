"""Seed the glossary with locked EN -> es-MX safety terms.
Run once: venv/bin/python seed_glossary.py"""
from app import app
from models import db, GlossaryTerm

TERMS = [
    ("full body harness", "arnés de cuerpo completo", "fall",
     "NEVER cinturón. A body belt is prohibited for fall arrest."),
    ("body belt", "cinturón de seguridad", "fall",
     "Distinct from harness. Not permitted for fall arrest."),
    ("lifeline", "línea de vida", "fall", ""),
    ("lanyard", "acollador", "fall", ""),
    ("anchorage", "anclaje", "fall", ""),
    ("guardrail", "barandal", "fall", ""),
    ("fall protection", "protección contra caídas", "fall", ""),
    ("scaffold", "andamio", "fall", ""),
    ("ladder", "escalera de mano", "fall", ""),
    ("wire rope", "cable de acero", "rigging",
     "Not cuerda de alambre."),
    ("hoist", "malacate", "rigging",
     "Not elevador or montacargas for a powered scaffold hoist."),
    ("counterweight", "contrapeso", "rigging", ""),
    ("competent person", "persona competente", "regulatory",
     "Defined regulatory term. Do not paraphrase."),
    ("qualified person", "persona calificada", "regulatory", ""),
    ("confined space", "espacio confinado", "confined", ""),
    ("permit-required confined space",
     "espacio confinado que requiere permiso", "confined", ""),
    ("atmospheric testing", "prueba atmosférica", "confined", ""),
    ("lockout/tagout", "bloqueo y etiquetado", "energy", ""),
    ("energized", "energizado", "energy", ""),
    ("respirator", "respirador", "resp", ""),
    ("air-purifying respirator", "respirador purificador de aire",
     "resp", ""),
    ("fit test", "prueba de ajuste", "resp", ""),
    ("personal protective equipment",
     "equipo de protección personal", "ppe",
     "Abbreviate as EPP after first use."),
    ("hard hat", "casco de seguridad", "ppe", ""),
    ("safety glasses", "gafas de seguridad", "ppe", ""),
    ("hearing protection", "protección auditiva", "ppe", ""),
    ("gloves", "guantes", "ppe", ""),
    ("heat illness", "enfermedad por calor", "heat", ""),
    ("heat stroke", "insolación", "heat", ""),
    ("heat exhaustion", "agotamiento por calor", "heat", ""),
    ("shade", "sombra", "heat", ""),
    ("lead", "plomo", "chem", ""),
    ("silica", "sílice", "chem", ""),
    ("asbestos", "asbesto", "chem", ""),
    ("safety data sheet", "hoja de datos de seguridad", "chem", ""),
    ("spill", "derrame", "chem", ""),
    ("hazard", "peligro", "general", ""),
    ("danger", "peligro", "general", "Signal word. Highest severity."),
    ("warning", "advertencia", "general", "Signal word."),
    ("caution", "precaución", "general", "Signal word."),
    ("supervisor", "supervisor", "general", ""),
    ("employee", "empleado", "general", ""),
    ("training", "capacitación", "general", "Not entrenamiento."),
    ("first aid", "primeros auxilios", "general", ""),
    ("emergency", "emergencia", "general", ""),
    ("evacuation", "evacuación", "general", ""),
    ("fire extinguisher", "extintor", "general", ""),
    ("inspection", "inspección", "general", ""),
    ("report", "reportar", "general", ""),
    ("bear spray", "repelente para osos", "wildlife",
     "Not gas pimienta, which is a different product."),
    ("mountain lion", "león de montaña", "wildlife", ""),
    ("wildlife agency", "agencia de vida silvestre", "wildlife", ""),
    ("scat", "excremento", "wildlife", ""),
    ("tracks", "huellas", "wildlife", ""),
    ("prey", "presa", "wildlife", ""),
]

with app.app_context():
    added = 0
    for en, es, domain, notes in TERMS:
        if GlossaryTerm.query.filter_by(term_en=en).first():
            continue
        db.session.add(GlossaryTerm(term_en=en, term_es=es,
                                    is_locked=True, domain=domain,
                                    notes=notes))
        added += 1
    db.session.commit()
    print("seeded %d terms" % added)
