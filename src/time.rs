use crate::contracts::Schemas;
use crate::error::{Error,ErrorKind,Result};
use crate::graph::ExactRef;
use crate::resources::registered_evidence;
use crate::store::Store;
use crate::strict_json;
use serde::{Deserialize,Serialize};
use serde_json::{Value,json};

#[derive(Clone,Copy,Debug,Deserialize,Serialize,PartialEq,Eq)]
#[serde(rename_all="snake_case")]
pub enum TimeUnit { Second,Frame,Sample,Tick }

#[derive(Clone,Copy,Debug,Deserialize,Serialize)]
#[serde(rename_all="snake_case")]
pub enum Rounding { Exact,Floor,Ceil,NearestEven }

#[derive(Clone,Debug,Deserialize,Serialize)]
#[serde(deny_unknown_fields)]
pub struct TimeQuantity {
    pub numerator: i64,
    pub denominator: u64,
    pub unit: TimeUnit,
    pub basis_ref: Option<ExactRef>,
    pub rounding: Rounding,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
pub struct TimeConversion {
    pub quantity: TimeQuantity,
    pub target_unit: TimeUnit,
    pub target_basis_ref: Option<ExactRef>,
    pub rounding: Rounding,
}

#[derive(Clone,Copy,Debug,PartialEq,Eq)]
pub(crate) struct Fraction { pub numerator: i128,pub denominator: i128 }

fn greatest_common_divisor(mut left: i128, mut right: i128) -> i128 {
    left=left.abs();
    while right != 0 { let remainder=left%right;left=right;right=remainder; }
    left.max(1)
}

impl Fraction {
    pub(crate) fn new(numerator: i128, denominator: i128) -> Result<Self> {
        if denominator <= 0 || numerator == i128::MIN { return Err(Error::new(ErrorKind::Shape,"positive time denominator and bounded numerator required")); }
        let divisor=greatest_common_divisor(numerator,denominator);
        Ok(Self { numerator:numerator/divisor,denominator:denominator/divisor })
    }

    fn multiply(self, other: Self) -> Result<Self> {
        let left=greatest_common_divisor(self.numerator,other.denominator);
        let right=greatest_common_divisor(other.numerator,self.denominator);
        let numerator=(self.numerator/left).checked_mul(other.numerator/right).ok_or_else(||Error::new(ErrorKind::BudgetExhausted,"exact time numerator overflow"))?;
        let denominator=(self.denominator/right).checked_mul(other.denominator/left).ok_or_else(||Error::new(ErrorKind::BudgetExhausted,"exact time denominator overflow"))?;
        Self::new(numerator,denominator)
    }

    pub(crate) fn compare(self, other: Self) -> Result<std::cmp::Ordering> {
        let divisor=greatest_common_divisor(self.denominator,other.denominator);
        let left=self.numerator.checked_mul(other.denominator/divisor).ok_or_else(||Error::new(ErrorKind::BudgetExhausted,"time comparison overflow"))?;
        let right=other.numerator.checked_mul(self.denominator/divisor).ok_or_else(||Error::new(ErrorKind::BudgetExhausted,"time comparison overflow"))?;
        Ok(left.cmp(&right))
    }

    pub(crate) fn subtract(self, other: Self) -> Result<Self> {
        let divisor=greatest_common_divisor(self.denominator,other.denominator);
        let left=self.numerator.checked_mul(other.denominator/divisor).ok_or_else(||Error::new(ErrorKind::BudgetExhausted,"time difference overflow"))?;
        let right=other.numerator.checked_mul(self.denominator/divisor).ok_or_else(||Error::new(ErrorKind::BudgetExhausted,"time difference overflow"))?;
        let numerator=left.checked_sub(right).ok_or_else(||Error::new(ErrorKind::BudgetExhausted,"time difference overflow"))?;
        let denominator=(self.denominator/divisor).checked_mul(other.denominator).ok_or_else(||Error::new(ErrorKind::BudgetExhausted,"time difference denominator overflow"))?;
        Self::new(numerator,denominator)
    }

    fn round(self, rounding: Rounding) -> Result<Self> {
        if matches!(rounding,Rounding::Exact) { return Ok(self); }
        let floor=self.numerator.div_euclid(self.denominator);
        let remainder=self.numerator.rem_euclid(self.denominator);
        let value=match rounding {
            Rounding::Floor => floor,
            Rounding::Ceil => floor+i128::from(remainder!=0),
            Rounding::NearestEven => {
                let distance=self.denominator-remainder;
                floor+i128::from(remainder>distance || (remainder==distance && floor.rem_euclid(2)!=0))
            },
            Rounding::Exact => unreachable!(),
        };
        Self::new(value,1)
    }
}

pub(crate) struct Basis { pub rate: Fraction,pub origin: Option<ExactRef> }

impl Store {
    pub(crate) fn time_basis(&self, unit: TimeUnit, reference: Option<&ExactRef>) -> Result<Basis> {
        let Some(reference)=reference else {
            return if unit==TimeUnit::Second { Ok(Basis { rate:Fraction::new(1,1)?,origin:None }) }
                else { Err(Error::new(ErrorKind::Reference,"frame/sample/tick require an exact adopted time basis")) };
        };
        let bytes=registered_evidence(&self.connection,&self.workspace,&self.scope,reference)?;
        let value=strict_json::parse(&bytes)?;
        let schemas=Schemas::frozen()?;
        schemas.check_definition("TimeBase",&value)?;
        let basis_unit: TimeUnit=serde_json::from_value(value["unit"].clone())?;
        if basis_unit!=unit { return Err(Error::new(ErrorKind::Shape,"time unit differs from adopted basis; frame rate is not sample rate")); }
        let origin: ExactRef=serde_json::from_value(value["origin_ref"].clone())?;
        registered_evidence(&self.connection,&self.workspace,&self.scope,&origin)?;
        let rate=if unit==TimeUnit::Second {
            if !value["rate"].is_null() { return Err(Error::new(ErrorKind::Shape,"second basis cannot contain a discrete-unit rate")); }
            Fraction::new(1,1)?
        } else {
            let rate_reference:ExactRef=serde_json::from_value(value["rate"].clone())?;
            let rate_bytes=registered_evidence(&self.connection,&self.workspace,&self.scope,&rate_reference)?;
            let adopted_rate=strict_json::parse(&rate_bytes)?;
            schemas.check_definition("Rate",&adopted_rate)?;
            let rate_unit: TimeUnit=serde_json::from_value(adopted_rate["unit"].clone())?;
            if rate_unit!=unit { return Err(Error::new(ErrorKind::Shape,"rate unit and time basis must match")); }
            let profile: ExactRef=serde_json::from_value(adopted_rate["profile_ref"].clone())?;
            registered_evidence(&self.connection,&self.workspace,&self.scope,&profile)?;
            let numerator=adopted_rate["value"]["numerator"].as_u64().ok_or_else(||Error::new(ErrorKind::Shape,"positive rate numerator required"))?;
            let denominator=adopted_rate["value"]["denominator"].as_u64().ok_or_else(||Error::new(ErrorKind::Shape,"positive rate denominator required"))?;
            Fraction::new(i128::from(numerator),i128::from(denominator))?
        };
        Ok(Basis { rate,origin:Some(origin) })
    }

    pub(crate) fn seconds(&self, quantity: &TimeQuantity) -> Result<(Fraction,Option<ExactRef>)> {
        Schemas::frozen()?.check_definition("TimeQuantity",&serde_json::to_value(quantity)?)?;
        let basis=self.time_basis(quantity.unit,quantity.basis_ref.as_ref())?;
        let ratio=Fraction::new(i128::from(quantity.numerator),i128::from(quantity.denominator))?;
        Ok((ratio.multiply(Fraction::new(basis.rate.denominator,basis.rate.numerator)?)?,basis.origin))
    }

    pub fn convert_time(&self, conversion: &TimeConversion) -> Result<Value> {
        let (seconds,origin)=self.seconds(&conversion.quantity)?;
        let target=self.time_basis(conversion.target_unit,conversion.target_basis_ref.as_ref())?;
        if origin.is_some() && target.origin.is_some() && origin!=target.origin {
            return Err(Error::new(ErrorKind::Reference,"different time origins require an explicit retiming map; no implicit rebase"));
        }
        let output=seconds.multiply(target.rate)?.round(conversion.rounding)?;
        let result=TimeQuantity { numerator:i64::try_from(output.numerator).map_err(|_|Error::new(ErrorKind::BudgetExhausted,"converted numerator exceeds contract integer range"))?,
            denominator:u64::try_from(output.denominator).map_err(|_|Error::new(ErrorKind::BudgetExhausted,"converted denominator exceeds contract integer range"))?,
            unit:conversion.target_unit,basis_ref:conversion.target_basis_ref.clone(),rounding:conversion.rounding };
        Ok(json!({"quantity":result,"conversion":"exact-rational-before-explicit-rounding","adopted_basis_hash_checked":true,
            "measured_media_profile":"not_claimed","duration_only":origin.is_none() || target.origin.is_none(),"runtime_authority":false}))
    }
}
