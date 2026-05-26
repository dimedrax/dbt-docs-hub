# Reborn DataOps Platform — dbt Docs portal main policy
# Package isolated from any other Reborn lakehouse policies.
package dbtdocs

import data.dbtdocs.project_access
import data.dbtdocs.column_access

# Default deny everything.
default allow := false

# Project-level decision (used for /<project>/manifest.json + 403 on whole project).
allow if {
	project_access.project_allowed
}

# Column-level decision: column visible iff project allowed AND not masked.
column_visible := result if {
	project_access.project_allowed
	not column_access.column_masked
	result := true
}

column_visible := result if {
	not project_access.project_allowed
	result := false
}

column_visible := result if {
	project_access.project_allowed
	column_access.column_masked
	result := false
}
