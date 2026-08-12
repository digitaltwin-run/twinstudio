# ADD_FEATURE

## Purpose

Propose a feature attached to a selected object or semantic region.

## Syntax

`kind=add_feature; target_uri=<poa>; arguments.feature_type=<type>`

## Inputs

A selected object or region, feature type and allow-listed feature arguments.

## Outputs

A deferred CAD operation awaiting a compatible geometry adapter.

## Errors

Missing persistent geometry mapping or unsupported feature types keep the operation deferred.

## Examples

`dodaj fazę 45 stopni` proposes a 45-degree chamfer on the selected boundary.
