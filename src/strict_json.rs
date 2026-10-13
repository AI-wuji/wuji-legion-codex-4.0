use crate::error::{Error, ErrorKind, Result};
use serde::de::{self, Deserialize, Deserializer, MapAccess, SeqAccess, Visitor};
use serde_json::{Map, Number, Value};
use sha2::{Digest, Sha256};
use std::fmt;

pub const MAX_INPUT_BYTES: usize = 1024 * 1024;

struct StrictValue<const ALLOW_FLOAT: bool>(Value);

impl<'de, const ALLOW_FLOAT: bool> Deserialize<'de> for StrictValue<ALLOW_FLOAT> {
    fn deserialize<D: Deserializer<'de>>(deserializer: D) -> std::result::Result<Self, D::Error> {
        deserializer.deserialize_any(StrictVisitor::<ALLOW_FLOAT>)
    }
}

struct StrictVisitor<const ALLOW_FLOAT: bool>;

impl<'de, const ALLOW_FLOAT: bool> Visitor<'de> for StrictVisitor<ALLOW_FLOAT> {
    type Value = StrictValue<ALLOW_FLOAT>;

    fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("strict JSON without duplicate keys or floating-point numbers")
    }

    fn visit_bool<E: de::Error>(self, value: bool) -> std::result::Result<Self::Value, E> {
        Ok(StrictValue(Value::Bool(value)))
    }

    fn visit_i64<E: de::Error>(self, value: i64) -> std::result::Result<Self::Value, E> {
        Ok(StrictValue(Value::Number(Number::from(value))))
    }

    fn visit_u64<E: de::Error>(self, value: u64) -> std::result::Result<Self::Value, E> {
        Ok(StrictValue(Value::Number(Number::from(value))))
    }

    fn visit_f64<E: de::Error>(self, value: f64) -> std::result::Result<Self::Value, E> {
        if !ALLOW_FLOAT { return Err(E::custom("floating-point JSON is not a core value")); }
        Number::from_f64(value).map(|number| StrictValue(Value::Number(number)))
            .ok_or_else(|| E::custom("non-finite protocol number"))
    }

    fn visit_str<E: de::Error>(self, value: &str) -> std::result::Result<Self::Value, E> {
        Ok(StrictValue(Value::String(value.to_owned())))
    }

    fn visit_string<E: de::Error>(self, value: String) -> std::result::Result<Self::Value, E> {
        Ok(StrictValue(Value::String(value)))
    }

    fn visit_unit<E: de::Error>(self) -> std::result::Result<Self::Value, E> {
        Ok(StrictValue(Value::Null))
    }

    fn visit_seq<A: SeqAccess<'de>>(self, mut sequence: A) -> std::result::Result<Self::Value, A::Error> {
        let mut values = Vec::new();
        while let Some(value) = sequence.next_element::<StrictValue<ALLOW_FLOAT>>()? {
            values.push(value.0);
        }
        Ok(StrictValue(Value::Array(values)))
    }

    fn visit_map<A: MapAccess<'de>>(self, mut map: A) -> std::result::Result<Self::Value, A::Error> {
        let mut values = Map::new();
        while let Some(key) = map.next_key::<String>()? {
            if values.contains_key(&key) {
                return Err(de::Error::custom(format!("duplicate key: {key}")));
            }
            values.insert(key, map.next_value::<StrictValue<ALLOW_FLOAT>>()?.0);
        }
        Ok(StrictValue(Value::Object(values)))
    }
}

pub fn parse(bytes: &[u8]) -> Result<Value> {
    parse_domain::<false>(bytes)
}

pub fn parse_protocol(bytes: &[u8]) -> Result<Value> {
    parse_domain::<true>(bytes)
}

fn parse_domain<const ALLOW_FLOAT: bool>(bytes: &[u8]) -> Result<Value> {
    if bytes.len() > MAX_INPUT_BYTES {
        return Err(Error::new(ErrorKind::BudgetExhausted, "JSON exceeds 1 MiB"));
    }
    let mut deserializer = serde_json::Deserializer::from_slice(bytes);
    let value = StrictValue::<ALLOW_FLOAT>::deserialize(&mut deserializer)?;
    deserializer.end()?;
    Ok(value.0)
}

pub fn canonical(value: &Value) -> Result<Vec<u8>> {
    canonical_domain::<false>(value)
}

pub fn canonical_protocol(value: &Value) -> Result<Vec<u8>> {
    canonical_domain::<true>(value)
}

fn canonical_domain<const ALLOW_FLOAT: bool>(value: &Value) -> Result<Vec<u8>> {
    fn normalize<const ALLOW_FLOAT: bool>(value: &Value, depth: usize) -> Result<Value> {
        if depth > 128 {
            return Err(Error::new(ErrorKind::BudgetExhausted, "JSON nesting exceeds 128"));
        }
        match value {
            Value::Number(number) if !ALLOW_FLOAT && !number.is_i64() && !number.is_u64() => {
                Err(Error::new(ErrorKind::Shape, "floating-point core value"))
            }
            Value::Object(object) => {
                let mut ordered = Map::new();
                let mut keys: Vec<_> = object.keys().collect();
                keys.sort_by(|left, right| left.as_bytes().cmp(right.as_bytes()));
                for key in keys {
                    ordered.insert(key.clone(), normalize::<ALLOW_FLOAT>(&object[key], depth + 1)?);
                }
                Ok(Value::Object(ordered))
            }
            Value::Array(array) => Ok(Value::Array(array.iter().map(|value| normalize::<ALLOW_FLOAT>(value, depth + 1)).collect::<Result<Vec<_>>>()?)),
            _ => Ok(value.clone()),
        }
    }
    Ok(serde_json::to_vec(&normalize::<ALLOW_FLOAT>(value, 0)?)?)
}

pub fn sha256(bytes: &[u8]) -> String {
    Sha256::digest(bytes).iter().map(|byte| format!("{byte:02x}")).collect()
}

pub fn digest(value: &Value) -> Result<String> {
    Ok(sha256(&canonical(value)?))
}

pub fn object_digest(envelope: &Value) -> Result<String> {
    let mut value = envelope.clone();
    value.get_mut("metadata").and_then(Value::as_object_mut)
        .ok_or_else(|| Error::new(ErrorKind::Shape, "missing metadata"))?
        .remove("content_hash");
    let mut bytes = b"wuji4-object\0wuji-canonical-json-v1\0".to_vec();
    bytes.extend(canonical(&value)?);
    Ok(sha256(&bytes))
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn strict_input_failures() {
        for input in [r#"{"id":1,"id":2}"#, r#"{"outer":{"id":1,"id":2}}"#, "1.25", "{}{}", "[NaN]"] {
            assert!(parse(input.as_bytes()).is_err(), "{input}");
        }
    }

    #[test]
    fn canonical_order_and_unicode() {
        let first = parse(r#"{"中文":[2,1],"a":"é"}"#.as_bytes()).unwrap();
        let second = parse(r#"{"a":"é","中文":[2,1]}"#.as_bytes()).unwrap();
        assert_eq!(digest(&first).unwrap(), digest(&second).unwrap());
        assert_ne!(digest(&first).unwrap(), digest(&json!({"a":"é","中文":[2,1]})).unwrap());
        assert_ne!(digest(&first).unwrap(), digest(&json!({"a":"é","中文":[1,2]})).unwrap());
    }

    #[test]
    fn protocol_numbers_do_not_weaken_integer_only_core_contracts() {
        let input = br#"{"argument":{"ratio":0.25},"id":1}"#;
        let protocol = parse_protocol(input).unwrap();
        assert_eq!(protocol["argument"]["ratio"], json!(0.25));
        assert!(parse(input).is_err());
        assert!(canonical(&protocol).is_err());
        assert!(canonical_protocol(&protocol).is_ok());
        for invalid in [r#"{"outer":{"ratio":0.25,"ratio":0.5}}"#, r#"{"ratio":NaN}"#, r#"{"ratio":1e999}"#, "{}{}"] {
            assert!(parse_protocol(invalid.as_bytes()).is_err());
        }
    }

    #[test]
    fn object_hash_excludes_only_self_hash() {
        let first = json!({"metadata":{"content_hash":"first","owner":"writer"},"payload":{"sha256":"asset"}});
        let mut second = first.clone();
        second["metadata"]["content_hash"] = json!("second");
        assert_eq!(object_digest(&first).unwrap(), object_digest(&second).unwrap());
        second["metadata"]["owner"] = json!("other");
        assert_ne!(object_digest(&first).unwrap(), object_digest(&second).unwrap());
    }
}
