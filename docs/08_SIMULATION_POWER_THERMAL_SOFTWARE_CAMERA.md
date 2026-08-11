# 08 — Power, thermal, software and camera simulation

## Layer separation

The project separates four kinds of evidence:

1. **Analytical estimate:** fast formulas and reduced-order models.
2. **Software-in-container test:** real application code with controlled inputs.
3. **Hardware-in-the-loop/bench test:** real device and instrumentation.
4. **Validated engineering simulation:** calibrated electrical, thermal, CFD or FEA adapter.

Results must state which layer produced them.

## Power model

The included model computes load-case voltage drop using lumped cable, connector and board-path resistance. It reports board voltage, distribution loss, current-limit risk and brownout risk.

It does not model:

- USB-C negotiation;
- transient regulator behavior;
- inrush, ripple or dynamic load steps;
- battery chemistry;
- individual power-rail sequencing.

Those require a SPICE/power-integrity adapter or measurement.

## Thermal model

The included thermal model is a lumped RC time-domain estimate. It can compare scenarios and provide a calibration target. It is not CFD and has no geometry-based airflow, radiation or fan curve.

A production thermal workflow should ingest component power, materials, contacts, vents, orientation, ambient conditions and fan behavior, then calibrate against thermocouples or onboard sensors.

## Raspberry Pi software simulation

The example runtime container processes sample images and produces deterministic JSON. The separate device simulator publishes workload, estimated current, estimated SoC temperature and image-analysis telemetry over MQTT.

This verifies packaging and data-flow contracts. It does not emulate Raspberry Pi hardware, the camera sensor, kernel drivers or real-time performance.

## Camera simulation

Included synthetic dark/bright patterns support repeatable pipeline tests. Future levels:

- recorded real Camera Module 3 frames with consent/provenance;
- lens distortion and exposure/noise model;
- scene/lighting generation;
- hardware camera replay;
- accuracy, latency and false-positive acceptance thresholds.

## Voltage/thermal coupling

A future process manager can feed electrical loss and component power into the thermal adapter, then apply temperature-dependent resistance and performance derating iteratively. The results should remain a simulation artifact linked to the exact project revision and parameter set.
