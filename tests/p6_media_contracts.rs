use serde_json::{Value,json};
use std::fs;
use std::path::{Path,PathBuf};
use std::time::{SystemTime,UNIX_EPOCH};
use wuji4::error::ErrorKind;
use wuji4::graph::ExactRef;
use wuji4::media::{MediaChainRequest,timeline_retiming_binding};
use wuji4::store::Store;
use wuji4::strict_json;

fn time(numerator: i64,denominator: u64) -> Value {
    json!({"numerator":numerator,"denominator":denominator,"unit":"second","basis_ref":null,"rounding":"exact"})
}

fn file(root: &Path,store: &mut Store,name: &str,bytes: &[u8]) -> ExactRef {
    fs::write(root.join(name),bytes).unwrap();
    if name.ends_with(".wav") { store.register_local_binary_input(&format!("user/{name}"),Path::new(name),"confirm-isolated-binary-media-input").unwrap() }
    else { store.register_local_input(&format!("user/{name}"),Path::new(name)).unwrap() }
}

fn contract(root: &Path,store: &mut Store,name: &str,kind: &str,payload: Value) -> ExactRef {
    let mut envelope=json!({"schema_version":1,"contract_type":kind,"payload":payload,"metadata":{
        "id":name,"type":kind,"scope":store.scope(),"schema_version":1,"revision":1,"owner":"aji-local",
        "authority":"review_proposal","status":"proposal","source_refs":[],"evidence_refs":[],"created_at_utc_ms":1,"updated_at_utc_ms":1,
        "valid_until_utc_ms":null,"classification":"project_private","content_hash":"0".repeat(64),"parent_refs":[]}});
    envelope["metadata"]["content_hash"]=json!(strict_json::object_digest(&envelope).unwrap());
    file(root,store,name,&strict_json::canonical(&envelope).unwrap())
}

fn wave() -> Vec<u8> {
    let data_size=16000u32;
    let mut bytes=Vec::new();
    bytes.extend(b"RIFF");
    bytes.extend((36+data_size).to_le_bytes());
    bytes.extend(b"WAVEfmt ");
    bytes.extend(16u32.to_le_bytes());
    bytes.extend(1u16.to_le_bytes());
    bytes.extend(1u16.to_le_bytes());
    bytes.extend(8000u32.to_le_bytes());
    bytes.extend(16000u32.to_le_bytes());
    bytes.extend(2u16.to_le_bytes());
    bytes.extend(16u16.to_le_bytes());
    bytes.extend(b"data");
    bytes.extend(data_size.to_le_bytes());
    for sample in 0..8000 { bytes.extend(if sample%20<10 { 512i16 } else { -512i16 }.to_le_bytes()); }
    bytes
}

fn setup() -> (PathBuf,Store,MediaChainRequest,Value,Value) {
    let root=Path::new(env!("CARGO_MANIFEST_DIR")).join(".dev/media-acceptance")
        .join(format!("{}-{}",std::process::id(),SystemTime::now().duration_since(UNIX_EPOCH).unwrap().as_nanos()));
    fs::create_dir_all(&root).unwrap();
    let mut store=Store::open(&root).unwrap();
    let audio=file(&root,&mut store,"synthetic.wav",&wave());
    let rights=file(&root,&mut store,"rights.txt",b"This project generated this synthetic PCM fixture; no external music and no professional quality claim.");
    let story=contract(&root,&mut store,"story.json","StoryPlan",json!({"text":"A local two-second fixture","version":1,
        "segment_ids":["segment-1"],"duration_target":time(2,1),"narrative_functions":["demonstrate contracts"],
        "emotion_curve":["neutral"],"invariants":["no published artifacts"],"voice_roles":[]}));
    let cue=json!({"cue_id":"cue","story_segment_ref":story,"emotion":"neutral fixture","density":"sparse","asset":audio,"rights":rights,
        "start":time(0,1),"end":time(1,1),"transition":"no transition","phrase_anchors":[],"beat_anchors":[],"ducking":[],"lock_level":"adopted"});
    let cue_ref=contract(&root,&mut store,"cue.json","MusicCuePlan",cue.clone());
    let shot=json!({"shot_id":"shot","story_refs":[story],"music_refs":[cue_ref],"start":time(0,1),"end":time(4,5),
        "camera":"static","action":"show local fixture","visual_refs":[],"dialogue_ref":null,"srt_ref":null,"sound_intent":"actual synthetic audio",
        "transition":"none","generation_requirements":["no claim of professional video"]});
    let shot_ref=contract(&root,&mut store,"shot.json","ShotPlan",shot.clone());
    (root,store,MediaChainRequest { story_ref:story,music_refs:vec![cue_ref],shot_refs:vec![shot_ref],timeline_ref:None,sound_package_ref:None },cue,shot)
}

fn timeline_fixture(root: &Path, store: &mut Store, request: &MediaChainRequest) -> (Value, Value) {
    let profile=file(root,store,"frame-profile.json",&strict_json::canonical(&json!({
        "profile_type":"frame_rate_declaration","supported_rates":[{"numerator":24,"denominator":1}]})).unwrap());
    let timeline=json!({"timeline_id":"timeline-1","revision":1,
        "timebase":{"unit":"second","rate":null,"origin_ref":request.story_ref},
        "frame_rate":{"value":{"numerator":24,"denominator":1},"unit":"frame","per_unit":"second","profile_ref":profile},
        "clip_spans":[{"clip_ref":request.shot_refs[0],"start":time(0,1),"end":time(1,1),"transition_overlap":time(0,1)}],
        "retiming_map":[],"story_refs":[request.story_ref],"shot_refs":request.shot_refs,
        "music_refs":request.music_refs,"owner":"aji-local"});
    let retiming=json!({"timeline_id":"timeline-1","timeline_revision":1,
        "timeline_binding_sha256":timeline_retiming_binding(store.scope(),&timeline).unwrap(),"source_ref":request.shot_refs[0],
        "segments":[{"source_start":time(0,1),"source_end":time(2,5),"target_start":time(0,1),"target_end":time(1,2)},
                    {"source_start":time(2,5),"source_end":time(4,5),"target_start":time(1,2),"target_end":time(1,1)}]});
    (timeline,retiming)
}

fn adopt_timeline(root: &Path, store: &mut Store, request: &mut MediaChainRequest, mut timeline: Value, retiming: Option<Value>) {
    if let Some(retiming)=retiming {
        timeline["retiming_map"]=json!([file(root,store,"retiming.json",&strict_json::canonical(&retiming).unwrap())]);
    }
    request.timeline_ref=Some(contract(root,store,"timeline.json","TimelineManifest",timeline));
}

#[test]
fn actual_pcm_cue_precedes_exact_shot_preparation_without_beat_forced_cuts() {
    let (_,store,request,_,_)=setup();
    let result=store.validate_media_chain(&request).unwrap();
    assert_eq!(result["state"],"prepared");
    assert_eq!(result["cues"][0]["audio_profile"]["sample_rate"],8000);
    assert_eq!(result["cues"][0]["audio_profile"]["sample_frames"],8000);
    assert_eq!(result["shots"][0]["beat_forced_cuts"],false);
    assert_eq!(result["runtime_admission"],false);
    assert_eq!(result["REAPER_executed"],false);
    assert_eq!(result["cues"][0]["rights_authority_verified"],false);
}

#[test]
fn exact_timeline_retiming_and_sound_package_validate_without_professional_effect_claim() {
    let (root,mut store,mut request,_,_)=setup();
    let (timeline,retiming)=timeline_fixture(&root,&mut store,&request);
    adopt_timeline(&root,&mut store,&mut request,timeline,Some(retiming));
    let timeline=request.timeline_ref.clone().unwrap();
    let stem=file(&root,&mut store,"stem.wav",&wave());
    let bus=file(&root,&mut store,"bus.json",b"bus fixture");
    let automation=file(&root,&mut store,"automation.json",b"automation fixture");
    let render=file(&root,&mut store,"render.wav",&wave());
    let validation=file(&root,&mut store,"sound-validation.json",b"validation fixture");
    let sound=contract(&root,&mut store,"sound.json","SoundPackage",json!({
        "target_timeline_ref":timeline,"music_cue_refs":request.music_refs,"srt_refs":[],"dialogue_refs":[],
        "stems":[stem],"buses":[bus],"automation_refs":[automation],"render_refs":[render],"validation":validation}));
    request.timeline_ref=Some(timeline);
    request.sound_package_ref=Some(sound);
    let result=store.validate_media_chain(&request).unwrap();
    assert_eq!(result["state"],"prepared");
    assert_eq!(result["timeline"]["retiming_checks"][0]["segments"],2);
    assert_eq!(result["sound_package"]["evidence_counts"]["stems"],1);
    assert_eq!(result["sound_package"]["professional_effectiveness"],"not_claimed");
    assert_eq!(result["sound_package"]["pcm_checks"].as_array().unwrap().len(),2);
    assert_eq!(result["sound_package"]["bus_routing_checked"],false);
    assert_eq!(result["sound_package"]["render_executed"],false);
    assert_eq!(result["timeline"]["downstream_revalidation"],"not_implemented_no_minimal_closure_claim");
}

#[test]
fn retiming_same_identity_changed_content_missing_map_and_stale_parent_fail_closed() {
    for mutation in ["changed_clip","changed_owner","missing_map","old_revision","old_binding","legacy_identity_only"] {
        let (root,mut store,mut request,_,_)=setup();
        let (mut timeline,mut retiming)=timeline_fixture(&root,&mut store,&request);
        match mutation {
            "changed_clip" => timeline["clip_spans"][0]["end"]=time(6,5),
            "changed_owner" => timeline["owner"]=json!("different-owner"),
            "missing_map" => {},
            "old_revision" => retiming["timeline_revision"]=json!(2),
            "old_binding" => retiming["timeline_binding_sha256"]=json!("0".repeat(64)),
            "legacy_identity_only" => { retiming.as_object_mut().unwrap().remove("timeline_binding_sha256"); },
            _ => unreachable!(),
        }
        adopt_timeline(&root,&mut store,&mut request,timeline,if mutation=="missing_map" { None } else { Some(retiming) });
        assert!(store.validate_media_chain(&request).is_err(),"{mutation}");
    }
}

#[test]
fn retiming_gaps_overlap_reverse_partial_and_out_of_clip_segments_are_rejected() {
    for mutation in ["source_gap","source_overlap","target_gap","target_overlap","reverse","partial","outside_clip","outside_shot","extra_key"] {
        let (root,mut store,mut request,_,_)=setup();
        let (timeline,mut retiming)=timeline_fixture(&root,&mut store,&request);
        match mutation {
            "source_gap" => retiming["segments"][1]["source_start"]=time(1,2),
            "source_overlap" => retiming["segments"][1]["source_start"]=time(1,5),
            "target_gap" => retiming["segments"][1]["target_start"]=time(3,5),
            "target_overlap" => retiming["segments"][1]["target_start"]=time(2,5),
            "reverse" => retiming["segments"][0]["source_start"]=time(3,5),
            "partial" => { retiming["segments"].as_array_mut().unwrap().pop(); },
            "outside_clip" => retiming["segments"][1]["target_end"]=time(6,5),
            "outside_shot" => retiming["segments"][1]["source_end"]=time(1,1),
            "extra_key" => retiming["segments"][0]["unapproved"]=json!(true),
            _ => unreachable!(),
        }
        adopt_timeline(&root,&mut store,&mut request,timeline,Some(retiming));
        assert!(store.validate_media_chain(&request).is_err(),"{mutation}");
    }
}

#[test]
fn timeline_profile_arbitrary_bytes_unsupported_rate_and_discrete_rate_mismatch_are_rejected() {
    for mutation in ["arbitrary_profile","unsupported_rate","discrete_mismatch"] {
        let (root,mut store,mut request,_,_)=setup();
        let (mut timeline,mut retiming)=timeline_fixture(&root,&mut store,&request);
        match mutation {
            "arbitrary_profile" => timeline["frame_rate"]["profile_ref"]=json!(file(&root,&mut store,"opaque-profile.json",b"not a profile")),
            "unsupported_rate" => timeline["frame_rate"]["value"]["numerator"]=json!(30),
            "discrete_mismatch" => {
                let mut rate=timeline["frame_rate"].clone();
                rate["value"]["numerator"]=json!(30);
                timeline["timebase"]["unit"]=json!("frame");
                timeline["timebase"]["rate"]=json!(file(&root,&mut store,"frame-rate.json",&strict_json::canonical(&rate).unwrap()));
            },
            _ => unreachable!(),
        }
        retiming["timeline_binding_sha256"]=json!(timeline_retiming_binding(store.scope(),&timeline).unwrap());
        adopt_timeline(&root,&mut store,&mut request,timeline,Some(retiming));
        assert!(store.validate_media_chain(&request).is_err(),"{mutation}");
    }
}

#[test]
fn unmodified_clip_needs_no_retiming_and_changed_evidence_cannot_replay() {
    let (root,mut store,mut request,_,_)=setup();
    let (mut timeline,_)=timeline_fixture(&root,&mut store,&request);
    timeline["clip_spans"][0]["end"]=time(4,5);
    adopt_timeline(&root,&mut store,&mut request,timeline,None);
    assert!(store.validate_media_chain(&request).is_ok());
    fs::write(root.join("frame-profile.json"),b"changed after registration").unwrap();
    assert!(store.validate_media_chain(&request).is_err());
}

#[test]
fn sound_package_arbitrary_pcm_stale_evidence_and_wrong_timeline_fail_closed() {
    for mutation in ["arbitrary_pcm","stale_evidence","wrong_timeline"] {
        let (root,mut store,mut request,_,_)=setup();
        let (timeline,retiming)=timeline_fixture(&root,&mut store,&request);
        adopt_timeline(&root,&mut store,&mut request,timeline,Some(retiming));
        let stem=file(&root,&mut store,"stem.wav",if mutation=="arbitrary_pcm" { b"placeholder".to_vec() } else { wave() }.as_slice());
        let validation=file(&root,&mut store,"validation.txt",b"reference-integrity-only");
        let mut target=request.timeline_ref.clone().unwrap();
        if mutation=="wrong_timeline" { target.revision+=1; }
        request.sound_package_ref=Some(contract(&root,&mut store,"sound.json","SoundPackage",json!({
            "target_timeline_ref":target,"music_cue_refs":request.music_refs,"srt_refs":[],"dialogue_refs":[],
            "stems":[stem],"buses":[],"automation_refs":[],"render_refs":[],"validation":validation})));
        if mutation=="stale_evidence" { fs::write(root.join("validation.txt"),b"changed").unwrap(); }
        assert!(store.validate_media_chain(&request).is_err(),"{mutation}");
    }
}

#[test]
fn mood_only_cue_missing_rights_short_asset_and_stale_shot_references_fail_closed() {
    let (root,mut store,mut request,mut cue,mut shot)=setup();
    cue["asset"]=Value::Null;
    request.music_refs=vec![contract(&root,&mut store,"intent.json","MusicCuePlan",cue.clone())];
    assert_eq!(store.validate_media_chain(&request).unwrap_err().kind,ErrorKind::Reference);
    cue["asset"]=shot["music_refs"][0].clone();
    cue["rights"]=Value::Null;
    request.music_refs=vec![contract(&root,&mut store,"no-rights.json","MusicCuePlan",cue)];
    assert_eq!(store.validate_media_chain(&request).unwrap_err().kind,ErrorKind::Reference);
    let (root,mut store,mut request,mut cue,_)=setup();
    cue["end"]=time(2,1);
    request.music_refs=vec![contract(&root,&mut store,"short.json","MusicCuePlan",cue)];
    assert_eq!(store.validate_media_chain(&request).unwrap_err().kind,ErrorKind::Shape);
    let (root,mut store,mut request,_,original_shot)=setup();
    shot=original_shot;
    shot["music_refs"][0]["revision"]=json!(2);
    request.shot_refs=vec![contract(&root,&mut store,"stale-shot.json","ShotPlan",shot)];
    assert_eq!(store.validate_media_chain(&request).unwrap_err().kind,ErrorKind::Reference);
}

#[test]
fn source_changes_malformed_pcm_scope_mismatch_and_unsupported_timeline_are_not_completed() {
    let (root,store,mut request,_,_)=setup();
    request.timeline_ref=Some(request.story_ref.clone());
    assert_eq!(store.validate_media_chain(&request).unwrap_err().kind,ErrorKind::ScopeDenied);
    request.timeline_ref=None;
    fs::write(root.join("synthetic.wav"),b"changed source").unwrap();
    assert_eq!(store.validate_media_chain(&request).unwrap_err().kind,ErrorKind::ValidationStale);
    let (root,mut store,mut request,mut cue,_)=setup();
    let mut audio=wave();
    audio[28]=0;
    cue["asset"]=serde_json::to_value(file(&root,&mut store,"malformed.wav",&audio)).unwrap();
    request.music_refs=vec![contract(&root,&mut store,"malformed-cue.json","MusicCuePlan",cue)];
    assert_eq!(store.validate_media_chain(&request).unwrap_err().kind,ErrorKind::Shape);
    let (_,other_store,_,_,_)=setup();
    assert_eq!(other_store.validate_media_chain(&request).unwrap_err().kind,ErrorKind::ScopeDenied);
}
