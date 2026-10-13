use crate::error::{Error, ErrorKind, Result};
use crate::graph::ExactRef;
use crate::resources::registered_evidence;
use crate::store::Store;
use crate::strict_json;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::path::Path;

const MAX_PAGE_BYTES: usize = 16_384;
const MAX_DECLARATION_STRING_BYTES: usize = 128;

#[derive(Deserialize, Serialize)]
#[serde(rename_all = "snake_case")]
enum DeclaredHostClass {
    LocalCodex,
    ManagedApi,
    Dsh,
    TestLocal,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct DeclaredBudgetValues {
    tool_output_token_limit: Option<u64>,
    model_auto_compact_token_limit: Option<u64>,
    auto_compact_scope: Option<String>,
    configured_context_window: Option<u64>,
    skills_max_context_tokens: Option<u64>,
    max_threads: Option<u64>,
}

#[derive(Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct BudgetDeclaration {
    schema_version: u64,
    host_class: DeclaredHostClass,
    model: String,
    config_revision: u64,
    values: DeclaredBudgetValues,
}

fn declaration_string(value: &str, field: &str) -> Result<()> {
    if value.is_empty()
        || value.len() > MAX_DECLARATION_STRING_BYTES
        || value.trim() != value
        || value.chars().any(char::is_control)
    {
        return Err(Error::new(
            ErrorKind::Shape,
            format!("{field} must be 1..128 UTF-8 bytes without boundary whitespace or control characters"),
        ));
    }
    Ok(())
}

fn hexadecimal(bytes: &[u8]) -> String {
    const DIGITS: &[u8; 16] = b"0123456789abcdef";
    let mut encoded = String::with_capacity(bytes.len() * 2);
    for &byte in bytes {
        encoded.push(char::from(DIGITS[usize::from(byte >> 4)]));
        encoded.push(char::from(DIGITS[usize::from(byte & 15)]));
    }
    encoded
}

impl Store {
    pub fn read_evidence_page(
        &self,
        reference: &ExactRef,
        offset: usize,
        page_size: usize,
    ) -> Result<Value> {
        let bytes = registered_evidence(
            &self.connection,
            &self.workspace,
            &self.scope,
            reference,
        )?;
        if !(1..=MAX_PAGE_BYTES).contains(&page_size) {
            return Err(Error::new(
                ErrorKind::BudgetExhausted,
                "evidence page size must be 1..16384 engineering bytes, not tokens or a fee limit",
            ));
        }
        if offset > bytes.len() {
            return Err(Error::new(
                ErrorKind::Shape,
                "evidence byte offset exceeds the complete registered file length",
            ));
        }
        let next_offset = offset + page_size.min(bytes.len() - offset);
        let page = &bytes[offset..next_offset];
        Ok(json!({
            "schema_version": 1,
            "kind": "registered-evidence-byte-page",
            "reference": reference,
            "sha256": reference.sha256,
            "total_bytes": bytes.len(),
            "offset": offset,
            "next_offset": next_offset,
            "complete": next_offset == bytes.len(),
            "encoding": "hex",
            "page_hex": hexadecimal(page),
            "page_sha256": strict_json::sha256(page),
            "page_bytes": page.len(),
            "requested_page_bytes": page_size,
            "engineering_page_byte_limit": MAX_PAGE_BYTES,
            "full_evidence_retained": true,
            "evidence_truncated": false,
            "failure_fields_filtered": false,
            "safety_fields_filtered": false,
            "fee_hard_limit": false,
            "execution_authority": false,
            "runtime_admission": false,
            "native_host_verified": false
        }))
    }

    pub fn budget_configuration(&self, reference: &ExactRef) -> Result<Value> {
        let development = std::fs::canonicalize(
            Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev"),
        )
        .map_err(|_| {
            Error::new(
                ErrorKind::ScopeDenied,
                "budget declarations require an existing isolated .dev workspace",
            )
        })?;
        if !self.workspace.root().starts_with(&development)
            || self.workspace.root() == development
        {
            return Err(Error::new(
                ErrorKind::ScopeDenied,
                "budget declarations are restricted to a separate project .dev workspace",
            ));
        }
        let bytes = registered_evidence(
            &self.connection,
            &self.workspace,
            &self.scope,
            reference,
        )?;
        let declaration: BudgetDeclaration =
            serde_json::from_value(strict_json::parse(&bytes)?)?;
        if declaration.schema_version != 1 || declaration.config_revision == 0 {
            return Err(Error::new(
                ErrorKind::Shape,
                "budget declaration requires schema_version 1 and config_revision >= 1",
            ));
        }
        declaration_string(&declaration.model, "model")?;
        if let Some(scope) = &declaration.values.auto_compact_scope {
            declaration_string(scope, "auto_compact_scope")?;
        }
        let host_schema_fingerprint = strict_json::digest(&json!({
            "fingerprint_schema_version": 1,
            "declaration_schema_version": declaration.schema_version,
            "declared_host_class": declaration.host_class,
            "declared_model": declaration.model,
            "config_revision": declaration.config_revision,
            "source_ref": reference
        }))?;
        Ok(json!({
            "schema_version": 1,
            "kind": "registered-budget-configuration",
            "source_ref": reference,
            "host_schema_fingerprint": host_schema_fingerprint,
            "fingerprint_kind": "declaration_host_schema_and_exact_source_not_active_host_identity",
            "model_policy": "current_selection_baseline_upgrade_only",
            "requested_model": "inherit_current_selection",
            "upgrade_model": "gpt-6.1-sol",
            "upgrade_efforts": ["high", "xhigh"],
            "automatic_downgrade": false,
            "failure_fallback_chain": false,
            "configured_state": "configured_only",
            "configured": declaration,
            "observed": {
                "kind": "current_registered_file_bytes_and_hash_only",
                "source_ref": reference,
                "sha256": reference.sha256,
                "total_bytes": bytes.len(),
                "active_config_observed": false,
                "native_host_verified": false
            },
            "effective": {
                "context_window": "unknown",
                "directory_budget": "unknown",
                "model": "unknown",
                "effort": "unknown",
                "quota": "unknown",
                "tool_output_token_limit": "unknown",
                "model_auto_compact_token_limit": "unknown",
                "auto_compact_scope": "unknown",
                "skills_max_context_tokens": "unknown",
                "max_threads": "unknown"
            },
            "budget_semantics": {
                "declared_values": "configured_only_not_active_configuration",
                "page_byte_limit": "engineering_bytes_not_model_tokens_or_fees",
                "compaction_threshold": "configured_target_not_fee_hard_limit",
                "directory_budget_calculated": false,
                "effective_window_used_for_calculation": false,
                "other_model_context_window_reused": false,
                "fee_hard_limit": false
            },
            "active_config_observed": false,
            "native_host_verified": false,
            "fee_hard_limit": false,
            "execution_authority": false,
            "runtime_admission": false
        }))
    }
}
