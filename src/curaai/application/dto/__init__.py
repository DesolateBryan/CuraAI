"""DTOs: frozen, behavior-free data that crosses a port (ADR-012).

One module per boundary, matching the M2 "Crossing of Each Line" table.
No DTO has a summary field (ADR-004), and no DTO carries free text the model
could use to speak to a patient (ADR-009).
"""
