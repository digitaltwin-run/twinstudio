# SET_PARAMETER

## Purpose

Propose a typed scalar parameter value for one selected POA object.

## Syntax

`kind=set_parameter; target_uri=<poa>; arguments.parameter=<name>; arguments.value=<scalar>`

## Inputs

A selected object, an existing parameter name, a value and an optional unit.

## Outputs

A reversible parameter patch after runtime authorization.

## Errors

Unknown parameters, non-positive dimensions and targets outside the selected scope are rejected or deferred.

## Examples

`ustaw wysokość na 21 mm` proposes `height=21 mm` on the selected object.
