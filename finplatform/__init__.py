"""FinSight Layer-0 platform package.

Retains only the RBAC matrix (``finplatform.rbac.matrix``) and tenant
configuration schema (``finplatform.config.tenant_schema``), both of which
have live consumers. All other sub-packages were removed in Slice 7.

Layer 0: imports nothing internal. No re-exports.
"""
