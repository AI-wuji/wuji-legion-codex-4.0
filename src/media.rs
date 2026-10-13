use crate::contracts::Schemas;
use crate::error::{Error,ErrorKind,Result};
use crate::graph::ExactRef;
use crate::resources::registered_evidence;
use crate::store::Store;
use crate::strict_json;
use crate::time::{Fraction,TimeQuantity,TimeUnit};
use serde::Deserialize;
use serde_json::{Value,json};
use std::collections::{BTreeMap,BTreeSet};

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct MediaChainRequest {
    pub story_ref: ExactRef,
    pub music_refs: Vec<ExactRef>,
    pub shot_refs: Vec<ExactRef>,
    pub timeline_ref: Option<ExactRef>,
    #[serde(default)]
    pub sound_package_ref: Option<ExactRef>,
}

#[derive(Clone)]
struct Span { start:Fraction,end:Fraction,origin:Option<ExactRef> }

pub fn timeline_retiming_binding(scope: &str, payload: &Value) -> Result<String> {
    let mut content = payload.clone();
    content.as_object_mut().ok_or_else(|| Error::new(ErrorKind::Shape, "timeline payload must be an object"))?
        .remove("retiming_map");
    let mut bytes = b"wuji4-timeline-retiming-v1\0".to_vec();
    bytes.extend(strict_json::canonical(&json!({"scope": scope, "timeline_payload": content}))?);
    Ok(strict_json::sha256(&bytes))
}

fn validate_clip_order(span: &Span, prior: &Span, prior_overlap: Fraction) -> Result<()> {
    if span.start.compare(prior.start)? == std::cmp::Ordering::Less
        || (span.start.compare(prior.end)? == std::cmp::Ordering::Less
            && prior.end.subtract(span.start)?.compare(prior_overlap)? == std::cmp::Ordering::Greater) {
        return Err(Error::new(ErrorKind::Shape, "timeline clip spans must be ordered and overlap only within the prior transition"));
    }
    Ok(())
}

fn exact_refs(value: &Value) -> Result<Vec<ExactRef>> { Ok(serde_json::from_value(value.clone())?) }

fn ensure_unique_refs(references: &[ExactRef], detail: &str) -> Result<()> {
    for (index, reference) in references.iter().enumerate() {
        if references[..index].iter().any(|previous| previous == reference) {
            return Err(Error::new(ErrorKind::Reference, detail));
        }
    }
    Ok(())
}

fn wave_duration(bytes: &[u8]) -> Result<(Fraction,Value)> {
    if bytes.len()<12 || &bytes[..4]!=b"RIFF" || &bytes[8..12]!=b"WAVE" {
        return Err(Error::new(ErrorKind::Shape,"bounded local music preparation requires an actual PCM WAV asset"));
    }
    let riff_size=u32::from_le_bytes(bytes[4..8].try_into().unwrap()) as usize;
    if riff_size.checked_add(8)!=Some(bytes.len()) { return Err(Error::new(ErrorKind::Shape,"RIFF declared size differs from actual bytes")); }
    let mut offset=12;
    let mut format=None;
    let mut data=None;
    let mut chunks=0;
    while offset<bytes.len() {
        chunks+=1;
        if chunks>64 || bytes.len()-offset<8 { return Err(Error::new(ErrorKind::Shape,"invalid or excessive WAV chunks")); }
        let tag=&bytes[offset..offset+4];
        let length=u32::from_le_bytes(bytes[offset+4..offset+8].try_into().unwrap()) as usize;
        let start=offset+8;
        let end=start.checked_add(length).ok_or_else(||Error::new(ErrorKind::Shape,"WAV chunk size overflow"))?;
        if end>bytes.len() { return Err(Error::new(ErrorKind::Shape,"WAV chunk extends beyond actual asset")); }
        if tag==b"fmt " {
            if format.is_some() || length!=16 { return Err(Error::new(ErrorKind::Shape,"single canonical PCM WAV fmt chunk required")); }
            let encoding=u16::from_le_bytes(bytes[start..start+2].try_into().unwrap());
            let channels=u16::from_le_bytes(bytes[start+2..start+4].try_into().unwrap());
            let rate=u32::from_le_bytes(bytes[start+4..start+8].try_into().unwrap());
            let byte_rate=u32::from_le_bytes(bytes[start+8..start+12].try_into().unwrap());
            let alignment=u16::from_le_bytes(bytes[start+12..start+14].try_into().unwrap());
            let bits=u16::from_le_bytes(bytes[start+14..start+16].try_into().unwrap());
            if encoding!=1 || !(1..=8).contains(&channels) || !(8000..=192000).contains(&rate)
                || ![16,24,32].contains(&bits) || alignment!=channels*(bits/8) || byte_rate!=rate*u32::from(alignment) {
                return Err(Error::new(ErrorKind::Shape,"unsupported or inconsistent WAV format; no sample/frame confusion"));
            }
            format=Some((channels,rate,alignment,bits));
        } else if tag==b"data" {
            if data.replace(length).is_some() { return Err(Error::new(ErrorKind::Shape,"multiple WAV data chunks not admitted")); }
        }
        offset=end.checked_add(length%2).ok_or_else(||Error::new(ErrorKind::Shape,"WAV padding overflow"))?;
        if offset>bytes.len() { return Err(Error::new(ErrorKind::Shape,"missing WAV padding byte")); }
    }
    let (channels,rate,alignment,bits)=format.ok_or_else(||Error::new(ErrorKind::Shape,"WAV fmt missing"))?;
    let data=data.ok_or_else(||Error::new(ErrorKind::Shape,"WAV data missing"))?;
    if data==0 || data%usize::from(alignment)!=0 { return Err(Error::new(ErrorKind::Shape,"WAV sample data must be nonempty and block-aligned")); }
    let samples=data/usize::from(alignment);
    Ok((Fraction::new(samples as i128,i128::from(rate))?,json!({"channels":channels,"sample_rate":rate,"bits_per_sample":bits,"sample_frames":samples,"format":"PCM-WAV"})))
}

impl Store {
    fn media_envelope(&self, reference: &ExactRef, kind: &str) -> Result<Value> {
        let bytes=registered_evidence(&self.connection,&self.workspace,&self.scope,reference)?;
        let envelope=strict_json::parse(&bytes)?;
        Schemas::frozen()?.check_envelope(&envelope)?;
        if envelope["contract_type"]!=kind || envelope["metadata"]["scope"]!=self.scope
            || envelope["metadata"]["classification"]!="project_private" || envelope["metadata"]["authority"]!="review_proposal" {
            return Err(Error::new(ErrorKind::ScopeDenied,"local media preparation only reads current same-project proposal contracts"));
        }
        Ok(envelope)
    }

    fn media_span(&self, payload: &Value) -> Result<Span> {
        let start: TimeQuantity=serde_json::from_value(payload["start"].clone())?;
        let end: TimeQuantity=serde_json::from_value(payload["end"].clone())?;
        let (start,start_origin)=self.seconds(&start)?;
        let (end,end_origin)=self.seconds(&end)?;
        if start_origin!=end_origin || start.numerator<0 || start.compare(end)?!=std::cmp::Ordering::Less {
            return Err(Error::new(ErrorKind::Shape,"positive ordered media span with one explicit origin required"));
        }
        Ok(Span { start,end,origin:start_origin })
    }

    fn timeline_timebase(&self, value: &Value) -> Result<ExactRef> {
        let schemas = Schemas::frozen()?;
        schemas.check_definition("TimeBase", value)?;
        let unit: TimeUnit = serde_json::from_value(value["unit"].clone())?;
        let origin: ExactRef = serde_json::from_value(value["origin_ref"].clone())?;
        registered_evidence(&self.connection, &self.workspace, &self.scope, &origin)?;
        match unit {
            TimeUnit::Second => {
                if !value["rate"].is_null() {
                    return Err(Error::new(ErrorKind::Shape, "second timeline timebase cannot contain a discrete rate"));
                }
            }
            TimeUnit::Frame | TimeUnit::Sample | TimeUnit::Tick => {
                let rate_ref: ExactRef = serde_json::from_value(value["rate"].clone())?;
                let rate_bytes = registered_evidence(&self.connection, &self.workspace, &self.scope, &rate_ref)?;
                let rate = strict_json::parse(&rate_bytes)?;
                schemas.check_definition("Rate", &rate)?;
                let rate_unit: TimeUnit = serde_json::from_value(rate["unit"].clone())?;
                if rate_unit != unit {
                    return Err(Error::new(ErrorKind::Shape, "timeline timebase rate unit differs from its time unit"));
                }
                let profile: ExactRef = serde_json::from_value(rate["profile_ref"].clone())?;
                registered_evidence(&self.connection, &self.workspace, &self.scope, &profile)?;
            }
        }
        Ok(origin)
    }

    fn timeline_rate(&self, value: &Value) -> Result<Value> {
        let schemas = Schemas::frozen()?;
        schemas.check_definition("Rate", value)?;
        let unit: TimeUnit = serde_json::from_value(value["unit"].clone())?;
        if unit != TimeUnit::Frame {
            return Err(Error::new(ErrorKind::Shape, "timeline frame_rate must be a frame-per-second rate"));
        }
        let profile: ExactRef = serde_json::from_value(value["profile_ref"].clone())?;
        let bytes = registered_evidence(&self.connection, &self.workspace, &self.scope, &profile)?;
        let declaration = strict_json::parse(&bytes)?;
        let object = declaration.as_object().ok_or_else(|| Error::new(ErrorKind::Shape, "frame rate declaration object required"))?;
        let rates = declaration["supported_rates"].as_array().ok_or_else(|| Error::new(ErrorKind::Shape, "declared supported frame rates required"))?;
        if object.len() != 2 || declaration["profile_type"] != "frame_rate_declaration"
            || rates.is_empty() || rates.len() > 32 {
            return Err(Error::new(ErrorKind::Shape, "bounded frame_rate_declaration required; arbitrary bytes are not a rate profile"));
        }
        let declared = Fraction::new(i128::from(value["value"]["numerator"].as_u64().unwrap()),
            i128::from(value["value"]["denominator"].as_u64().unwrap()))?;
        let mut supported = false;
        for rate in rates {
            schemas.check_definition("PositiveRational", rate)?;
            let rate = Fraction::new(i128::from(rate["numerator"].as_u64().unwrap()), i128::from(rate["denominator"].as_u64().unwrap()))?;
            supported |= declared == rate;
        }
        if !supported { return Err(Error::new(ErrorKind::Reference, "frame rate is not supported by its exact declaration")); }
        Ok(json!({"unit": unit, "value": value["value"], "profile_ref": profile,
            "profile_scope": "declared_rates_only_not_measured_media"}))
    }

    fn timeline_span(&self, payload: &Value, duration: Fraction, origin: &ExactRef) -> Result<(Span, Fraction)> {
        let span = self.media_span(payload)?;
        if span.origin.as_ref().is_some_and(|reference| reference != origin) {
            return Err(Error::new(ErrorKind::Reference, "timeline clip uses a different time origin"));
        }
        if span.start.numerator < 0 || span.end.compare(duration)? == std::cmp::Ordering::Greater {
            return Err(Error::new(ErrorKind::Shape, "timeline clip must stay within the positive story duration"));
        }
        let overlap_quantity: TimeQuantity = serde_json::from_value(payload["transition_overlap"].clone())?;
        let (overlap, overlap_origin) = self.seconds(&overlap_quantity)?;
        if overlap.numerator < 0 || overlap_origin.as_ref().is_some_and(|reference| reference != origin)
            || overlap.compare(span.end.subtract(span.start)?)? == std::cmp::Ordering::Greater {
            return Err(Error::new(ErrorKind::Shape, "timeline transition overlap must be nonnegative and bounded by its clip"));
        }
        Ok((span, overlap))
    }

    fn validate_retiming_map(&self, reference: &ExactRef, timeline_id: &str, timeline_revision: u64,
        binding: &str, timeline_origin: &ExactRef, clips: &[(ExactRef, Span)]) -> Result<(ExactRef, Value)> {
        let bytes = registered_evidence(&self.connection, &self.workspace, &self.scope, reference)?;
        let value = strict_json::parse(&bytes)?;
        let object = value.as_object().ok_or_else(|| Error::new(ErrorKind::Shape, "retiming map must be a strict JSON object"))?;
        if object.len() != 5 || !object.contains_key("timeline_id") || !object.contains_key("timeline_revision")
            || !object.contains_key("timeline_binding_sha256")
            || !object.contains_key("source_ref") || !object.contains_key("segments") {
            return Err(Error::new(ErrorKind::Shape, "retiming map requires identity, revision, content binding, source_ref and segments only"));
        }
        if value["timeline_id"].as_str() != Some(timeline_id) || value["timeline_revision"].as_u64() != Some(timeline_revision)
            || value["timeline_binding_sha256"].as_str() != Some(binding) {
            return Err(Error::new(ErrorKind::Reference, "retiming map is not bound to this timeline content, scope and revision"));
        }
        let source: ExactRef = serde_json::from_value(value["source_ref"].clone())?;
        let (_, target_span) = clips.iter().find(|(candidate, _)| candidate == &source)
            .ok_or_else(|| Error::new(ErrorKind::Reference, "retiming map source is not one of the exact timeline shots"))?;
        let segments = value["segments"].as_array().ok_or_else(|| Error::new(ErrorKind::Shape, "retiming map segments array required"))?;
        if segments.is_empty() || segments.len() > 64 {
            return Err(Error::new(ErrorKind::BudgetExhausted, "retiming map requires 1..64 bounded segments"));
        }
        let source_envelope = self.media_envelope(&source, "ShotPlan")?;
        let source_span = self.media_span(&source_envelope["payload"])?;
        if source_span.origin.as_ref().is_some_and(|origin| origin != timeline_origin) {
            return Err(Error::new(ErrorKind::Reference, "retiming source shot uses a different timeline origin"));
        }
        let mut previous_source: Option<Span> = None;
        let mut previous_target: Option<Span> = None;
        for segment in segments {
            let segment_object = segment.as_object().ok_or_else(|| Error::new(ErrorKind::Shape, "retiming segment must be an object"))?;
            if segment_object.len() != 4 || !segment_object.contains_key("source_start") || !segment_object.contains_key("source_end")
                || !segment_object.contains_key("target_start") || !segment_object.contains_key("target_end") {
                return Err(Error::new(ErrorKind::Shape, "retiming segment requires source and target start/end only"));
            }
            let source_payload = json!({"start": segment["source_start"], "end": segment["source_end"]});
            let target_payload = json!({"start": segment["target_start"], "end": segment["target_end"]});
            let current_source = self.media_span(&source_payload)?;
            let current_target = self.media_span(&target_payload)?;
            if current_source.origin != source_span.origin
                || current_target.origin.as_ref().is_some_and(|origin| origin != timeline_origin)
                || current_source.start.compare(source_span.start)? == std::cmp::Ordering::Less
                || current_source.end.compare(source_span.end)? == std::cmp::Ordering::Greater
                || current_target.start.compare(target_span.start)? == std::cmp::Ordering::Less
                || current_target.end.compare(target_span.end)? == std::cmp::Ordering::Greater {
                return Err(Error::new(ErrorKind::Shape, "retiming segment is outside its exact source shot or target clip"));
            }
            let source_start = previous_source.as_ref().map_or(source_span.start, |previous| previous.end);
            let target_start = previous_target.as_ref().map_or(target_span.start, |previous| previous.end);
            if current_source.start.compare(source_start)? != std::cmp::Ordering::Equal
                || current_target.start.compare(target_start)? != std::cmp::Ordering::Equal {
                return Err(Error::new(ErrorKind::Shape, "retiming segments must cover their spans contiguously without gaps or overlap"));
            }
            previous_source = Some(current_source);
            previous_target = Some(current_target);
        }
        if previous_source.unwrap().end.compare(source_span.end)? != std::cmp::Ordering::Equal
            || previous_target.unwrap().end.compare(target_span.end)? != std::cmp::Ordering::Equal {
            return Err(Error::new(ErrorKind::Shape, "retiming segments must cover the full source shot and target clip"));
        }
        Ok((source.clone(), json!({"reference": reference, "timeline_id": timeline_id, "timeline_revision": timeline_revision,
            "timeline_binding_sha256": binding, "source_ref": source, "segments": segments.len()})))
    }

    fn validate_timeline(&self, reference: &ExactRef, story_ref: &ExactRef, music_refs: &[ExactRef],
        shot_refs: &[ExactRef], duration: Fraction) -> Result<Value> {
        let envelope = self.media_envelope(reference, "TimelineManifest")?;
        let payload = &envelope["payload"];
        let stories = exact_refs(&payload["story_refs"])?;
        let shots = exact_refs(&payload["shot_refs"])?;
        let music = exact_refs(&payload["music_refs"])?;
        if stories != vec![story_ref.clone()] || shots != shot_refs || music != music_refs {
            return Err(Error::new(ErrorKind::Reference, "timeline must bind the exact current story, shots and music cue list"));
        }
        ensure_unique_refs(&shots, "timeline contains duplicate shot references")?;
        ensure_unique_refs(&music, "timeline contains duplicate music references")?;
        let origin = self.timeline_timebase(&payload["timebase"])?;
        let frame_rate = self.timeline_rate(&payload["frame_rate"])?;
        if payload["timebase"]["unit"] == "frame" {
            let rate_ref: ExactRef = serde_json::from_value(payload["timebase"]["rate"].clone())?;
            let bytes = registered_evidence(&self.connection, &self.workspace, &self.scope, &rate_ref)?;
            if strict_json::parse(&bytes)? != payload["frame_rate"] {
                return Err(Error::new(ErrorKind::Reference, "frame timebase rate must equal the exact declared timeline frame_rate"));
            }
        }
        let clips = payload["clip_spans"].as_array().ok_or_else(|| Error::new(ErrorKind::Shape, "timeline clip_spans array required"))?;
        if clips.len() != shot_refs.len() || clips.len() > 64 {
            return Err(Error::new(ErrorKind::Reference, "timeline must provide exactly one bounded clip span per requested shot"));
        }
        let mut seen = Vec::new();
        let mut previous: Option<(Span, Fraction)> = None;
        let mut clip_checks = Vec::new();
        let mut clip_spans = Vec::new();
        for clip in clips {
            let clip_ref: ExactRef = serde_json::from_value(clip["clip_ref"].clone())?;
            if !shot_refs.iter().any(|candidate| candidate == &clip_ref) || seen.iter().any(|candidate: &ExactRef| candidate == &clip_ref) {
                return Err(Error::new(ErrorKind::Reference, "timeline clip must reference each requested shot exactly once"));
            }
            let (span, overlap) = self.timeline_span(clip, duration, &origin)?;
            if let Some((prior, prior_overlap)) = &previous {
                validate_clip_order(&span, prior, *prior_overlap)?;
            }
            seen.push(clip_ref.clone());
            clip_spans.push((clip_ref.clone(), span.clone()));
            previous = Some((span, overlap));
            clip_checks.push(json!({"clip_ref": clip_ref, "span_checked": true, "transition_checked": true}));
        }
        let retiming_refs = exact_refs(&payload["retiming_map"])?;
        ensure_unique_refs(&retiming_refs, "timeline contains duplicate retiming maps")?;
        let mut retiming_checks = Vec::new();
        let timeline_id = payload["timeline_id"].as_str().ok_or_else(|| Error::new(ErrorKind::Shape, "timeline id missing"))?;
        let timeline_revision = payload["revision"].as_u64().ok_or_else(|| Error::new(ErrorKind::Shape, "timeline revision missing"))?;
        let binding = timeline_retiming_binding(&self.scope, payload)?;
        let mut mapped = Vec::new();
        for retiming in &retiming_refs {
            let (source, check) = self.validate_retiming_map(retiming, timeline_id, timeline_revision, &binding, &origin, &clip_spans)?;
            if mapped.contains(&source) { return Err(Error::new(ErrorKind::Reference, "only one complete retiming map per source shot is admitted")); }
            mapped.push(source);
            retiming_checks.push(check);
        }
        for (shot, clip_span) in &clip_spans {
            let source = self.media_envelope(shot, "ShotPlan")?;
            let span = self.media_span(&source["payload"])?;
            if span.origin.as_ref().is_some_and(|reference| reference != &origin) {
                return Err(Error::new(ErrorKind::Reference, "shot origin differs from the timeline origin"));
            }
            if (span.start != clip_span.start || span.end != clip_span.end) && !mapped.contains(shot) {
                return Err(Error::new(ErrorKind::Reference, "changed clip timing requires a content-bound complete retiming map"));
            }
        }
        Ok(json!({"reference": reference, "revision": payload["revision"], "timebase_origin": origin,
            "frame_rate": frame_rate, "clip_checks": clip_checks, "retiming_checks": retiming_checks,
            "downstream_revalidation": "not_implemented_no_minimal_closure_claim"}))
    }

    fn validate_sound_package(&self, reference: &ExactRef, timeline_ref: &ExactRef, music_refs: &[ExactRef]) -> Result<Value> {
        let envelope = self.media_envelope(reference, "SoundPackage")?;
        let payload = &envelope["payload"];
        let target: ExactRef = serde_json::from_value(payload["target_timeline_ref"].clone())?;
        if &target != timeline_ref {
            return Err(Error::new(ErrorKind::Reference, "sound package must target the exact current timeline revision"));
        }
        let package_music = exact_refs(&payload["music_cue_refs"])?;
        if package_music != music_refs {
            return Err(Error::new(ErrorKind::Reference, "sound package music cues differ from the exact timeline inputs"));
        }
        ensure_unique_refs(&package_music, "sound package contains duplicate music cue references")?;
        let mut counts = BTreeMap::new();
        let mut audio_checks = Vec::new();
        for field in ["srt_refs", "dialogue_refs", "stems", "buses", "automation_refs", "render_refs"] {
            let references = exact_refs(&payload[field])?;
            if references.len() > 64 { return Err(Error::new(ErrorKind::BudgetExhausted, "local sound evidence lists are bounded to 64 references")); }
            ensure_unique_refs(&references, "sound package contains duplicate evidence references")?;
            for item in &references {
                let bytes = registered_evidence(&self.connection, &self.workspace, &self.scope, item)?;
                if field == "stems" || field == "render_refs" {
                    let (_, profile) = wave_duration(&bytes)?;
                    audio_checks.push(json!({"field": field, "reference": item, "audio_profile": profile}));
                }
            }
            counts.insert(field, references.len());
        }
        let validation: ExactRef = serde_json::from_value(payload["validation"].clone())?;
        registered_evidence(&self.connection, &self.workspace, &self.scope, &validation)?;
        Ok(json!({"reference": reference, "target_timeline_ref": target, "music_checked": true,
            "evidence_counts": counts, "validation_ref": validation, "professional_effectiveness": "not_claimed",
            "validation_scope": "reference_integrity_and_bounded_pcm_only", "pcm_checks": audio_checks,
            "bus_routing_checked": false, "automation_semantics_checked": false, "render_executed": false}))
    }

    pub fn validate_media_chain(&self, request: &MediaChainRequest) -> Result<Value> {
        if request.music_refs.is_empty() || request.music_refs.len()>16 || request.shot_refs.is_empty() || request.shot_refs.len()>64 {
            return Err(Error::new(ErrorKind::BudgetExhausted,"bounded media recipe requires 1..16 cues and 1..64 shots"));
        }
        let story=self.media_envelope(&request.story_ref,"StoryPlan")?;
        let duration: TimeQuantity=serde_json::from_value(story["payload"]["duration_target"].clone())?;
        let (duration,_)=self.seconds(&duration)?;
        if duration.numerator<=0 { return Err(Error::new(ErrorKind::Shape,"story duration must be positive")); }
        let mut cues=BTreeMap::new();
        let mut cue_checks=Vec::new();
        let mut origin=None;
        for reference in &request.music_refs {
            let envelope=self.media_envelope(reference,"MusicCuePlan")?;
            let payload=&envelope["payload"];
            if cues.contains_key(&reference.id) || payload["story_segment_ref"]!=serde_json::to_value(&request.story_ref)? || payload["lock_level"]!="adopted" {
                return Err(Error::new(ErrorKind::Reference,"cue requires an exact current story and explicitly supplied adopted input; no duplicate/latest fallback"));
            }
            let asset: ExactRef=serde_json::from_value(payload["asset"].clone()).map_err(|_|Error::new(ErrorKind::Reference,"music must be backed by actual audio, not a mood-only intent"))?;
            let rights: ExactRef=serde_json::from_value(payload["rights"].clone()).map_err(|_|Error::new(ErrorKind::Reference,"music rights evidence reference required"))?;
            let audio=registered_evidence(&self.connection,&self.workspace,&self.scope,&asset)?;
            registered_evidence(&self.connection,&self.workspace,&self.scope,&rights)?;
            for anchor in exact_refs(&payload["phrase_anchors"])?.into_iter().chain(exact_refs(&payload["beat_anchors"])?) {
                registered_evidence(&self.connection,&self.workspace,&self.scope,&anchor)?;
            }
            let span=self.media_span(payload)?;
            if span.end.compare(duration)?==std::cmp::Ordering::Greater { return Err(Error::new(ErrorKind::Shape,"music cue exceeds story duration")); }
            if cues.is_empty() { origin=span.origin.clone(); }
            else if span.origin!=origin { return Err(Error::new(ErrorKind::Reference,"music cues must share the same explicit origin")); }
            let (audio_duration,profile)=wave_duration(&audio)?;
            if span.end.subtract(span.start)?.compare(audio_duration)?==std::cmp::Ordering::Greater {
                return Err(Error::new(ErrorKind::Shape,"actual pre-cut audio is shorter than the cue; no implied looping"));
            }
            cue_checks.push(json!({"reference":reference,"asset":asset,"rights_evidence":rights,"audio_profile":profile,"rights_authority_verified":false}));
            cues.insert(reference.id.clone(),(reference.clone(),span));
        }
        let mut shot_ids=BTreeSet::new();
        let mut shot_checks=Vec::new();
        for reference in &request.shot_refs {
            let envelope=self.media_envelope(reference,"ShotPlan")?;
            let payload=&envelope["payload"];
            let stories=exact_refs(&payload["story_refs"])?;
            let music=exact_refs(&payload["music_refs"])?;
            if !shot_ids.insert(reference.id.clone()) || stories!=vec![request.story_ref.clone()] || music.is_empty() {
                return Err(Error::new(ErrorKind::Reference,"shot must use the same exact story and preexisting actual music cues"));
            }
            let span=self.media_span(payload)?;
            if span.origin!=origin || span.end.compare(duration)?==std::cmp::Ordering::Greater {
                return Err(Error::new(ErrorKind::Shape,"shot time origin or duration differs from the adopted cue/story"));
            }
            for reference in music {
                let (exact,cue)=cues.get(&reference.id).ok_or_else(||Error::new(ErrorKind::Reference,"shot refers to an unprepared music cue"))?;
                if &reference!=exact || span.start.compare(cue.end)?!=std::cmp::Ordering::Less || cue.start.compare(span.end)?!=std::cmp::Ordering::Less {
                    return Err(Error::new(ErrorKind::Reference,"shot music reference is stale or has no actual temporal intersection"));
                }
            }
            for reference in exact_refs(&payload["visual_refs"])? { registered_evidence(&self.connection,&self.workspace,&self.scope,&reference)?; }
            for field in ["dialogue_ref","srt_ref"] {
                if !payload[field].is_null() {
                    registered_evidence(&self.connection,&self.workspace,&self.scope,&serde_json::from_value(payload[field].clone())?)?;
                }
            }
            shot_checks.push(json!({"reference":reference,"start_checked":true,"end_checked":true,"music_precedes_shot_preparation":true,"beat_forced_cuts":false}));
        }
        let timeline_check = request.timeline_ref.as_ref().map(|timeline| self.validate_timeline(timeline, &request.story_ref, &request.music_refs, &request.shot_refs, duration)).transpose()?;
        let sound_check = match (&request.timeline_ref, &request.sound_package_ref) {
            (Some(timeline), Some(sound)) => Some(self.validate_sound_package(sound, timeline, &request.music_refs)?),
            (None, Some(_)) => return Err(Error::new(ErrorKind::Reference, "sound package requires an exact timeline manifest")),
            _ => None,
        };
        Ok(json!({"state":"prepared","recipe":"story-actual-pcm-cue-shot-timeline-sound-contracts","story":request.story_ref,"cues":cue_checks,"shots":shot_checks,
            "timeline":timeline_check,"sound_package":sound_check,
            "acceptance_scope":"actual-adopted-files-exact-refs-and-time-contracts","model_or_professional_effectiveness":"not_claimed",
            "runtime_admission":false,"REAPER_executed":false,"global_or_publish_authority":false}))
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn clip_comparison_and_overlap_arithmetic_overflow_fail_closed() {
        let zero = Fraction::new(0, 1).unwrap();
        let prior = Span { start: Fraction::new(2, 3).unwrap(), end: Fraction::new(1, 1).unwrap(), origin: None };
        let span = Span { start: Fraction::new(2, i128::MAX).unwrap(), end: Fraction::new(1, 1).unwrap(), origin: None };
        assert_eq!(validate_clip_order(&span, &prior, zero).unwrap_err().kind, ErrorKind::BudgetExhausted);
        let prior = Span { start: zero, end: Fraction::new(2, 3).unwrap(), origin: None };
        assert_eq!(validate_clip_order(&span, &prior, zero).unwrap_err().kind, ErrorKind::BudgetExhausted);
    }
}
