# Raspberry Pi 5 housing

Revision: **A**  
Units: **mm**

## Source assumptions requiring confirmation

- The default total external depth of 95 mm is a working assumption derived from the 80 mm flat lid section plus 13 mm front and 2 mm rear insets.
- Connector opening positions are configurable placeholders and must be verified against the final board, components, and plug bodies.
- Hinge clearances and the pin method require a physical FDM prototype before production.

## Main enclosure

- External width: 79.00
- External depth: 95.00
- Total height: 40.00
- Lower base height: 25.00
- Wall thickness: 2.00
- Lid flat top: 59.00 x 80.00
- Lower vertical lid section: 2.00
- Nominal external edge radius: 0.80

## Raspberry Pi mounting

- PCB reference: 56.00 x 85.00
- Mounting-hole pattern: 49.00 x 58.00
- Standoffs: OD 6.00, pilot 1.00, height 3.00
- Position A: front 2.00, right 1.00
- Position B: front 2.00, right 7.50, requested left 10.50

## Lid internal bosses

- Auxiliary boss OD: 8.00
- Auxiliary boss hole: 2.00
- Auxiliary boss top datum from the upper base mating plane (Datum A): 14.00

## Hinge

- Knuckle OD: 8.00
- Nominal pin diameter: 3.00
- Bore diameter: 3.20 (includes 0.20 diametral clearance)
- Target opening angle: 195.00 deg
- Front base chamfer: 45.00 deg; vertical drop 2.00
- Base wall rotational relief: 1.50
- Lid edge rotational relief: 2.00

## Connector openings

- rear_connector: enabled; wall=rear; width=20.00; height=8.00; corner radius=1.00; bottom Z=7.00

## Enabled feature layers

- `base_shell`: enabled - Lower base shell
- `lid_shell`: enabled - Upper lid shell
- `hinge`: enabled - Front hinge
- `pcb_mount_a`: enabled - PCB mounting pattern A
- `pcb_mount_b`: enabled - PCB mounting pattern B
- `camera_mounts`: enabled - Camera mounting bosses
- `lid_aux_bosses`: enabled - Four auxiliary lid bosses
- `rear_tabs`: enabled - Rear internal tabs
- `connector_openings`: enabled - Connector openings
- `locating_lip`: disabled - Internal locating lip
- `pcb_reference`: enabled - PCB reference geometry

## Validation notes

- **INFO / EXTERNAL_DEPTH_WORKING_ASSUMPTION**: The 95.00 mm total external depth is a working assumption derived from the 80.00 mm flat lid section plus configured 13.00 mm front and 2.00 mm rear insets. The supplied source did not independently dimension the total depth.
  - Suggested action: Confirm the total external depth before production or edit dimensions.external_depth.
- **INFO / CONNECTOR_OPENING_REQUIRES_VERIFICATION**: Connector openings are configurable reference geometry. Their exact dimensions and positions must be checked against the final Raspberry Pi/component assembly and plug bodies.
- **WARNING / PCB_B_CLEARANCE_MISMATCH**: Mounting position B is anchored to the requested right clearance (7.50 mm), which produces an actual left clearance of 11.50 mm instead of 10.50 mm.
  - Suggested action: Change the external width, wall thickness, PCB width, or choose which side clearance is authoritative. The generator does not silently average them.
- **INFO / AUX_BOSS_EMBEDDED_IN_ROOF**: Auxiliary bosses extend 1.00 mm into the lid roof to create a structural attachment.
- **INFO / REAR_MIDDLE_WALL_DETAIL_SIMPLIFIED**: The rear tabs are generated and extended toward the inner roof using the configured clearance, but the separate wall section between the tabs is represented only as a documented simplified detail.
  - Suggested action: Confirm the exact cross-section of the 4 mm reduced middle wall before production.
- **INFO / PHYSICAL_PROTOTYPE_REQUIRED**: The generated hinge, connector opening, tolerances, and support-free angles are parametric CAD assumptions. Verify them with a printed prototype before production.

## Manufacturing notice

This generator produces parametric CAD and documentation artifacts. A physical prototype is still required before production, especially for the hinge, moving clearances, connector access, and FDM tolerances.
