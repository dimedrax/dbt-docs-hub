# Reborn DataOps Platform — project-level access
#
# A user can view project P if any of these is true:
#   - they belong to "dbt-docs-admin" (super-group)
#   - they belong to a group explicitly mapped to P in `project_group_mapping`
#   - they belong to a group named "dbt-docs-{P}" (convention shortcut)
#
# The explicit mapping is the source of truth for the ShopStream personas
# (e.g. `dbt-docs-finance-tax` → `dbt_corporate_finance`). The naming
# convention is kept so the original demo (alice/bob/charlie + voiture) still
# works without listing every project here.
package dbtdocs.project_access

project_allowed if {
	some g in input.user.groups
	g == "dbt-docs-admin"
}

project_allowed if {
	some g in input.user.groups
	some allowed in project_group_mapping[g]
	allowed == input.resource.project
}

project_allowed if {
	some g in input.user.groups
	g == sprintf("dbt-docs-%s", [input.resource.project])
}

# Explicit group → projects mapping for ShopStream personas.
project_group_mapping := {
	# Finance
	"dbt-docs-finance-all":        ["dbt_corporate_finance"],
	"dbt-docs-finance-tax":        ["dbt_corporate_finance"],
	"dbt-docs-finance-treasury":   ["dbt_corporate_finance"],
	# People
	"dbt-docs-people-all":         ["dbt_people"],
	"dbt-docs-people-hr":          ["dbt_people"],
	"dbt-docs-people-recruitment": ["dbt_people"],
	# Commerce
	"dbt-docs-commerce-all":       ["dbt_commerce"],
	"dbt-docs-commerce-marketing": ["dbt_commerce"],
	"dbt-docs-commerce-pricing":   ["dbt_commerce"],
	# Operations
	"dbt-docs-operations-all":     ["dbt_operations"],
	# Auditor — read-only access to finance.
	"dbt-docs-readonly":           ["dbt_corporate_finance"],
}
