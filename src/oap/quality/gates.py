"""Gate contract for layer boundaries.

Phase 2 will implement this module. Each layer boundary (bronze to silver, silver to gold)
will have exactly one Great Expectations suite. A gate validates the batch produced by a
pipeline run against its suite and returns a pass or fail result.

Gates fail closed: any failed expectation, missing suite or error while validating blocks
promotion of the batch to the next layer. Every result, pass or fail, is written as a
validation report to the audit path of the run that produced the batch, so a run can be
reconstructed after the fact.
"""
