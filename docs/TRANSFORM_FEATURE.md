# TRANSFORM_FEATURE

## Purpose

Propose moving or transforming a selected feature.

## Syntax

`kind=transform_feature; target_uri=<poa>; arguments.distance_mm=<number>; arguments.direction=<axis>`

## Inputs

A persistent feature selection, distance and explicit direction or axis.

## Outputs

A deferred CAD transform operation.

## Errors

Requests without an axis remain unresolved and cannot be automatically applied.

## Examples

`przesuń o 5 mm w osi X` proposes a five-millimetre feature translation.
