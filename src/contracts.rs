use crate::error::{Error, ErrorKind, Result};
use crate::strict_json;
use serde_json::Value;

pub struct Schemas {
    contracts: Value,
    atoms: Value,
}

impl Schemas {
    pub fn frozen() -> Result<Self> {
        let schemas = Self {
            contracts: strict_json::parse(include_bytes!("../schemas/contracts.schema.json"))?,
            atoms: strict_json::parse(include_bytes!("../schemas/atom-semantics.schema.json"))?,
        };
        schemas.audit_schema(&schemas.contracts, 0)?;
        schemas.audit_schema(&schemas.atoms, 0)?;
        Ok(schemas)
    }

    fn resolve(&self, reference: &str, namespace: &str) -> Result<(&Value, &'static str)> {
        let (file, fragment) = reference.split_once('#').ok_or_else(|| Error::new(ErrorKind::Reference, "schema reference requires pointer"))?;
        let selected = if file.is_empty() { namespace } else { file };
        let (document, name) = match selected {
            "contracts.schema.json" => (&self.contracts, "contracts.schema.json"),
            "atom-semantics.schema.json" => (&self.atoms, "atom-semantics.schema.json"),
            _ => return Err(Error::new(ErrorKind::Reference, "unlocked schema reference")),
        };
        let value = document.pointer(fragment).ok_or_else(|| Error::new(ErrorKind::Reference, "missing schema pointer"))?;
        Ok((value, name))
    }

    fn audit_schema(&self, schema: &Value, depth: usize) -> Result<()> {
        if depth > 256 {
            return Err(Error::new(ErrorKind::BudgetExhausted, "schema nesting"));
        }
        let object = schema.as_object().ok_or_else(|| Error::new(ErrorKind::Shape, "schema object required"))?;
        let supported = ["$schema", "$id", "$ref", "title", "description", "$defs", "type", "const", "enum", "properties", "required", "additionalProperties", "items", "minItems", "maxItems", "minLength", "maxLength", "minimum", "maximum", "pattern", "oneOf", "anyOf", "allOf"];
        if object.keys().any(|key| !supported.contains(&key.as_str())) {
            return Err(Error::new(ErrorKind::Shape, "unsupported frozen schema keyword"));
        }
        if let Some(pattern) = schema["pattern"].as_str() {
            if pattern != "^[0-9a-f]{64}$" && !(pattern.starts_with('^') && pattern.ends_with("_[A-Z0-9_]+$")) {
                return Err(Error::new(ErrorKind::Shape, "unsupported frozen pattern"));
            }
        }
        for map_key in ["$defs", "properties"] {
            if let Some(children) = schema[map_key].as_object() {
                for child in children.values() {
                    self.audit_schema(child, depth + 1)?;
                }
            }
        }
        for list_key in ["oneOf", "anyOf", "allOf"] {
            if let Some(children) = schema[list_key].as_array() {
                for child in children {
                    self.audit_schema(child, depth + 1)?;
                }
            }
        }
        if let Some(child) = schema.get("items") {
            self.audit_schema(child, depth + 1)?;
        }
        Ok(())
    }

    pub fn check_definition(&self, name: &str, value: &Value) -> Result<()> {
        let definition = self.contracts["$defs"].get(name).ok_or_else(|| Error::new(ErrorKind::Reference, "unknown contract definition"))?;
        self.walk(definition, value, "contracts.schema.json", "$", 0)
    }

    pub fn check_atom(&self, name: &str, value: &Value) -> Result<()> {
        let definition = self.atoms["$defs"].get(name).ok_or_else(|| Error::new(ErrorKind::Reference, "unknown atom definition"))?;
        self.walk(definition, value, "atom-semantics.schema.json", "$", 0)
    }

    pub fn check_envelope(&self, value: &Value) -> Result<()> {
        self.walk(&self.contracts, value, "contracts.schema.json", "$", 0)?;
        let metadata = &value["metadata"];
        let payload = &value["payload"];
        if metadata["type"] != value["contract_type"] {
            return Err(Error::new(ErrorKind::Shape, "metadata.type does not match contract_type"));
        }
        for key in ["id", "scope", "revision", "owner", "schema_version"] {
            if let Some(field) = payload.get(key) {
                if field != &metadata[key] {
                    return Err(Error::new(ErrorKind::Shape, format!("duplicated authority field: {key}")));
                }
            }
        }
        let created = metadata["created_at_utc_ms"].as_u64().unwrap();
        let updated = metadata["updated_at_utc_ms"].as_u64().unwrap();
        if updated < created || metadata["valid_until_utc_ms"].as_u64().is_some_and(|expiry| expiry < updated) {
            return Err(Error::new(ErrorKind::Shape, "metadata time order invalid"));
        }
        if metadata["content_hash"].as_str() != Some(strict_json::object_digest(value)?.as_str()) {
            return Err(Error::new(ErrorKind::HashMismatch, "object hash mismatch"));
        }
        Ok(())
    }

    fn walk(&self, schema: &Value, value: &Value, namespace: &str, path: &str, depth: usize) -> Result<()> {
        if depth > 256 {
            return Err(Error::new(ErrorKind::BudgetExhausted, "validation nesting"));
        }
        let reject = |reason: &str| Error::new(ErrorKind::Shape, format!("{path}: {reason}"));
        if let Some(reference) = schema["$ref"].as_str() {
            let (target, target_namespace) = self.resolve(reference, namespace)?;
            self.walk(target, value, target_namespace, path, depth + 1)?;
        }
        if let Some(expected) = schema.get("const") {
            if expected != value { return Err(reject("const mismatch")); }
        }
        if let Some(choices) = schema["enum"].as_array() {
            if !choices.contains(value) { return Err(reject("enum mismatch")); }
        }
        if let Some(expected) = schema.get("type") {
            let matches_type = |name: &str| match name {
                "object" => value.is_object(), "array" => value.is_array(),
                "string" => value.is_string(), "integer" => value.as_i64().is_some() || value.as_u64().is_some(),
                "boolean" => value.is_boolean(), "null" => value.is_null(), _ => false,
            };
            let valid = expected.as_str().is_some_and(matches_type)
                || expected.as_array().is_some_and(|types| types.iter().any(|kind| kind.as_str().is_some_and(matches_type)));
            if !valid { return Err(reject("type mismatch")); }
        }
        for key in ["oneOf", "anyOf", "allOf"] {
            if let Some(variants) = schema[key].as_array() {
                let successes = variants.iter().filter(|variant| self.walk(variant, value, namespace, path, depth + 1).is_ok()).count();
                if (key == "oneOf" && successes != 1) || (key == "anyOf" && successes == 0) || (key == "allOf" && successes != variants.len()) {
                    return Err(reject(key));
                }
            }
        }
        if let Some(object) = value.as_object() {
            if let Some(required) = schema["required"].as_array() {
                for name in required {
                    if !object.contains_key(name.as_str().unwrap()) { return Err(reject("required property missing")); }
                }
            }
            if schema["additionalProperties"] == Value::Bool(false) {
                if object.keys().any(|key| schema["properties"].get(key).is_none()) { return Err(reject("unknown property")); }
            }
            if let Some(properties) = schema["properties"].as_object() {
                for (key, child_schema) in properties {
                    if let Some(child_value) = object.get(key) {
                        self.walk(child_schema, child_value, namespace, &format!("{path}/{key}"), depth + 1)?;
                    }
                }
            }
        }
        if let Some(array) = value.as_array() {
            for (key, too_small) in [("minItems", true), ("maxItems", false)] {
                if let Some(limit) = schema[key].as_u64() {
                    if (too_small && (array.len() as u64) < limit) || (!too_small && (array.len() as u64) > limit) { return Err(reject("array length")); }
                }
            }
            if let Some(item_schema) = schema.get("items") {
                for (index, item) in array.iter().enumerate() {
                    self.walk(item_schema, item, namespace, &format!("{path}/{index}"), depth + 1)?;
                }
            }
        }
        if let Some(text) = value.as_str() {
            let length = text.chars().count() as u64;
            if schema["minLength"].as_u64().is_some_and(|minimum| length < minimum) || schema["maxLength"].as_u64().is_some_and(|maximum| length > maximum) { return Err(reject("string length")); }
            if let Some(pattern) = schema["pattern"].as_str() {
                let valid = if pattern == "^[0-9a-f]{64}$" {
                    text.len() == 64 && text.bytes().all(|byte| byte.is_ascii_digit() || (b'a'..=b'f').contains(&byte))
                } else {
                    let prefix = pattern.trim_start_matches('^').trim_end_matches("[A-Z0-9_]+$");
                    text.strip_prefix(prefix).is_some_and(|suffix| !suffix.is_empty() && suffix.bytes().all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_'))
                };
                if !valid { return Err(reject("pattern mismatch")); }
            }
        }
        if value.is_number() {
            let numeric = value.to_string().parse::<i128>().map_err(|_| reject("integer required"))?;
            for (key, below) in [("minimum", true), ("maximum", false)] {
                if let Some(limit) = schema.get(key) {
                    let bound = limit.to_string().parse::<i128>().map_err(|_| reject("invalid bound"))?;
                    if (below && numeric < bound) || (!below && numeric > bound) { return Err(reject("integer bound")); }
                }
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn exact_reference_and_unknown_field() {
        let schemas = Schemas::frozen().unwrap();
        let mut reference = json!({"id":"input","type":"file","scope":"project","revision":1,"sha256":"a".repeat(64),"release":"local-1","schema_version":1});
        schemas.check_definition("ExactRef", &reference).unwrap();
        reference["actor"] = json!("user");
        assert!(schemas.check_definition("ExactRef", &reference).is_err());
    }

    #[test]
    fn atom_result_coupling() {
        let schemas = Schemas::frozen().unwrap();
        let mut result = json!({"atom_id":"B01","status":"pass","value":{"compatible":true},"failure_code":null,"evidence_refs":[]});
        schemas.check_atom("B01Result", &result).unwrap();
        result["status"] = json!("unknown");
        assert!(schemas.check_atom("B01Result", &result).is_err());
        result["failure_code"] = json!("B01_SCOPE_UNKNOWN");
        schemas.check_atom("B01Result", &result).unwrap();
        result["failure_code"] = json!("I08_WRONG_ATOM");
        assert!(schemas.check_atom("B01Result", &result).is_err());
    }

    fn seed(schemas: &Schemas, schema: &Value, namespace: &str) -> Value {
        if let Some(value) = schema.get("const") { return value.clone(); }
        if let Some(choices) = schema["enum"].as_array() { return choices[0].clone(); }
        if let Some(reference) = schema["$ref"].as_str() {
            let (target, selected) = schemas.resolve(reference,namespace).unwrap();
            return seed(schemas,target,selected);
        }
        if let Some(choices) = schema["anyOf"].as_array().or_else(|| schema["oneOf"].as_array()) {
            return seed(schemas,&choices[0],namespace);
        }
        let kind = schema["type"].as_str().or_else(|| schema["type"].as_array().and_then(|types| types[0].as_str())).unwrap_or("object");
        match kind {
            "object" => {
                let mut object = serde_json::Map::new();
                if let Some(properties) = schema["properties"].as_object() {
                    for (key, child) in properties { object.insert(key.clone(),seed(schemas,child,namespace)); }
                }
                Value::Object(object)
            }
            "array" => {
                let count = schema["minItems"].as_u64().unwrap_or(0);
                Value::Array((0..count).map(|_| seed(schemas,&schema["items"],namespace)).collect())
            }
            "string" => {
                if schema["pattern"] == "^[0-9a-f]{64}$" { json!("a".repeat(64)) }
                else { json!("x".repeat(schema["minLength"].as_u64().unwrap_or(1) as usize)) }
            }
            "integer" => schema.get("minimum").cloned().unwrap_or(json!(0)),
            "boolean" => json!(false),
            "null" => Value::Null,
            _ => panic!("unsupported fixture type"),
        }
    }

    #[test]
    fn every_public_envelope_shape_and_missing_fields() {
        let schemas = Schemas::frozen().unwrap();
        for branch in schemas.contracts["oneOf"].as_array().unwrap() {
            let mut envelope = seed(&schemas,branch,"contracts.schema.json");
            envelope["metadata"]["type"] = envelope["contract_type"].clone();
            for key in ["id","scope","revision","owner","schema_version"] {
                if let Some(value) = envelope["payload"].get(key).cloned() { envelope["metadata"][key] = value; }
            }
            envelope["metadata"]["content_hash"] = json!(strict_json::object_digest(&envelope).unwrap());
            schemas.check_envelope(&envelope).unwrap_or_else(|error| panic!("{}: {error}",envelope["contract_type"]));
            let definition = &schemas.contracts["$defs"][envelope["contract_type"].as_str().unwrap()];
            for required in definition["required"].as_array().unwrap() {
                let mut broken = envelope.clone();
                broken["payload"].as_object_mut().unwrap().remove(required.as_str().unwrap());
                broken["metadata"]["content_hash"] = json!(strict_json::object_digest(&broken).unwrap());
                assert!(schemas.check_envelope(&broken).is_err(),"missing {} in {}",required,envelope["contract_type"]);
            }
        }
    }

    #[test]
    fn altered_metadata_is_not_hash_valid() {
        let schemas = Schemas::frozen().unwrap();
        let branch = &schemas.contracts["oneOf"][0];
        let mut envelope = seed(&schemas,branch,"contracts.schema.json");
        envelope["metadata"]["type"] = envelope["contract_type"].clone();
        envelope["metadata"]["content_hash"] = json!(strict_json::object_digest(&envelope).unwrap());
        schemas.check_envelope(&envelope).unwrap();
        envelope["metadata"]["authority"] = json!("model_inference");
        assert_eq!(schemas.check_envelope(&envelope).unwrap_err().kind,ErrorKind::HashMismatch);
    }
}
