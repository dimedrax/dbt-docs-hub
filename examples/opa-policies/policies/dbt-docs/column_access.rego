# Reborn DataOps Platform — column-level access
# A column is masked iff it carries the "pii" tag AND the user is NOT
# member of any PII-authorized group (pii-authorized, dbt-docs-pii) or admin.
package dbtdocs.column_access

column_masked if {
	"pii" in input.resource.tags
	not pii_authorized
}

pii_authorized if {
	some g in input.user.groups
	g in {"pii-authorized", "dbt-docs-pii", "dbt-docs-admin"}
}
