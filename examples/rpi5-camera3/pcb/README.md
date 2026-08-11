# PCB/SCH adapter boundary

This example does not contain a custom PCB design. Raspberry Pi 5 and Camera Module 3 are purchased components in the xBOM.

The platform reserves POA object kinds for `pcb` and `schematic`, and the future adapter contract is:

1. keep native KiCad source files as source artifacts;
2. derive symbols, footprints, nets, board outlines and design-rule findings into the product graph;
3. map 2D PCB/SCH selections to stable KiCad UUIDs;
4. compile scoped natural-language intent into an allow-listed PCB/SCH change plan;
5. apply changes through a versioned adapter;
6. run ERC/DRC and export review artifacts;
7. append commands, results and approvals to the project event stream.

`kicad_adapter.py` only implements safe CLI discovery/export/check orchestration. It does not autoroute or synthesize a production circuit.
