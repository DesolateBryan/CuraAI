"""CuraAI: Clinical Record Triage and Historical Pre-Fetch.

Ring map (Dependency Rule: source code dependencies point inward only):

    curaai.domain        Ring 1  Entities: pure business rules
    curaai.application   Ring 2  Use cases, ports, DTOs, model-output validation
    curaai.adapters      Ring 3  Interface adapters (EHR, drug DB, model, presenter, stores)
    curaai.app           Ring 4  Frameworks and drivers, composition root (main)
"""
