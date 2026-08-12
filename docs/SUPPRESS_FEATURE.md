# SUPPRESS_FEATURE

## Purpose

Propose suppression of an identified feature without deleting its history.

## Syntax

`kind=suppress_feature; target_uri=<poa>; selector.feature=<stable-id>`

## Inputs

A scoped target and a stable feature identifier.

## Outputs

A reversible deferred suppression operation.

## Errors

Ambiguous or missing feature identifiers require clarification and are not automatically applied.

## Examples

Suppress a selected mounting boss while preserving its event history.
