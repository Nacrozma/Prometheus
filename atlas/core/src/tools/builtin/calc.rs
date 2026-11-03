//! Safe arithmetic evaluator (recursive descent; no code execution).

use super::descriptor;
use crate::tools::{PermissionClass, Tool, ToolContext, ToolDescriptor, ToolError};
use async_trait::async_trait;
use serde_json::{json, Value};

pub struct Calculator(ToolDescriptor);

impl Calculator {
    pub fn new() -> Self {
        Self(descriptor(
            "calc.evaluate",
            "Calculator",
            "Evaluate an arithmetic expression exactly as written. Supports + - * / % ^, parentheses, \
             functions sqrt abs sin cos tan asin acos atan ln log10 log2 exp floor ceil round min max pow, \
             and constants pi and e. Trigonometry uses radians.",
            "compute",
            PermissionClass::ReadOnly,
            false,
            json!({"type":"object","properties":{"expression":{"type":"string","minLength":1,"maxLength":500}},"required":["expression"],"additionalProperties":false}),
            json!({"type":"object","properties":{"expression":{"type":"string"},"result":{"type":"number"}},"required":["expression","result"]}),
            5,
            "No data access; pure computation on this computer.",
        ))
    }
}

impl Default for Calculator {
    fn default() -> Self {
        Self::new()
    }
}

#[async_trait]
impl Tool for Calculator {
    fn descriptor(&self) -> &ToolDescriptor {
        &self.0
    }
    async fn execute(&self, input: Value, _ctx: &ToolContext) -> Result<Value, ToolError> {
        let expr = input["expression"].as_str().unwrap_or_default();
        let result = evaluate(expr).map_err(|m| ToolError::new("invalid_expression", m))?;
        Ok(json!({"expression": expr, "result": result}))
    }
}

pub fn evaluate(src: &str) -> Result<f64, String> {
    let mut p = Parser { s: src.as_bytes(), i: 0, depth: 0 };
    let v = p.expr()?;
    p.ws();
    if p.i != p.s.len() {
        return Err(format!("unexpected '{}' at position {}", p.s[p.i] as char, p.i + 1));
    }
    if !v.is_finite() {
        return Err("result is not a finite number (division by zero or overflow)".into());
    }
    Ok(v)
}

struct Parser<'a> {
    s: &'a [u8],
    i: usize,
    depth: u32,
}

impl Parser<'_> {
    fn ws(&mut self) {
        while self.i < self.s.len() && self.s[self.i].is_ascii_whitespace() {
            self.i += 1;
        }
    }
    fn peek(&mut self) -> Option<u8> {
        self.ws();
        self.s.get(self.i).copied()
    }
    fn eat(&mut self, c: u8) -> bool {
        if self.peek() == Some(c) {
            self.i += 1;
            true
        } else {
            false
        }
    }
    fn enter(&mut self) -> Result<(), String> {
        self.depth += 1;
        if self.depth > 64 { Err("expression is nested too deeply".into()) } else { Ok(()) }
    }
    fn expr(&mut self) -> Result<f64, String> {
        self.enter()?;
        let mut v = self.term()?;
        loop {
            if self.eat(b'+') {
                v += self.term()?;
            } else if self.eat(b'-') {
                v -= self.term()?;
            } else {
                break;
            }
        }
        self.depth -= 1;
        Ok(v)
    }
    fn term(&mut self) -> Result<f64, String> {
        let mut v = self.unary()?;
        loop {
            if self.eat(b'*') {
                v *= self.unary()?;
            } else if self.eat(b'/') {
                v /= self.unary()?;
            } else if self.eat(b'%') {
                v %= self.unary()?;
            } else {
                break;
            }
        }
        Ok(v)
    }
    fn unary(&mut self) -> Result<f64, String> {
        if self.eat(b'-') {
            self.enter()?;
            let v = -self.unary()?;
            self.depth -= 1;
            return Ok(v);
        }
        if self.eat(b'+') {
            return self.unary();
        }
        self.power()
    }
    fn power(&mut self) -> Result<f64, String> {
        let base = self.atom()?;
        if self.eat(b'^') {
            self.enter()?;
            let exp = self.unary()?; // right-associative
            self.depth -= 1;
            return Ok(base.powf(exp));
        }
        Ok(base)
    }
    fn atom(&mut self) -> Result<f64, String> {
        match self.peek() {
            Some(b'(') => {
                self.i += 1;
                let v = self.expr()?;
                if !self.eat(b')') {
                    return Err("missing ')'".into());
                }
                Ok(v)
            }
            Some(c) if c.is_ascii_digit() || c == b'.' => self.number(),
            Some(c) if c.is_ascii_alphabetic() => self.ident(),
            Some(c) => Err(format!("unexpected '{}'", c as char)),
            None => Err("unexpected end of expression".into()),
        }
    }
    fn number(&mut self) -> Result<f64, String> {
        let start = self.i;
        while self.i < self.s.len() && (self.s[self.i].is_ascii_digit() || self.s[self.i] == b'.' || self.s[self.i] == b'_') {
            self.i += 1;
        }
        if self.i < self.s.len() && (self.s[self.i] == b'e' || self.s[self.i] == b'E') {
            let save = self.i;
            self.i += 1;
            if self.i < self.s.len() && (self.s[self.i] == b'+' || self.s[self.i] == b'-') {
                self.i += 1;
            }
            if self.i < self.s.len() && self.s[self.i].is_ascii_digit() {
                while self.i < self.s.len() && self.s[self.i].is_ascii_digit() {
                    self.i += 1;
                }
            } else {
                self.i = save;
            }
        }
        let text: String = String::from_utf8_lossy(&self.s[start..self.i]).replace('_', "");
        text.parse::<f64>().map_err(|_| format!("invalid number '{text}'"))
    }
    fn ident(&mut self) -> Result<f64, String> {
        let start = self.i;
        while self.i < self.s.len() && (self.s[self.i].is_ascii_alphanumeric()) {
            self.i += 1;
        }
        let name = String::from_utf8_lossy(&self.s[start..self.i]).to_lowercase();
        match name.as_str() {
            "pi" => return Ok(std::f64::consts::PI),
            "e" => return Ok(std::f64::consts::E),
            _ => {}
        }
        if !self.eat(b'(') {
            return Err(format!("unknown name '{name}'"));
        }
        let mut args = vec![self.expr()?];
        while self.eat(b',') {
            args.push(self.expr()?);
        }
        if !self.eat(b')') {
            return Err("missing ')'".into());
        }
        let one = |f: fn(f64) -> f64| -> Result<f64, String> {
            if args.len() != 1 { Err(format!("{name}() takes 1 argument")) } else { Ok(f(args[0])) }
        };
        match name.as_str() {
            "sqrt" => one(f64::sqrt),
            "abs" => one(f64::abs),
            "sin" => one(f64::sin),
            "cos" => one(f64::cos),
            "tan" => one(f64::tan),
            "asin" => one(f64::asin),
            "acos" => one(f64::acos),
            "atan" => one(f64::atan),
            "ln" => one(f64::ln),
            "log10" | "log" => one(f64::log10),
            "log2" => one(f64::log2),
            "exp" => one(f64::exp),
            "floor" => one(f64::floor),
            "ceil" => one(f64::ceil),
            "round" => one(f64::round),
            "min" if !args.is_empty() => Ok(args.iter().cloned().fold(f64::INFINITY, f64::min)),
            "max" if !args.is_empty() => Ok(args.iter().cloned().fold(f64::NEG_INFINITY, f64::max)),
            "pow" if args.len() == 2 => Ok(args[0].powf(args[1])),
            _ => Err(format!("unknown function '{name}'")),
        }
    }
}

#[cfg(test)]
mod tests {
    use super::evaluate;

    #[test]
    fn arithmetic() {
        assert_eq!(evaluate("2 + 3 * 4").unwrap(), 14.0);
        assert_eq!(evaluate("(2 + 3) * 4").unwrap(), 20.0);
        assert_eq!(evaluate("2 ^ 3 ^ 2").unwrap(), 512.0);
        assert_eq!(evaluate("-2 ^ 2").unwrap(), -4.0);
        assert_eq!(evaluate("10 % 4").unwrap(), 2.0);
        assert!((evaluate("sqrt(16) + sin(pi/2)").unwrap() - 5.0).abs() < 1e-12);
        assert_eq!(evaluate("max(1, 7, 3)").unwrap(), 7.0);
        assert_eq!(evaluate("1_000 * 1.5e2").unwrap(), 150_000.0);
    }

    #[test]
    fn errors() {
        assert!(evaluate("1/0").is_err());
        assert!(evaluate("2 +").is_err());
        assert!(evaluate("system(1)").is_err());
        assert!(evaluate(&"(".repeat(200)).is_err());
        assert!(evaluate("1 2").is_err());
    }
}
