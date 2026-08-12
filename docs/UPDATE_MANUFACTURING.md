# UPDATE_MANUFACTURING

## Purpose

Propose an update to manufacturing metadata for a selected object.

## Syntax

`kind=update_manufacturing; target_uri=<poa>; arguments.<field>=<value>`

## Inputs

A selected object and typed make/buy, process, material or supplier fields.

## Outputs

A reviewed manufacturing change plan.

## Errors

Unknown process values and changes outside the selected product scope are rejected.

## Examples

Change the selected part process from prototype printing to CNC milling.
