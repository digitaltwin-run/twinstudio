# ADR 0002 — Product Object Addressing

- Status: accepted
- Decision: define `poa://tenant/project@revision/...` as the canonical cross-interface identifier.
- Rationale: filenames and tool-native IDs are insufficient across CAD, PCB, software, test, manufacturing and commerce.
- Consequences: adapters must preserve POA metadata and map native IDs to it; POA is explicitly a project-defined term.
