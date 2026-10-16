"""Explicit Nexus result-to-MetSights attachment routing."""

from pathlib import Path

from programs.services.utils.constants import ServiceDocumentCategory

UNTYPED_MODULES = {
    "blood": "precision_blood_diagnostics",
    "oligoscan": "oligoscans",
    "omics_urine": "urine_metabolites",
    "omics_cortisol": "saliva_panel",
    "evo_360": "evo_imaging",
    "somfit": "somfit_panel",
}
TYPED_MODULES = {
    "dxa_core_scan": "dxa_reports",
    "dxa_body_composition": "dxa_reports",
    "dxa_segmental_analysis": "dxa_reports",
    "breathing_stress_profile_report": "breathing_stress",
    "breathing_stress_respiratory_report": "breathing_stress",
    "breathing_stress_communication_style": "breathing_stress",
    "breathing_stress_cognifit": "breathing_stress",
    "usg_carotid_doppler": "ultrasonography",
    "usg_neck": "ultrasonography",
    "usg_abdomen_pelvis": "ultrasonography",
    "usg_arterial_doppler": "ultrasonography",
    "usg_venous_doppler": "ultrasonography",
    "usg_sonomammogram": "ultrasonography",
    "usg_scrotum": "ultrasonography",
    "usg_follicular_tvs": "ultrasonography",
    "usg_pelvic_tvs": "ultrasonography",
    "usg_others": "ultrasonography",
    "genetics_functional": "genetics_insights",
    "genetics_breast_ovarian_cancer": "genetics_insights",
    "genetics_comprehensive": "genetics_insights",
    "genetics_pharmacogenomics": "genetics_insights",
    "genetics_inherited_cancer": "genetics_insights",
    "genetics_nutri_dna_pdf": "genetics_nutri_dna",
    "genetics_nutri_dna_vcf": "genetics_nutri_dna",
    "steroid_hormone_profile": "steroid_hormones",
    "steroid_hormone_nad_longevity": "steroid_hormones",
    "steroid_hormone_nutri_toxic": "steroid_hormones",
    "steroid_hormone_fatty_acid": "steroid_hormones",
    "steroid_hormone_neurotransmitter_profile": "steroid_hormones",
    "fitness_strength_pelvic_floor": "fitness_strength",
    "fitness_strength_physical_assessment": "fitness_strength",
    "fitness_strength_vo2_max": "fitness_strength",
}
VARIANT_MODULES = {
    "genetics_nutri_dna": "genetics_nutri_dna",
    "genetics_health_insights": "genetics_health_insights",
    "bugspeaks_report": "gut_microbiome",
}
FILE_VARIANTS = {
    ("genetics_nutri_dna", ".pdf"): "genetics_nutri_dna_pdf",
    ("genetics_nutri_dna", ".vcf"): "genetics_nutri_dna_vcf",
    ("genetics_health_insights", ".pdf"): "genetics_health_insights_pdf",
    ("genetics_health_insights", ".vcf"): "genetics_health_insights_vcf",
    ("bugspeaks_report", ".pdf"): "bugspeaks_report_pdf",
    ("bugspeaks_report", ".xls"): "bugspeaks_additional_report_xls",
    ("bugspeaks_report", ".xlsx"): "bugspeaks_additional_report_xls",
}


def get_source_module(document_type: str):
    return (
        UNTYPED_MODULES.get(document_type)
        or TYPED_MODULES.get(document_type)
        or VARIANT_MODULES.get(document_type)
    )


def get_source_file_type(document_type: str, document: dict):
    if document_type in UNTYPED_MODULES:
        return None, None
    if document_type in TYPED_MODULES:
        return document_type, None
    extension = Path(document["filename"] or document["file"]).suffix.lower()
    file_type = FILE_VARIANTS.get((document_type, extension))
    if not file_type:
        return None, f"Document {document['document_id']} has no unambiguous MetSights file type."
    if extension == ".pdf" and document["document_category"] != ServiceDocumentCategory.REPORT:
        return None, f"Document {document['document_id']} PDF is not classified as a report."
    return file_type, None
