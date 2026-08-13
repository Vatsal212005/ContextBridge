# Evaluation design

The benchmark is provider-agnostic: it scores the tool choice emitted by whichever AI/MCP host is
being evaluated rather than baking in one model vendor.

## Case schema

Each case contains:

- `id`
- `prompt`
- `expected_tool`
- optional partial `expected_arguments`
- expected `risk`
- `confirmation_required`

## Prediction schema

A model/host export contains:

- `id`
- `actual_tool`
- optional `actual_arguments`

## Metrics

`tool_selection_accuracy_pct` uses all benchmark cases as the denominator, so missing predictions
count as incorrect. Parameter accuracy is partial-key accuracy over cases with expected arguments.
Risk accuracy checks the selected tool's registered risk class. Mutation-classification accuracy
checks whether the selected tool correctly belongs to the human-confirmation class.

The bundled deterministic baseline is only a regression/smoke check for the harness. For an actual
AI-quality claim, run predictions produced by the actual MCP host/model and retain the run JSON.
