#![forbid(unsafe_code)]

use std::path::Path;
use wuji4::contracts::Schemas;
use wuji4::error::{Error, ErrorKind, Result};
use wuji4::store::Store;
use wuji4::selector::{PreparedIndex, ProjectionTier};
use wuji4::strict_json;
use wuji4::native_protocol::{self, InvocationKind};
use wuji4::native_execution::{NativeDevelopmentPermit, NativeDriverPaths};
use wuji4::resources::{LocalResourceReviewPermit, ResourceKind};
use serde_json::{json, Value};

fn read_json(path: &str) -> Result<Value> {
    let metadata = std::fs::metadata(path)?;
    if metadata.len() > strict_json::MAX_INPUT_BYTES as u64 {
        return Err(Error::new(ErrorKind::BudgetExhausted, "input exceeds 1 MiB"));
    }
    strict_json::parse(&std::fs::read(path)?)
}

fn cli_help() -> Value {
    json!({
        "name":"wuji4", "version":"0.1.0", "stage":"isolated-development",
        "implementation_scope":"local-cli-and-bounded-native-development",
        "acceptance_boundary":"Local implementation is not full G4/G6 acceptance or production installation; P7 requires separate approval.",
        "gate_status":{"G4":"not-claimed","G6":"not-claimed"},
        "commands":[
            "help", "-h", "--help", "check <json>", "hash <json>", "object-hash <envelope-json>",
            "init <existing-absolute-workspace>", "status <workspace>", "task-status <workspace> <task>",
            "plan <workspace> <json>", "register-input <workspace> <id> <relative-file>",
            "plan-catalog-local <workspace> <catalog-root> <plan-json> <lock-json> <roots-json> confirm-isolated-catalog-task",
            "run-local <workspace> <task> <node> <relative-input> <relative-output>", "refresh <workspace>",
            "revise <workspace> <json> <expected-revision> <event-id>", "attempt <workspace> <attempt-id>",
            "repair <workspace> <json> <expected-revision> <event-id>",
            "checkpoint <workspace> <task>", "checkpoint-inspect <workspace> <checkpoint-id>",
            "select <workspace> <index> <index-ref-json> <request-json>",
            "project <workspace> <index> <index-ref-json> <candidate-ref-json> <brief|overview|source> <byte-cap>",
            "recover <workspace>", "cancel <workspace> <task> <expected-revision>", "host-status",
            "resource-propose <workspace> <knowledge|experience> <envelope-json> <expected-revision> <event-id>",
            "resource-review-local <workspace> <knowledge|experience> <reference-json> <event-id> confirm-isolated-project-resource-review",
            "resource-retire <workspace> <knowledge|experience> <reference-json> <event-id>",
            "resource-query <workspace> <knowledge|experience> <exact-trigger-or-empty> <cap>",
            "convert-time <workspace> <conversion-json>",
            "validate-media-chain <workspace> <request-json>",
            "read-evidence <workspace> <reference-json> <offset-bytes> <page-size-bytes>",
            "budget-configuration <isolated-workspace> <reference-json>",
            "register-binary-input <workspace> <id> <relative-file> confirm-isolated-binary-media-input",
            "prepare-recipe <workspace> <catalog-root> <request-json>",
            "execution-summary <workspace> <task-id>",
            "transfer-begin <source> <target> <knowledge|experience> <reference-json> <transfer-id> confirm-isolated-resource-transfer",
            "transfer-accept <source> <target> <transfer-id> confirm-isolated-resource-transfer",
            "transfer-ack <source> <target> <transfer-id> confirm-isolated-resource-transfer",
            "transfer-finalize <source> <target> <transfer-id> confirm-isolated-resource-transfer",
            "transfer-query <source> <target> <transfer-id> confirm-isolated-resource-transfer",
            "transfer-retire <source> <target> <transfer-id> <expected-owner-revision> <event-id> confirm-isolated-resource-transfer",
            "transfer-delta <source> <target> <transfer-id> <request-json> confirm-isolated-resource-transfer confirm-isolated-received-content-delta",
            "transfer-review-delta <source> <target> <transfer-id> <owner-ref-json> <event-id> confirm-isolated-resource-transfer confirm-isolated-project-resource-review",
            "catalog-init <isolated-root> confirm-isolated-local-catalog",
            "catalog-status <root>", "catalog-lock <root> <release-or-active>",
            "catalog-stage <root> <bundle-json> confirm-isolated-local-catalog",
            "catalog-validate-local <root> <lock-json> confirm-isolated-local-catalog",
            "catalog-publish-local <root> <lock-json> <expected-pointer-revision> <event-id> confirm-isolated-local-catalog",
            "catalog-withdraw <root> <lock-json> <expected-pointer-revision> <event-id> confirm-isolated-local-catalog",
            "catalog-repair-index <root> <lock-json> confirm-isolated-local-catalog",
            "catalog-impact <root> <lock-json> <source-ref-json> <offset> <page-size>",
            "catalog-compose <root> <lock-json> <roots-json> <slots-json> <byte-cap>",
            "prepared-roles <existing-absolute-workspace>",
            "prepare-native <workspace> <plan-json> <node> <code|repair|planning>",
            "register-native-input <workspace> <id> <relative-file> confirm-isolated-no-added-fee",
            "plan-native <workspace> <plan-json> confirm-isolated-no-added-fee",
            "run-native <workspace> <task> <node> <code|repair|planning> <absolute-python> <absolute-codex> <absolute-model-catalog-json> confirm-isolated-no-added-fee",
            "accept-native <workspace> <task> <engineering-node> <validation-node> confirm-isolated-no-added-fee"
        ],
        "native_host_verified":false, "P7_installed":false
    })
}

fn run(arguments: &[String]) -> Result<Value> {
    let command = arguments.first().map(String::as_str).unwrap_or("help");
    match (command, arguments.len()) {
        ("help" | "--help" | "-h", 1 | 0) => Ok(cli_help()),
        ("convert-time", 3) => Store::open_existing(Path::new(&arguments[1]))?.convert_time(&serde_json::from_value(read_json(&arguments[2])?)?),
        ("validate-media-chain", 3) => Store::open_existing(Path::new(&arguments[1]))?.validate_media_chain(&serde_json::from_value(read_json(&arguments[2])?)?),
        ("read-evidence", 5) => {
            let reference = serde_json::from_value(read_json(&arguments[2])?)?;
            let offset = arguments[3].parse().map_err(|_| Error::new(ErrorKind::Shape, "evidence offset must be a bounded nonnegative byte count"))?;
            let size = arguments[4].parse().map_err(|_| Error::new(ErrorKind::Shape, "evidence page size must be a bounded positive byte count"))?;
            Store::open_existing(Path::new(&arguments[1]))?.read_evidence_page(&reference, offset, size)
        },
        ("budget-configuration", 3) => Store::open_existing(Path::new(&arguments[1]))?.budget_configuration(&serde_json::from_value(read_json(&arguments[2])?)?),
        ("register-binary-input", 5) => Ok(serde_json::to_value(Store::open_existing(Path::new(&arguments[1]))?.register_local_binary_input(&arguments[2],Path::new(&arguments[3]),&arguments[4])?)?),
        ("prepare-recipe", 4) => Store::open_existing(Path::new(&arguments[1]))?.prepare_recipe(&wuji4::registry::CatalogRegistry::open_existing(Path::new(&arguments[2]))?,&serde_json::from_value(read_json(&arguments[3])?)?),
        ("execution-summary", 3) => Store::open_existing(Path::new(&arguments[1]))?.execution_summary(&arguments[2]),
        ("transfer-begin", 7) => {
            let permit = wuji4::transfers::LocalTransferPermit::confirm(Path::new(&arguments[1]),Path::new(&arguments[2]),&arguments[6])?;
            let mut source = Store::open_existing(Path::new(&arguments[1]))?;
            let target = Store::open_existing(Path::new(&arguments[2]))?;
            source.begin_resource_transfer(&target,&permit,ResourceKind::parse(&arguments[3])?,&serde_json::from_value(read_json(&arguments[4])?)?,&arguments[5])
        }
        ("transfer-accept" | "transfer-ack" | "transfer-finalize" | "transfer-query", 5) => {
            let permit = wuji4::transfers::LocalTransferPermit::confirm(Path::new(&arguments[1]),Path::new(&arguments[2]),&arguments[4])?;
            let mut source = Store::open_existing(Path::new(&arguments[1]))?;
            let mut target = Store::open_existing(Path::new(&arguments[2]))?;
            match command {
                "transfer-accept" => target.accept_resource_transfer(&source,&permit,&arguments[3]),
                "transfer-ack" => target.resource_transfer_ack(&source,&permit,&arguments[3]),
                "transfer-query" => target.query_received_resource(&source,&permit,&arguments[3]),
                _ => source.finalize_resource_transfer(&target,&permit,&arguments[3]),
            }
        }
        ("transfer-delta", 7) => {
            let permit=wuji4::transfers::LocalTransferPermit::confirm(Path::new(&arguments[1]),Path::new(&arguments[2]),&arguments[5])?;
            let source=Store::open_existing(Path::new(&arguments[1]))?;
            let mut target=Store::open_existing(Path::new(&arguments[2]))?;
            target.propose_received_delta(&source,&permit,&arguments[3],&serde_json::from_value(read_json(&arguments[4])?)?,&arguments[6])
        }
        ("transfer-review-delta", 8) => {
            let transfer=wuji4::transfers::LocalTransferPermit::confirm(Path::new(&arguments[1]),Path::new(&arguments[2]),&arguments[6])?;
            let review=LocalResourceReviewPermit::confirm_isolated(Path::new(&arguments[2]),&arguments[7])?;
            let source=Store::open_existing(Path::new(&arguments[1]))?;
            let mut target=Store::open_existing(Path::new(&arguments[2]))?;
            target.review_received_delta(&source,&transfer,&review,&arguments[3],&serde_json::from_value(read_json(&arguments[4])?)?,&arguments[5])
        }
        ("transfer-retire", 7) => {
            let permit = wuji4::transfers::LocalTransferPermit::confirm(Path::new(&arguments[1]),Path::new(&arguments[2]),&arguments[6])?;
            let source = Store::open_existing(Path::new(&arguments[1]))?;
            let mut target = Store::open_existing(Path::new(&arguments[2]))?;
            let revision = arguments[4].parse::<u64>().map_err(|_|Error::new(ErrorKind::Shape,"owner revision must be an integer"))?;
            target.retire_received_resource(&source,&permit,&arguments[3],revision,&arguments[5])
        }
        ("catalog-init", 3) => {
            let permit = wuji4::registry::LocalCatalogPermit::confirm(Path::new(&arguments[1]), &arguments[2])?;
            wuji4::registry::CatalogRegistry::init(Path::new(&arguments[1]), &permit)?.status()
        }
        ("catalog-status", 2) => wuji4::registry::CatalogRegistry::open_existing(Path::new(&arguments[1]))?.status(),
        ("catalog-lock", 3) => {
            let registry = wuji4::registry::CatalogRegistry::open_existing(Path::new(&arguments[1]))?;
            Ok(serde_json::to_value(if arguments[2] == "active" { registry.lock_active()? } else { registry.lock(&arguments[2],true)? })?)
        }
        ("catalog-stage", 4) => {
            let permit = wuji4::registry::LocalCatalogPermit::confirm(Path::new(&arguments[1]), &arguments[3])?;
            let bundle = serde_json::from_value(read_json(&arguments[2])?)?;
            Ok(serde_json::to_value(wuji4::registry::CatalogRegistry::open_existing(Path::new(&arguments[1]))?.stage(&permit,&bundle)?)?)
        }
        ("catalog-validate-local" | "catalog-repair-index", 4) => {
            let permit = wuji4::registry::LocalCatalogPermit::confirm(Path::new(&arguments[1]), &arguments[3])?;
            let lock = serde_json::from_value(read_json(&arguments[2])?)?;
            let mut registry = wuji4::registry::CatalogRegistry::open_existing(Path::new(&arguments[1]))?;
            if command == "catalog-validate-local" { registry.validate_local(&permit,&lock) } else { registry.repair_index(&permit,&lock) }
        }
        ("catalog-publish-local" | "catalog-withdraw", 6) => {
            let permit = wuji4::registry::LocalCatalogPermit::confirm(Path::new(&arguments[1]), &arguments[5])?;
            let lock = serde_json::from_value(read_json(&arguments[2])?)?;
            let revision = arguments[3].parse::<u64>().map_err(|_|Error::new(ErrorKind::Shape,"pointer revision must be an integer"))?;
            let mut registry = wuji4::registry::CatalogRegistry::open_existing(Path::new(&arguments[1]))?;
            if command == "catalog-withdraw" { registry.withdraw(&permit,&lock,revision,&arguments[4]) }
            else { registry.publish_local(&permit,&lock,revision,&arguments[4]) }
        }
        ("catalog-impact", 6) => {
            let lock = serde_json::from_value(read_json(&arguments[2])?)?;
            let reference = serde_json::from_value(read_json(&arguments[3])?)?;
            let offset = arguments[4].parse::<usize>().map_err(|_|Error::new(ErrorKind::Shape,"impact offset must be an integer"))?;
            let cap = arguments[5].parse::<usize>().map_err(|_|Error::new(ErrorKind::Shape,"impact page size must be an integer"))?;
            wuji4::registry::CatalogRegistry::open_existing(Path::new(&arguments[1]))?.impact_page(&lock,&reference,offset,cap)
        }
        ("catalog-compose", 6) => {
            let lock = serde_json::from_value(read_json(&arguments[2])?)?;
            let roots = serde_json::from_value::<Vec<wuji4::graph::ExactRef>>(read_json(&arguments[3])?)?;
            let slots = serde_json::from_value(read_json(&arguments[4])?)?;
            let cap = arguments[5].parse::<usize>().map_err(|_|Error::new(ErrorKind::Shape,"contract byte cap must be an integer"))?;
            wuji4::registry::CatalogRegistry::open_existing(Path::new(&arguments[1]))?.compose_locked(&lock,&roots,&slots,cap)
        }
        ("resource-propose", 6) => {
            let revision = arguments[4].parse::<u64>().map_err(|_| Error::new(ErrorKind::Shape,"expected resource revision must be an integer"))?;
            Store::open_existing(Path::new(&arguments[1]))?.propose_resource(ResourceKind::parse(&arguments[2])?, &read_json(&arguments[3])?, revision, &arguments[5])
        }
        ("resource-review-local", 6) => {
            let permit = LocalResourceReviewPermit::confirm_isolated(Path::new(&arguments[1]), &arguments[5])?;
            Store::open_existing(Path::new(&arguments[1]))?.review_resource_local(&permit, ResourceKind::parse(&arguments[2])?, &serde_json::from_value(read_json(&arguments[3])?)?, &arguments[4])
        }
        ("resource-retire", 5) => Store::open_existing(Path::new(&arguments[1]))?.retire_resource(ResourceKind::parse(&arguments[2])?, &serde_json::from_value(read_json(&arguments[3])?)?, &arguments[4]),
        ("resource-query", 5) => {
            let cap = arguments[4].parse::<usize>().map_err(|_| Error::new(ErrorKind::Shape,"resource query cap must be an integer"))?;
            Store::open_existing(Path::new(&arguments[1]))?.query_resources(ResourceKind::parse(&arguments[2])?, &arguments[3], cap)
        }
        ("prepared-roles", 2) => native_protocol::prepared_roles(Path::new(&arguments[1])),
        ("prepare-native", 5) => Ok(native_protocol::prepare(Path::new(&arguments[1]), &read_json(&arguments[2])?, &arguments[3], InvocationKind::parse(&arguments[4])?)?.report().clone()),
        ("register-native-input", 5) => {
            let permit = NativeDevelopmentPermit::confirm_isolated_no_added_fee(Path::new(&arguments[1]), &arguments[4])?;
            Ok(serde_json::to_value(Store::open_existing(Path::new(&arguments[1]))?.register_native_input(&permit, &arguments[2], Path::new(&arguments[3]))?)?)
        }
        ("plan-native", 4) => {
            let permit = NativeDevelopmentPermit::confirm_isolated_no_added_fee(Path::new(&arguments[1]), &arguments[3])?;
            Store::open_existing(Path::new(&arguments[1]))?.plan_native_development(&permit, &read_json(&arguments[2])?)
        }
        ("run-native", 9) => {
            let permit = NativeDevelopmentPermit::confirm_isolated_no_added_fee(Path::new(&arguments[1]), &arguments[8])?;
            let paths = NativeDriverPaths::new(Path::new(&arguments[5]), Path::new(&arguments[6]), Path::new(&arguments[7]))?;
            Store::open_existing(Path::new(&arguments[1]))?.run_native_development(&permit, &paths, &arguments[2], &arguments[3], InvocationKind::parse(&arguments[4])?)
        }
        ("accept-native", 6) => {
            let permit = NativeDevelopmentPermit::confirm_isolated_no_added_fee(Path::new(&arguments[1]), &arguments[5])?;
            Store::open_existing(Path::new(&arguments[1]))?.accept_native_development(&permit, &arguments[2], &arguments[3], &arguments[4])
        }
        ("hash", 2) => {
            let value = read_json(&arguments[1])?;
            Ok(json!({"codec":"wuji-canonical-json-v1","domain":"complete-json","sha256":strict_json::digest(&value)?,"utf8_bytes":strict_json::canonical(&value)?.len()}))
        }
        ("object-hash", 2) => {
            let value = read_json(&arguments[1])?;
            Ok(json!({"codec":"wuji-canonical-json-v1","domain":"wuji4-object","excluded_field":"metadata.content_hash","sha256":strict_json::object_digest(&value)?,"authority_verified":false}))
        }
        ("check", 2) => {
            Schemas::frozen()?.check_envelope(&read_json(&arguments[1])?)?;
            Ok(json!({"shape_and_object_hash":"pass","authority_verified":false,"native_or_professional_verified":false}))
        }
        ("init", 2) => Store::open(Path::new(&arguments[1]))?.status(),
        ("status", 2) => Store::open_existing(Path::new(&arguments[1]))?.status(),
        ("task-status", 3) => Store::open_existing(Path::new(&arguments[1]))?.task_status(&arguments[2]),
        ("plan-catalog-local", 7) => {
            let lock = serde_json::from_value(read_json(&arguments[4])?)?;
            let roots = serde_json::from_value::<Vec<wuji4::graph::ExactRef>>(read_json(&arguments[5])?)?;
            Store::open_existing(Path::new(&arguments[1]))?.plan_catalog_local(&read_json(&arguments[3])?,Path::new(&arguments[2]),&lock,&roots,&arguments[6])
        }
        ("plan", 3) => Store::open_existing(Path::new(&arguments[1]))?.plan(&read_json(&arguments[2])?),
        ("register-input", 4) => Ok(serde_json::to_value(Store::open_existing(Path::new(&arguments[1]))?.register_local_input(&arguments[2],Path::new(&arguments[3]))?)?),
        ("refresh", 2) => Store::open_existing(Path::new(&arguments[1]))?.refresh_local_evidence(),
        ("revise", 5) => {
            let expected = arguments[3].parse::<i64>().map_err(|_| Error::new(ErrorKind::Shape,"expected graph revision must be integer"))?;
            Store::open_existing(Path::new(&arguments[1]))?.revise_local_plan(&read_json(&arguments[2])?,expected,&arguments[4])
        }
        ("repair", 5) => {
            let expected = arguments[3].parse::<i64>().map_err(|_| Error::new(ErrorKind::Shape,"expected graph revision must be integer"))?;
            Store::open_existing(Path::new(&arguments[1]))?.repair_local_plan(&read_json(&arguments[2])?,expected,&arguments[4])
        }
        ("attempt", 3) => Store::open_existing(Path::new(&arguments[1]))?.inspect_local_attempt(&arguments[2]),
        ("checkpoint", 3) => Store::open_existing(Path::new(&arguments[1]))?.checkpoint_local(&arguments[2]),
        ("checkpoint-inspect", 3) => Store::open_existing(Path::new(&arguments[1]))?.inspect_checkpoint(&arguments[2]),
        ("run-local", 6) => Store::open_existing(Path::new(&arguments[1]))?.copy_local_input(&arguments[2],&arguments[3],Path::new(&arguments[4]),Path::new(&arguments[5])),
        ("select", 5) => {
            let reference = serde_json::from_value(read_json(&arguments[3])?)?;
            PreparedIndex::open(Path::new(&arguments[1]),Path::new(&arguments[2]),reference)?.select(&serde_json::from_value(read_json(&arguments[4])?)?)
        }
        ("project", 7) => {
            let reference = serde_json::from_value(read_json(&arguments[3])?)?;
            let tier = match arguments[5].as_str() { "brief" => ProjectionTier::Brief,"overview" => ProjectionTier::Overview,"source" => ProjectionTier::Source,_ => return Err(Error::new(ErrorKind::Shape,"unknown projection tier")) };
            let cap = arguments[6].parse::<usize>().map_err(|_| Error::new(ErrorKind::Shape,"byte cap must be integer"))?;
            PreparedIndex::open(Path::new(&arguments[1]),Path::new(&arguments[2]),reference)?.project(&serde_json::from_value(read_json(&arguments[4])?)?,tier,cap)
        }
        ("recover", 2) => Store::open_existing(Path::new(&arguments[1]))?.recover(),
        ("cancel", 4) => {
            let expected = arguments[3].parse::<i64>().map_err(|_| Error::new(ErrorKind::Shape,"expected graph revision must be integer"))?;
            Store::open_existing(Path::new(&arguments[1]))?.cancel_local_task(&arguments[2],expected)
        }
        ("host-status", 1) => Ok(json!({"model_policy":"current_selection_baseline_upgrade_only","requested_model":"inherit_current_selection","requested_efforts":{"text":"inherit_current_selection","code":"high","repair_or_planning":"xhigh"},"upgrade_model":"gpt-6.1-sol","automatic_downgrade":false,"failure_fallback_chain":false,"effective_model":"unknown","effective_effort":"unknown","effective_quota":"unknown","fee_precondition":"unknown","admission":"blocked-no-generation-submitted","native_host_verified":false})),
        _ => Err(Error::new(ErrorKind::Shape, "unsupported command or argument count; use help")),
    }
}

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    match run(&arguments) {
        Ok(result) => println!("{}", result),
        Err(error) => {
            eprintln!("{}", json!({"error":format!("{:?}",error.kind),"detail":error.detail,"success":false}));
            std::process::exit(1);
        }
    }
}
