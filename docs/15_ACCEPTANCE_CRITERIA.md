# 15 — Acceptance criteria

## MVP platform acceptance

- Web UI loads the seeded project and displays the object tree.
- Base and lid can be shown/hidden independently.
- Pointer/pencil/lasso/rectangle selection stores versioned evidence.
- 3D selection resolution identifies object and semantic feature/face where available.
- 2D selection without mapping is preserved but cannot silently modify 3D.
- NL request produces a schema-valid change plan.
- Operations outside selected POA scope are rejected.
- Scalar patches are event-sourced; topology changes are clearly deferred.
- Tree, specification and event history reconstruct after restart.
- Reader/editor/admin/creator permissions are enforced.
- Email approval creates an external membership and personal API token.
- Project export contains snapshot, specification, event stream, artifacts and hashes.
- Power/thermal/human/mechanical functions identify their model and limitations.
- Docker base stack starts; optional profiles are independently selectable.
- Protobuf and JSON schemas are present.
- Tests pass.

## Enclosure example acceptance

- Lower base and upper lid are separate object nodes and artifacts.
- General wall thickness is 2 mm in approved parameters.
- RPi mounting patterns, camera mounts, hinge and lid shell are visible as features.
- Purchased RPi, camera, power supply and hinge pin do not enter the print job.
- Base/lid enter the print job and remain downloadable as STL/STEP examples.
- Front/top/side 2D views are linked.
- Test plan covers dimensional, printability, power, camera software and human-use review.
- Provisional dimensions and unverified assumptions remain labeled.

## Criteria for claiming production readiness

Not met by the reference package alone. Required additional evidence includes physical fit/print tests, calibrated electrical/thermal measurements, production authentication/security review, stable CAD topology adapter, manufacturing inspection results, software test on target hardware and approved commercial identifiers/claims.
