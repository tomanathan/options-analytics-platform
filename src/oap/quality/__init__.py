"""Great Expectations gates between the bronze, silver and gold layers.

Data moves from one layer to the next only after the gate at that boundary passes. This
package owns the expectation suites and the code that runs them; orchestration (when a
gate runs) belongs to the Airflow DAGs and the transformations themselves belong to dbt.
"""
