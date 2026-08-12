# ADD_ANNOTATION

## Purpose

Preserve an ambiguous or non-executable natural-language request as a scoped note.

## Syntax

`kind=add_annotation; target_uri=<poa>; arguments.text=<source-text>`

## Inputs

A selected target and the original integrity-bound natural-language source.

## Outputs

A reviewable annotation without geometry effects.

## Errors

Empty text or a target outside the selected POA scope is rejected.

## Examples

An unsupported request is retained as an annotation with a clarification question.
