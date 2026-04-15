"""
=============================================================================
RG Ontology Population Pipeline — GLiNER2 (Ablass-focused)
=============================================================================

Strictly follows the WebProtégé ontology structure as observed in output.ttl.

RDF structure produced (matching gold standard exactly):
─────────────────────────────────────────────────────
  Regest (WP.RG_XXXXXXXX)
    hat_Bestandteil_RG → Header_RG (WP.RG_XXXXXXXX-0)
    hat_Bestandteil_RG → Sublemma_RG (WP.RG_XXXXXXXX-N_date_-_Ablass)
    hat_Nummer         → integer
    rg_Originaltext    → full combined text

  Header_RG (WP.RG_XXXXXXXX-0)
    rg_Originaltext    → header text only (e.g. "Aschersleve")
    hat_Petent         → Petent  [only in person-centric entries]
    hat_Akteur         → Petent

  Sublemma_RG (WP.RG_XXXXXXXX-N_date_-_Ablass)
    rg_Originaltext    → subentry text only
    stringInRG         → abbreviated RG text as in source
    has_RG_ID_Sublemma → "XXXXXXXX-N"
    Datum              → date string
    hat_Zentrale_Aktivitaet → Ablass individual
    hat_Fundstelle     → Fundstelle individual(s)
    hat_Ort            → Ort individual
    erwaehnte_Entitaet → Person_explizit individual(s)

  Ablass / Plenarablass / Ad-instar-Ablass / Jubilaeumsablass
    rdfs:label         → "Ablass für [institution] (RG XXXXXXXX-N)"
    skos:definition    → "Zentrale Aktivität in RG XXXXXXXX-N"
    rg_Originaltext    → abbreviated act text
    hat_Ablassempfaenger → Kirchliche_Institution  [one or more]
    hat_Vorbild        → Kirchliche_Institution    [ad-instar only]
    Dauer_gewaehrt     → Dauer individual
    Dauer_beantragt    → Dauer individual
    hat_Ablassdauer    → Dauer individual(s)
    hat_Ablassgeber    → literal (pope name)
    hat_Ablasshoehe    → literal (indulgence degree)

  Kirchliche_Institution (Kirche/Pfarrkirche/Kapelle/Kloster/…)
    rdfs:label         → Latin name as in text
    hat_Patrozinium    → literal (saint dedication)
    hat_Dioezese       → Dioezese individual

  Dioezese / Erzdioezese
    rdfs:label         → diocese name as in text

  Fundstelle
    rdfs:label         → "date register folio" (e.g. "26 apr. 1394 L 1 103v")
    has_source         → folio reference string

  Person_explizit
    rdfs:label         → name as in text

─────────────────────────────────────────────────────
THREE-STAGE DETECTION:

  Stage 1 — GLiNER2 classify_text()
    Classifies ALL subentries. Determines the correct Gnadenerweis
    subclass from the ontology. Non-Ablass types are recorded as
    hat_Weitere_Aktivitaet with the appropriate class.

  Stage 2 — GLiNER2 extract_json()
    Runs only on confirmed Ablass/Beichtbrief entries.
    Fields map 1:1 to ontology properties.

Usage:
    python rg_ablass_pipeline.py --input rg_sublema_test.json --output rg_gliner2_output.ttl
    python rg_ablass_pipeline.py --input rg_sublema_test.json --output rg_gliner2_output.ttl --verbose

Dependencies:
    pip install gliner2 rdflib tqdm
=============================================================================
"""

import argparse
import json
import re
import sys
import unicodedata
import uuid
from pathlib import Path

from rdflib import Graph, Literal, Namespace, URIRef, RDF, RDFS, OWL, XSD
from rdflib.namespace import SKOS

try:
    from tqdm import tqdm
    HAS_TQDM = True
except ImportError:
    HAS_TQDM = False

try:
    from gliner2 import GLiNER2
except ImportError:
    print("Error: gliner2 not installed. Run: pip install gliner2")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Namespaces
# ---------------------------------------------------------------------------
WP   = Namespace("http://webprotege.stanford.edu/")
RGA  = Namespace("https://dhi-roma.it/rg_a#")
TIME = Namespace("http://www.w3.org/2006/time#")
DC   = Namespace("http://purl.org/dc/elements/1.1/")


# ---------------------------------------------------------------------------
# Ontology classes
# ---------------------------------------------------------------------------
C = {
    "Regest":                WP.Regest,
    "Sublemma_RG":           WP.Sublemma_RG,
    "Header_RG":             WP.Header_RG,
    "Gnadenerweis":          WP.Gnadenerweis,
    "Ablass":                WP.Ablass,
    "Plenarablass":          WP.Plenarablass,
    "AdInstarAblass":        WP["Ad-instar-Ablass"],
    "Jubilaeumsablass":      WP.Jubilaeumsablass,
    "Beichtbrief":           WP.Beichtbrief_mit_Suendenablass,
    "Person":                WP.Person,
    "Person_explizit":       WP.Person_explizit,
    "Petent":                WP.Petent,
    "Supplikant":            WP.Supplikant,
    "Kirchliche_Institution":WP.Kirchliche_Institution,
    "Kirche":                WP.Kirche,
    "Pfarrkirche":           WP.Pfarrkirche,
    "Kapelle":               WP.Kapelle,
    "Kloster":               WP.Kloster,
    "Abtei":                 WP.Abtei,
    "Stift":                 WP.Stift,
    "Kollegiatstift":        WP.Kollegiatstift,
    "Domstift":              WP.Domstift,
    "Hospital":              WP.Hospital,
    "Orden":                 WP.Orden,
    "Dioezese":              WP.Dioezese,
    "Erzdioezese":           WP.Erzdioezese,
    "Kirchliches_Amt":       WP.Kirchliches_Amt,
    "Weltliches_Amt":        WP.Weltliches_Amt,
    "Sozialer_Stand":        WP.Sozialer_Stand,
    "Ort":                   WP.Ort,
    "Dauer":                 WP.Dauer,
    "Fundstelle":            WP.Fundstelle,
}

# ---------------------------------------------------------------------------
# Object properties
# ---------------------------------------------------------------------------
P = {
    "hat_Bestandteil_RG":      WP.hat_Bestandteil_RG,
    "hat_Zentrale_Aktivitaet": WP.hat_Zentrale_Aktivitaet,
    "hat_Weitere_Aktivitaet":  WP.hat_Weitere_Aktivitaet,
    "hat_Ablassempfaenger":    WP.hat_Ablassempfaenger,
    "Dauer_gewaehrt":          WP.Dauer_gewaehrt,
    "Dauer_beantragt":         WP.Dauer_beantragt,
    "hat_Ablassdauer":         WP.hat_Ablassdauer,
    "hat_Petent":              WP.hat_Petent,
    "hat_Akteur":              WP.hat_Akteur,
    "hat_Amt":                 WP.hat_Amt,
    "hat_Dioezese":            WP.hat_Dioezese,
    "hat_Ort":                 WP.hat_Ort,
    "hat_Fundstelle":          WP.hat_Fundstelle,
    "hat_Vorbild":             WP.hat_Vorbild,
    "hat_Patrozinium":         WP.hat_Patrozinium,
    "hat_Sozialer_Stand":      WP.hat_Sozialer_Stand,
    "erwaehnte_Entitaet":      WP.erwaehnte_Entitaet,
    "amtierender_Papst":       WP.amtierender_Papst,
}

# Datatype properties
DP = {
    "rg_Originaltext":    WP.rg_Originaltext,
    "stringInRG":         WP.stringInRG,
    "has_RG_ID":          WP.has_RG_ID,
    "has_RG_ID_Header":   WP.has_RG_ID_Header,
    "has_RG_ID_Sublemma": WP.has_RG_ID_Sublemma,
    "hat_Ablassgeber":    WP.hat_Ablassgeber,
    "hat_Ablasshoehe":    WP.hat_Ablasshoehe,
    "hat_Nummer":         WP.hat_Nummer,
    "Datum":              WP.Datum,
    "has_source":         WP.has_source,
    "time_years":         TIME.years,
    "time_months":        TIME.Monate,
}


# ---------------------------------------------------------------------------
# STAGE 1 — GLiNER2 classification schema
# Aligned with Gnadenerweis hierarchy from the ontology.
# ---------------------------------------------------------------------------
# Maps each act_type label to its OWL class in the ontology
# Used to set rdf:type on the Gnadenerweis individual
ACT_TYPE_CLASS = {
    # WP.Ablass subclasses — full extraction in Stage 2
    "indulgence_central":   None,   # subtype resolved in Stage 2 (indulgentia/ad_instar/plenary/jubilee)
    "beichtbrief":          WP.Beichtbrief_mit_Suendenablass,
    # Other Gnadenerweis subclasses — recorded but not fully extracted
    "indulgence_secondary": WP.Ablass,
    "dispensation":         WP.Dispens,
    "licence_licentia":     WP["Erlaubnis_(licentia)"],
    "benefice_provision":   WP.Gnadenerweis,   # no specific class for Provision in ontology
    "privilege_mandate":    WP.Gnadenerweis,
    "incorporation":        WP.Gnadenerweis,
    "other":                WP.Gnadenerweis,
}

CLASSIFY_SCHEMA = {
    "act_type": [
        # WP.Ablass subclasses (stringInRG: "indulg.", "plen. indulg.", etc.)
        "indulgence_central",    # institution:indulg. — the institution IS the act subject
        "beichtbrief",           # lit. confess. / rem. plen. — WP.Beichtbrief_mit_Suendenablass
        # Other Gnadenerweis subclasses from the ontology
        "indulgence_secondary",  # indulg. appears but as a secondary act, not the main topic
        "dispensation",          # disp. sup. — WP.Dispens
        "licence_licentia",      # lic. — WP.Erlaubnis_(licentia)
        "benefice_provision",    # m. prov. / prov. — benefice/canonicate provision
        "privilege_mandate",     # privil. / mand. — privilege or mandate
        "incorporation",         # incorp. — incorporation of a church
        "other",                 # anything else
    ]
}

# These get full Stage 2 extraction
ABLASS_LABELS = {"indulgence_central", "beichtbrief"}
# These get a minimal Sublemma_RG triple with hat_Zentrale_Aktivitaet → Gnadenerweis individual
NON_ABLASS_LABELS = {
    "indulgence_secondary", "dispensation", "licence_licentia",
    "benefice_provision", "privilege_mandate", "incorporation", "other"
}


# ---------------------------------------------------------------------------
# STAGE 2 — GLiNER2 extraction schema (fields map to ontology properties)
# ---------------------------------------------------------------------------
EXTRACT_SCHEMA = {
    "ablass_act": [

        # ── Ablass subtype → OWL class ────────────────────────────────────
        "ablass_subtype::[indulgentia|ad_instar|plenary|jubilee|beichtbrief|other]::str::"
        "Subtype of the indulgence, detected from the Latin abbreviations in the text: "
        "'indulg. ad instar' → ad_instar. "
        "'plen. indulg.' or 'rem. plen.' → plenary. "
        "'indulg. iubilei' → jubilee. "
        "'lit. confess.' or 'rem.' → beichtbrief. "
        "Otherwise → indulgentia (generic). "
        "Maps to OWL subclass of WP.Ablass.",

        # ── Recipient institutions → hat_Ablassempfaenger (one or more!) ──
        "recipient_institutions::list::"
        "ALL church institutions that receive the indulgence — list ALL of them. "
        "In a single grant there can be multiple institutions (e.g. several churches "
        "in the same city). Extract each as a separate item with the Latin name verbatim: "
        "'eccl. mai.' (cathedral), 'eccl. s. Johannis in Monte', 'capella b. Marie', "
        "'dom. fr. herem. s. Aug.', 'mon. s. Petri'. "
        "Maps to: Kirchliche_Institution → hat_Ablassempfaenger (one per institution).",

        "recipient_institution_types::list::"
        "OWL subclass for each institution in recipient_institutions (same order). "
        "Values: Kirche | Pfarrkirche | Kapelle | Kloster | Abtei | Stift | "
        "Kollegiatstift | Domstift | Hospital | Orden | Kirchliche_Institution. "
        "'par. eccl.' → Pfarrkirche. 'capella' → Kapelle. "
        "'mon.' or 'dom. fr.' → Kloster. 'eccl. mai.' → Domstift. "
        "'eccl.' alone → Kirche.",

        "recipient_patrozinia::list::"
        "Saint dedication for each institution in recipient_institutions (same order). "
        "Empty string if unknown. "
        "Examples: 's. Petri', 'b. Marie virginis', 'ss. Petri et Pauli', 's. Augustini'. "
        "Maps to: hat_Patrozinium (literal on institution).",

        "recipient_diocese::str::"
        "Diocese of the recipient institution(s). "
        "Examples: 'Magdeburgensis', 'Halberstadensis', 'Brandenburgensis', 'Mesnensis'. "
        "Maps to: Dioezese → hat_Dioezese on institution.",

        # ── Ad-instar reference → hat_Vorbild ─────────────────────────────
        "ad_instar_model::str::"
        "ONLY for ad_instar subtype: the church whose indulgence is being replicated. "
        "'indulg. ad instar eccl. s. Marie in Portiuncula' → 'eccl. s. Marie in Portiuncula'. "
        "Maps to: Kirchliche_Institution → hat_Vorbild on the Ablass individual.",

        # ── Duration → Dauer_gewaehrt / Dauer_beantragt ───────────────────
        "duration_granted::str::"
        "Duration of the indulgence as granted, verbatim from the text. "
        "Examples: '7 an.', '3 anni', '40 dies', 'quinquennium', 'in perpetuum'. "
        "Maps to: Dauer individual → Dauer_gewaehrt + hat_Ablassdauer.",

        "duration_requested::str::"
        "Duration requested by the petitioner if different from granted. "
        "Maps to: Dauer individual → Dauer_beantragt.",

        # ── Pope (Ablassgeber) ─────────────────────────────────────────────
        "ablass_giver::str::"
        "The pope granting the indulgence, if explicitly named in the text. "
        "Often not stated in abbreviated RG entries. "
        "Examples: 'Bonifaz IX', 'Martin V'. "
        "Maps to: hat_Ablassgeber (literal) on Ablass.",

        # ── Indulgence degree ──────────────────────────────────────────────
        "ablass_height::str::"
        "The degree or amount of indulgence if stated. "
        "Examples: '40 dies', '7 an.', 'plenam remissionem'. "
        "Maps to: hat_Ablasshoehe (literal) on Ablass.",

        # ── Source date → Datum on Sublemma, label on Fundstelle ──────────
        "source_date::str::"
        "Date of the document as it appears before the register reference. "
        "Keep verbatim: '26 apr. 1394', '5 iul. 1401', '17 dec. 1401'. "
        "Maps to: Datum on Sublemma_RG, and part of Fundstelle label.",

        # ── Source references → Fundstelle individuals ─────────────────────
        "source_references::list::"
        "All archival register references at end of entry. Extract each separately. "
        "Format: [register_letter] [volume] [folio]. "
        "Examples from 'L 1 103v et V 314 236v': ['L 1 103v', 'V 314 236v']. "
        "From 'L 94 199': ['L 94 199']. "
        "Maps to: Fundstelle individual → hat_Fundstelle on Sublemma_RG.",

        # ── Petitioner → hat_Petent on Header_RG (person-centric only) ────
        "petitioner_name::str::"
        "Name of the petitioner IF the entry is person-centric "
        "(i.e. the header contains a person's name, not a place name). "
        "In institution-centric entries (header = place like 'Aschersleve'), "
        "leave EMPTY. "
        "Example (person-centric): 'Albertus aep. Magdeburg'. "
        "Maps to: Petent → hat_Petent on Header_RG.",

        "petitioner_title::str::"
        "Ecclesiastical title of the petitioner if present. "
        "Examples: 'archiepiscopus', 'episcopus', 'canonicus', 'capellanus'. "
        "Maps to: Kirchliches_Amt → hat_Amt on Petent.",

        "petitioner_diocese::str::"
        "Diocese of the petitioner if stated. "
        "Maps to: Dioezese → hat_Dioezese on Petent.",

        # ── Other persons → erwaehnte_Entitaet on Sublemma_RG ─────────────
        "mentioned_persons::list::"
        "Other persons explicitly named besides the petitioner. "
        "Examples: 'Bartholomeo de Turchiis civi Lucan.', 'Rolando dec. eccl. s. Blasii'. "
        "Maps to: Person_explizit → erwaehnte_Entitaet on Sublemma_RG.",

        # ── Place → hat_Ort on Sublemma_RG ─────────────────────────────────
        "place::str::"
        "City or locality named in the text (not diocese). "
        "Often comes from the header in institution-centric entries. "
        "Examples: 'Magdeburg', 'Aschersleve', 'Barby', 'Grevenhayn'. "
        "Maps to: Ort → hat_Ort on Sublemma_RG.",
    ]
}


# ---------------------------------------------------------------------------
# URI helpers
# ---------------------------------------------------------------------------

def slugify(text: str, maxlen: int = 70) -> str:
    s = unicodedata.normalize("NFKD", str(text))
    s = s.encode("ascii", "ignore").decode("ascii")
    s = re.sub(r"[^\w\s-]", "", s).strip()
    s = re.sub(r"[\s_-]+", "_", s)
    return s[:maxlen] or uuid.uuid4().hex[:8]


def make_uri(label: str, suffix: str = "") -> URIRef:
    slug = slugify(label)
    return WP[f"{slug}_{suffix}"] if suffix else WP[slug]


def regest_uri(rg_id: str) -> URIRef:
    return WP[f"RG_{rg_id}"]


def header_uri(rg_id: str) -> URIRef:
    return WP[f"RG_{rg_id}-0"]


def sublemma_uri(rg_id: str, sub_id: str, date: str = "") -> URIRef:
    """
    Matches gold standard pattern: WP["RG_10200370-1_1394-04-26_-_Ablass"]
    """
    date_slug = slugify(date, 20) if date else ""
    if date_slug:
        return WP[f"RG_{rg_id}-{sub_id}_{date_slug}_-_Ablass"]
    return WP[f"RG_{rg_id}-{sub_id}_-_Ablass"]


def ablass_individual_uri(rg_id: str, sub_id: str, inst_name: str = "") -> URIRef:
    """
    Matches gold standard: WP["Ablass_fuer_das_Domstift_Magdeburg_etc_(RG_10200370-1)"]
    """
    if inst_name:
        slug = slugify(f"Ablass_fuer_{inst_name}")
    else:
        slug = f"Ablass_RG_{rg_id}_{sub_id}"
    return WP[f"{slug}_(RG_{rg_id}-{sub_id})"]


def fundstelle_uri(date: str, ref: str) -> URIRef:
    """
    Matches gold standard: WP["26_apr_1394_L_1_103v"]
    """
    combined = slugify(f"{date}_{ref}", 60)
    return WP[combined]


# ---------------------------------------------------------------------------
# RDF helpers
# ---------------------------------------------------------------------------

def add_individual(g: Graph, uri: URIRef, owl_class: URIRef,
                   label: str, lang: str = "de") -> None:
    g.add((uri, RDF.type, OWL.NamedIndividual))
    g.add((uri, RDF.type, owl_class))
    if label:
        g.add((uri, RDFS.label, Literal(label.strip(), lang=lang)))


def add_literal(g: Graph, subj: URIRef, prop: URIRef,
                value, datatype=None, lang: str = None) -> None:
    v = str(value).strip() if value is not None else ""
    if not v:
        return
    if lang:
        g.add((subj, prop, Literal(v, lang=lang)))
    elif datatype:
        g.add((subj, prop, Literal(v, datatype=datatype)))
    else:
        g.add((subj, prop, Literal(v)))


# ---------------------------------------------------------------------------
# Subtype → OWL class mapping
# ---------------------------------------------------------------------------
ABLASS_SUBTYPE_MAP = {
    "ad_instar":   C["AdInstarAblass"],
    "plenary":     C["Plenarablass"],
    "jubilee":     C["Jubilaeumsablass"],
    "beichtbrief": C["Beichtbrief"],
    "indulgentia": C["Ablass"],
    "other":       C["Ablass"],
}

INST_TYPE_MAP = {
    "Kirche":             C["Kirche"],
    "Pfarrkirche":        C["Pfarrkirche"],
    "Kapelle":            C["Kapelle"],
    "Kloster":            C["Kloster"],
    "Abtei":              C["Abtei"],
    "Stift":              C["Stift"],
    "Kollegiatstift":     C["Kollegiatstift"],
    "Domstift":           C["Domstift"],
    "Hospital":           C["Hospital"],
    "Orden":              C["Orden"],
    "Kirchliche_Institution": C["Kirchliche_Institution"],
}



# ---------------------------------------------------------------------------
# Build minimal RDF for non-Ablass subentries
# Records the correct Gnadenerweis subclass so the ontology is complete.
# ---------------------------------------------------------------------------

def build_non_ablass_triples(g: Graph, rg_id: str, sub_id: str,
                              header_text: str, sub_text: str,
                              act_type: str) -> None:
    """
    For non-Ablass subentries, creates:
      - Regest + Header_RG (same structure as Ablass)
      - Sublemma_RG with hat_Weitere_Aktivitaet (not hat_Zentrale_Aktivitaet)
        pointing to a Gnadenerweis individual of the correct subclass.
    This keeps the full ontology populated — no subentry is silently dropped.
    """
    rg_uri_ = regest_uri(rg_id)
    full_text = f"{header_text} || {sub_text}".strip(" |")
    add_individual(g, rg_uri_, C["Regest"], f"RG {rg_id}", lang="de")
    add_literal(g, rg_uri_, DP["rg_Originaltext"], full_text, lang="la")

    hdr_uri = header_uri(rg_id)
    add_individual(g, hdr_uri, C["Header_RG"], f"RG {rg_id}-0", lang="de")
    add_literal(g, hdr_uri, DP["rg_Originaltext"], header_text, lang="la")
    add_literal(g, hdr_uri, DP["has_RG_ID_Header"],
                f"{rg_id}-0", datatype=XSD.string)
    g.add((rg_uri_, P["hat_Bestandteil_RG"], hdr_uri))

    # Sublemma_RG — using act_type slug in URI so it is distinct from Ablass
    act_slug = act_type.replace("_", "-")
    sub_uri  = WP[f"RG_{rg_id}-{sub_id}_-_{act_slug}"]
    sub_label = f"RG {rg_id}-{sub_id} - {act_type.replace('_', ' ')}"
    add_individual(g, sub_uri, C["Sublemma_RG"], sub_label, lang="de")
    add_literal(g, sub_uri, DP["rg_Originaltext"], sub_text, lang="la")
    add_literal(g, sub_uri, DP["stringInRG"],       sub_text, lang="la")
    add_literal(g, sub_uri, DP["has_RG_ID_Sublemma"],
                f"{rg_id}-{sub_id}", datatype=XSD.string)
    g.add((rg_uri_, P["hat_Bestandteil_RG"], sub_uri))

    # Gnadenerweis individual with correct OWL subclass
    gnad_class = ACT_TYPE_CLASS.get(act_type, C["Gnadenerweis"])
    if gnad_class is None:
        gnad_class = C["Gnadenerweis"]
    gnad_uri   = WP[f"Gnadenerweis_RG_{rg_id}-{sub_id}_{act_slug}"]
    gnad_label = f"{act_type.replace('_', ' ').title()} (RG {rg_id}-{sub_id})"
    add_individual(g, gnad_uri, gnad_class, gnad_label, lang="de")
    add_literal(g, gnad_uri, DP["rg_Originaltext"], sub_text, lang="la")
    g.add((gnad_uri, SKOS.definition,
           Literal(f"Weitere Aktivität in RG {rg_id}-{sub_id} [{act_type}]",
                   datatype=XSD.string)))

    # hat_Weitere_Aktivitaet (not hat_Zentrale_Aktivitaet — those are Ablass)
    g.add((sub_uri, P["hat_Weitere_Aktivitaet"], gnad_uri))

# ---------------------------------------------------------------------------
# Build RDF triples — strictly following ontology structure
# ---------------------------------------------------------------------------

def build_triples(g: Graph, rg_id: str, sub_id: str,
                  header_text: str, sub_text: str, rec: dict) -> None:
    """
    Produces RDF triples for one extraction record,
    matching the structure of output.ttl gold standard exactly.
    """

    def val(key: str) -> str:
        v = rec.get(key) or ""
        return str(v).strip() if v else ""

    def lst(key: str) -> list:
        v = rec.get(key) or []
        if isinstance(v, str):
            v = [v] if v.strip() else []
        return [str(x).strip() for x in v if str(x).strip()]

    source_date = val("source_date")
    source_refs = lst("source_references")

    # ── Regest ────────────────────────────────────────────────────────────
    rg_uri_ = regest_uri(rg_id)
    full_text = f"{header_text} || {sub_text}".strip(" |")
    add_individual(g, rg_uri_, C["Regest"], f"RG {rg_id}", lang="de")
    add_literal(g, rg_uri_, DP["rg_Originaltext"], full_text, lang="la")
    if rg_id.isdigit():
        g.add((rg_uri_, DP["hat_Nummer"], Literal(int(rg_id), datatype=XSD.integer)))

    # ── Header_RG ─────────────────────────────────────────────────────────
    hdr_uri = header_uri(rg_id)
    add_individual(g, hdr_uri, C["Header_RG"], f"RG {rg_id}-0", lang="de")
    add_literal(g, hdr_uri, DP["rg_Originaltext"], header_text, lang="la")
    add_literal(g, hdr_uri, DP["has_RG_ID_Header"],
                f"{rg_id}-0", datatype=XSD.string)
    g.add((rg_uri_, P["hat_Bestandteil_RG"], hdr_uri))

    # hat_Petent on Header_RG (person-centric entries only)
    pet_name = val("petitioner_name")
    if pet_name:
        pet_uri = make_uri(pet_name, "Petent")
        add_individual(g, pet_uri, C["Petent"], pet_name, lang="la")
        g.add((hdr_uri, P["hat_Petent"], pet_uri))
        g.add((hdr_uri, P["hat_Akteur"],  pet_uri))

        title = val("petitioner_title")
        if title:
            amt_uri = make_uri(title, "Amt")
            add_individual(g, amt_uri, C["Kirchliches_Amt"], title, lang="la")
            g.add((pet_uri, P["hat_Amt"], amt_uri))

        pet_dioc = val("petitioner_diocese")
        if pet_dioc:
            pdio_uri = make_uri(pet_dioc, "Dioezese")
            add_individual(g, pdio_uri, C["Dioezese"], pet_dioc, lang="la")
            g.add((pet_uri, P["hat_Dioezese"], pdio_uri))

    # ── Sublemma_RG ───────────────────────────────────────────────────────
    sub_uri = sublemma_uri(rg_id, sub_id, source_date)
    sub_label = f"RG {rg_id}-{sub_id}"
    if source_date:
        sub_label += f", {source_date} - Ablass"
    else:
        sub_label += " - Ablass"
    add_individual(g, sub_uri, C["Sublemma_RG"], sub_label, lang="de")
    add_literal(g, sub_uri, DP["rg_Originaltext"], sub_text, lang="la")
    add_literal(g, sub_uri, DP["stringInRG"],       sub_text, lang="la")
    add_literal(g, sub_uri, DP["has_RG_ID_Sublemma"],
                f"{rg_id}-{sub_id}", datatype=XSD.string)
    if source_date:
        add_literal(g, sub_uri, DP["Datum"], source_date, datatype=XSD.string)
    g.add((rg_uri_, P["hat_Bestandteil_RG"], sub_uri))

    # ── Fundstelle individuals ────────────────────────────────────────────
    for ref in source_refs:
        fs_label = f"{source_date} {ref}".strip()
        fs_uri   = fundstelle_uri(source_date, ref)
        add_individual(g, fs_uri, C["Fundstelle"], fs_label, lang="de")
        add_literal(g, fs_uri, DP["has_source"], ref, datatype=XSD.string)
        g.add((sub_uri, P["hat_Fundstelle"], fs_uri))

    # ── Place → hat_Ort on Sublemma_RG ───────────────────────────────────
    place = val("place") or header_text.strip()
    if place:
        place_uri = make_uri(place, "Ort")
        add_individual(g, place_uri, C["Ort"], place, lang="la")
        g.add((sub_uri, P["hat_Ort"], place_uri))

    # ── Mentioned persons → erwaehnte_Entitaet ───────────────────────────
    for mp in lst("mentioned_persons"):
        if mp and mp != pet_name:
            mp_uri = make_uri(mp, "Person")
            add_individual(g, mp_uri, C["Person_explizit"], mp, lang="la")
            g.add((sub_uri, P["erwaehnte_Entitaet"], mp_uri))

    # ── Recipient institutions ────────────────────────────────────────────
    inst_names  = lst("recipient_institutions")
    inst_types  = lst("recipient_institution_types")
    inst_patros = lst("recipient_patrozinia")
    rec_diocese = val("recipient_diocese")

    # Diocese individual (shared across institutions of same entry)
    dioc_uri = None
    if rec_diocese:
        dioc_uri = make_uri(rec_diocese, "Dioezese")
        add_individual(g, dioc_uri, C["Dioezese"], rec_diocese, lang="la")

    inst_uris = []
    for i, inst_name in enumerate(inst_names):
        inst_type_str = inst_types[i] if i < len(inst_types) else "Kirchliche_Institution"
        inst_class    = INST_TYPE_MAP.get(inst_type_str, C["Kirchliche_Institution"])
        inst_uri      = make_uri(inst_name, "Inst")
        add_individual(g, inst_uri, inst_class, inst_name, lang="la")
        inst_uris.append(inst_uri)

        patro = inst_patros[i] if i < len(inst_patros) else ""
        if patro:
            add_literal(g, inst_uri, P["hat_Patrozinium"], patro, lang="la")

        if dioc_uri:
            g.add((inst_uri, P["hat_Dioezese"], dioc_uri))

    # ── Ablass individual — the central activity ──────────────────────────
    subtype_raw  = val("ablass_subtype").lower()
    ablass_class = ABLASS_SUBTYPE_MAP.get(subtype_raw, C["Ablass"])

    # Label: "Ablass für [first inst.] etc. (RG N-N)" — matches gold standard
    label_inst = inst_names[0] if inst_names else ""
    if len(inst_names) > 1:
        label_inst += " etc."
    abl_uri   = ablass_individual_uri(rg_id, sub_id, label_inst)
    abl_label = f"Ablass für {label_inst} (RG {rg_id}-{sub_id})" \
        if label_inst else f"Ablass (RG {rg_id}-{sub_id})"

    add_individual(g, abl_uri, ablass_class, abl_label, lang="de")
    g.add((abl_uri, SKOS.definition,
           Literal(f"Zentrale Aktivität in RG {rg_id}-{sub_id}",
                   datatype=XSD.string)))
    add_literal(g, abl_uri, DP["rg_Originaltext"], sub_text, lang="la")

    # Sublemma → hat_Zentrale_Aktivitaet → Ablass
    g.add((sub_uri, P["hat_Zentrale_Aktivitaet"], abl_uri))

    # hat_Ablassempfaenger — one or more institutions
    for inst_uri in inst_uris:
        g.add((abl_uri, P["hat_Ablassempfaenger"], inst_uri))

    # hat_Ablassgeber (literal)
    giver = val("ablass_giver")
    if giver:
        add_literal(g, abl_uri, DP["hat_Ablassgeber"], giver, lang="la")

    # hat_Ablasshoehe (literal)
    height = val("ablass_height")
    if height:
        add_literal(g, abl_uri, DP["hat_Ablasshoehe"], height, lang="la")

    # ── Duration individuals ──────────────────────────────────────────────
    dur_granted = val("duration_granted")
    if dur_granted:
        dur_uri = make_uri(f"Dauer_{rg_id}_{sub_id}_gewaehrt")
        add_individual(g, dur_uri, C["Dauer"], dur_granted, lang="la")
        g.add((abl_uri, P["Dauer_gewaehrt"],  dur_uri))
        g.add((abl_uri, P["hat_Ablassdauer"], dur_uri))
        yr = re.search(r'(\d+)\s*(?:an[io]|ann|jahre?|year)', dur_granted, re.I)
        mo = re.search(r'(\d+)\s*(?:mens|monat|month)',       dur_granted, re.I)
        if yr:
            add_literal(g, dur_uri, DP["time_years"],  yr.group(1), XSD.integer)
        if mo:
            add_literal(g, dur_uri, DP["time_months"], mo.group(1), XSD.integer)

    dur_requested = val("duration_requested")
    if dur_requested:
        dur_req_uri = make_uri(f"Dauer_{rg_id}_{sub_id}_beantragt")
        add_individual(g, dur_req_uri, C["Dauer"], dur_requested, lang="la")
        g.add((abl_uri, P["Dauer_beantragt"], dur_req_uri))
        g.add((abl_uri, P["hat_Ablassdauer"], dur_req_uri))

    # ── Ad-instar Vorbild ─────────────────────────────────────────────────
    ad_instar = val("ad_instar_model")
    if ad_instar and ablass_class == C["AdInstarAblass"]:
        vorbild_uri = make_uri(ad_instar, "Vorbild")
        add_individual(g, vorbild_uri, C["Kirchliche_Institution"],
                       ad_instar, lang="la")
        g.add((abl_uri, P["hat_Vorbild"], vorbild_uri))


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run(input_path: str, output_path: str,
        model_name: str, limit: int | None, verbose: bool) -> None:

    print(f"[1/4] Loading GLiNER2 model: {model_name}")
    extractor = GLiNER2.from_pretrained(model_name)

    print(f"[2/4] Loading RG JSON: {input_path}")
    with open(input_path, encoding="utf-8") as f:
        data: dict = json.load(f)
    print(f"      {len(data):,} records")

    print(f"[3/4] Initialising empty graph…")
    g = Graph()
    g.bind("wp",   WP)
    g.bind("rga",  RGA)
    g.bind("skos", SKOS)
    g.bind("time", TIME)
    g.bind("owl",  OWL)
    g.bind("xsd",  XSD)
    g.bind("rdfs", RDFS)

    print(f"[4/4] Processing records…")
    rg_ids = list(data.keys())
    if limit:
        rg_ids = rg_ids[:limit]

    stats = dict(
        records=0, subentries=0,
        ablass_detected=0, ablass_extracted=0,
        non_ablass=0, errors=0
    )

    iterator = tqdm(rg_ids, desc="Regesten") if HAS_TQDM else rg_ids

    for rg_id in iterator:
        entry       = data[rg_id]
        header_text = entry.get("header", {}).get("text", "").strip()
        stats["records"] += 1

        for sub_id, sub in entry.get("subentries", {}).items():
            sub_text = sub.get("text", "").strip()
            if not sub_text:
                continue
            stats["subentries"] += 1

            full_text = f"{header_text}. {sub_text}" if header_text else sub_text

            # ── STAGE 1 — classify ALL subentries ────────────────────────
            try:
                cls_result = extractor.classify_text(full_text, CLASSIFY_SCHEMA)
                act_type   = cls_result.get("act_type", "other")
            except Exception as e:
                if verbose:
                    print(f"  [{rg_id}-{sub_id}] WARN classify: {e}")
                stats["errors"] += 1
                continue

            is_ablass = act_type in ABLASS_LABELS
            if verbose:
                mark = "✓ ABLASS" if is_ablass else f"  {act_type}"
                print(f"  [{rg_id}-{sub_id}] {mark}")

            if is_ablass:
                stats["ablass_detected"] += 1
                # ── STAGE 2 — full extraction ─────────────────────────────
                try:
                    extraction = extractor.extract_json(full_text, EXTRACT_SCHEMA)
                    records    = extraction.get("ablass_act", [])
                    if not records:
                        if verbose:
                            print(f"  [{rg_id}-{sub_id}]   extract_json empty")
                        continue
                    for rec in records:
                        build_triples(g, rg_id, sub_id, header_text, sub_text, rec)
                    stats["ablass_extracted"] += 1
                except Exception as e:
                    if verbose:
                        print(f"  [{rg_id}-{sub_id}] WARN extract: {e}")
                    stats["errors"] += 1

            else:
                # ── Non-Ablass: record minimal Sublemma with correct class ─
                stats["non_ablass"] += 1
                build_non_ablass_triples(
                    g, rg_id, sub_id, header_text, sub_text, act_type
                )

    # ── Serialise ─────────────────────────────────────────────────────────
    print(f"\nWriting RDF → {output_path}")
    g.serialize(destination=output_path, format="turtle", encoding="utf-8")

    print(f"\n{'='*60}")
    print(f"  Records            : {stats['records']:>6,}")
    print(f"  Subentries         : {stats['subentries']:>6,}")
    print(f"  Ablass detected    : {stats['ablass_detected']:>6,}")
    print(f"  Ablass extracted   : {stats['ablass_extracted']:>6,}")
    print(f"  Non-Ablass marked  : {stats['non_ablass']:>6,}  (Dispens/Erlaubnis/etc.)")
    print(f"  Errors             : {stats['errors']:>6,}")
    print(f"  Total triples      : {len(g):>6,}")
    print(f"  Output             : {output_path}")
    print(f"{'='*60}")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Populate RG ontology from Ablass subentries using GLiNER2"
    )
    parser.add_argument("--input",   default="rg_sublema_test.json")
    parser.add_argument("--output",  default="rg_gliner2_output.ttl")
    parser.add_argument("--model",   default="fastino/gliner2-large-v1")
    parser.add_argument("--limit",   type=int, default=None,
                        help="Process only first N records (testing)")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    run(
        input_path=args.input,
        output_path=args.output,
        model_name=args.model,
        limit=args.limit,
        verbose=args.verbose,
    )