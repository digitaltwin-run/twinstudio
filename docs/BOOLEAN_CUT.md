# BOOLEAN_CUT

## Purpose

Propose subtractive geometry within the selected scope.

## Syntax

`kind=boolean_cut; target_uri=<poa>; arguments.feature_type=<cut-type>`

## Inputs

A selected region plus typed dimensions such as diameter and depth mode.

## Outputs

A deferred subtractive CAD operation.

## Errors

Missing diameter, insufficient edge distance or unresolved B-Rep mapping requires review.

## Examples

`dodaj otwór o średnicy 3 mm` proposes a three-millimetre through-hole.
