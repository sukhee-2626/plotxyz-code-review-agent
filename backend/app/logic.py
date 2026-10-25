"""Original deterministic implementation for Code Review (plotxyz-code-review-agent)."""
from __future__ import annotations

import ast
import csv
import io
import json
import math
import os
import re
import statistics
import time
from collections import Counter, defaultdict, deque


class LogicError(ValueError):
    """Raised when supplied input cannot be processed."""


def _text(payload, key, min_len=1, max_len=20000):
    value = payload.get(key)
    if not isinstance(value, str):
        raise LogicError(f"'{key}' must be a string")
    value = value.strip()
    if len(value) < min_len:
        raise LogicError(f"'{key}' is required")
    if len(value) > max_len:
        raise LogicError(f"'{key}' exceeds {max_len} characters")
    return value


def _num(payload, key, default=None, lo=None, hi=None):
    value = payload.get(key, default)
    if value is None or value == "":
        if default is None:
            raise LogicError(f"'{key}' is required")
        return default
    if isinstance(value, bool):
        raise LogicError(f"'{key}' must be numeric")
    try:
        number = float(value)
    except (TypeError, ValueError):
        raise LogicError(f"'{key}' must be numeric")
    if lo is not None and number < lo:
        raise LogicError(f"'{key}' must be at least {lo}")
    if hi is not None and number > hi:
        raise LogicError(f"'{key}' must be at most {hi}")
    return number


def _json(payload, key, expected=None, max_len=200000):
    raw = payload.get(key)
    if isinstance(raw, (dict, list)):
        data = raw
    elif isinstance(raw, str):
        if len(raw) > max_len:
            raise LogicError(f"'{key}' exceeds {max_len} characters")
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise LogicError(f"'{key}' is not valid JSON: {exc.msg} at line {exc.lineno}")
    else:
        raise LogicError(f"'{key}' must be JSON")
    if expected is not None and not isinstance(data, expected):
        name = expected.__name__ if hasattr(expected, "__name__") else str(expected)
        raise LogicError(f"'{key}' must be a JSON {name}")
    return data


def _csv(payload, key, max_rows=5000):
    text = _text(payload, key, max_len=2000000)
    try:
        reader = csv.DictReader(io.StringIO(text))
        if not reader.fieldnames:
            raise LogicError(f"'{key}' must include a header row")
        columns = [str(c).strip() for c in reader.fieldnames if c and str(c).strip()]
        if not columns:
            raise LogicError(f"'{key}' must include named columns")
        rows = []
        for index, raw in enumerate(reader):
            if index >= max_rows:
                raise LogicError(f"'{key}' exceeds {max_rows} rows")
            rows.append({col: (raw.get(col) or "").strip() for col in columns})
    except csv.Error as exc:
        raise LogicError(f"'{key}' is not valid CSV: {exc}")
    if not rows:
        raise LogicError(f"'{key}' must include at least one data row")
    return columns, rows


STOPWORDS = {'will', 'they', 'was', 'your', 'than', 'that', 'on', 'be', 'then', 'do', 'our', 'with', 'he', 'is', 'about', 'had', 'were', 'as', 'may', 'we', 'their', 'are', 'did', 'at', 'she', 'a', 'by', 'the', 'if', 'might', 'it', 'into', 'have', 'from', 'should', 'not', 'over', 'can', 'for', 'and', 'an', 'you', 'does', 'to', 'this', 'could', 'would', 'under', 'of', 'no', 'its', 'in', 'i', 'or', 'has'}


def _tokens(text):
    return [w for w in re.findall(r"[a-z0-9][a-z0-9_+-]{1,}", text.lower()) if w not in STOPWORDS]


def _sentences(text):
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [p.strip(" -•\t") for p in parts if len(p.strip()) > 2]


def provider_status():
    """Report which optional model providers are configured (never exposes secrets)."""
    ollama = bool(os.getenv("OLLAMA_BASE_URL"))
    openai = bool(os.getenv("OPENAI_BASE_URL") and os.getenv("OPENAI_MODEL"))
    return {"ollama_compatible": ollama, "openai_compatible": openai}


def _llm(messages, temperature=0.2):
    """Call an explicitly configured OpenAI-compatible endpoint; return None when unavailable."""
    base = os.getenv("OPENAI_BASE_URL", "").rstrip("/")
    model = os.getenv("OPENAI_MODEL", "")
    if not base or not model:
        ollama = os.getenv("OLLAMA_BASE_URL", "").rstrip("/")
        if not ollama:
            return None
        base = f"{ollama}/v1"
        model = os.getenv("OLLAMA_MODEL", "")
    if not model:
        return None
    try:
        import httpx

        headers = {"Content-Type": "application/json"}
        key = os.getenv("OPENAI_API_KEY")
        if key:
            headers["Authorization"] = f"Bearer {key}"
        with httpx.Client(timeout=20) as client:
            response = client.post(
                f"{base}/chat/completions",
                headers=headers,
                json={"model": model, "messages": messages, "temperature": temperature},
            )
            response.raise_for_status()
            return str(response.json()["choices"][0]["message"]["content"]).strip()
    except Exception:
        return None


def _result(summary, result, warnings=None):
    return {"summary": summary, "result": result, "warnings": warnings or []}


def agent_code_review(payload):
    code = _text(payload, "code", max_len=60000)
    language = str(payload.get("language", "python")).lower()
    findings, rows = [], []
    metrics = {"lines": len(code.splitlines()), "functions": 0, "max_function_lines": 0}
    if language == "python":
        try:
            tree = ast.parse(code)
        except SyntaxError as exc:
            findings.append({"title": "Syntax error", "severity": "high", "detail": f"Line {exc.lineno}: {exc.msg}"})
            tree = None
        if tree is not None:
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    length = (node.end_lineno or node.lineno) - node.lineno + 1
                    metrics["functions"] += 1
                    metrics["max_function_lines"] = max(metrics["max_function_lines"], length)
                    rows.append([node.name, node.lineno, length, len(node.args.args)])
                    if length > 40:
                        findings.append({"title": "Long function", "severity": "medium", "detail": f"'{node.name}' is {length} lines; consider extracting helpers."})
                    depth = 0
                    for child in ast.walk(node):
                        if isinstance(child, (ast.If, ast.For, ast.While, ast.Try, ast.With)):
                            depth += 1
                    if depth > 8:
                        findings.append({"title": "High nesting", "severity": "medium", "detail": f"'{node.name}' contains {depth} control-flow nodes; reduce nesting."})
    else:
        findings.append({"title": "Limited language support", "severity": "info", "detail": "AST checks run for Python; other languages receive pattern-based checks only."})
    patterns = [
        ("Dynamic execution", r"\b(eval|exec)\s*\(", "high", "Avoid executing dynamic strings."),
        ("Shell invocation", r"subprocess\.[^(]+\([^)]*shell\s*=\s*True", "high", "shell=True can enable command injection."),
        ("Hardcoded credential", r"(?i)(password|api_key|secret|token)\s*=\s*['\"][^'\"]{4,}['\"]", "high", "Move credentials to environment variables."),
        ("Unsafe deserialization", r"\bpickle\.loads?\s*\(", "medium", "Do not unpickle untrusted data."),
        ("Broad exception", r"except\s*:", "medium", "Catch specific exceptions."),
        ("TODO marker", r"#\s*TODO\b", "low", "Track unfinished work explicitly."),
    ]
    for label, pattern, severity, detail in patterns:
        count = len(re.findall(pattern, code))
        if count:
            findings.append({"title": label, "severity": severity, "detail": f"{detail} Found {count} occurrence(s)."})
    score = max(0, 100 - sum({"high": 18, "medium": 8, "low": 3}[f["severity"]] for f in findings))
    metrics["score"] = score
    return _result(
        f"Review score {score}/100 with {len(findings)} finding(s).",
        {
            "metrics": metrics,
            "findings": findings,
            "table": {"columns": ["Function", "Line", "Length", "Args"], "rows": rows},
            "items": ["Add tests for the changed behavior.", "Keep functions under roughly 40 lines where practical."],
        },
        ["Heuristic review only; it does not prove the absence of vulnerabilities."],
    )


run = agent_code_review
