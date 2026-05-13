from __future__ import annotations

import re
from typing import Iterable, Optional

from csp_frontend import CspFunction, CspTranslationUnit


IDENTIFIER_RE = re.compile(r"[A-Za-z_]\w*")


def generate_skeleton_assembly(
    unit: CspTranslationUnit,
    fallback_reason: Optional[str] = None,
) -> str:
    """Emit a compilable assembly scaffold for a parsed CSP translation unit.

    This is intentionally marked as fallback output. It is used to keep the
    Phase 1 .s generation pipeline closed while unsupported C++17 features are
    still being migrated into the real semantic/codegen path.
    """
    functions = unique_defined_functions(unit.skeleton.functions if unit.skeleton else [])
    if not any(function.name == "main" for function in functions):
        raise ValueError("CSP fallback requires a defined main function")

    lines = [
        ".intel_syntax noprefix",
        "# CSP skeleton fallback assembly.",
        "# This file is generated from the self-developed frontend skeleton.",
        "# Unsupported source semantics are not fully lowered yet.",
    ]
    if fallback_reason:
        lines.append("# Fallback reason: %s" % sanitize_comment(fallback_reason))
    if unit.path is not None:
        lines.append("# Source: %s" % sanitize_comment(str(unit.path)))
    lines.append(".text")

    emitted = set()
    for function in functions:
        label = sanitize_label(function.name)
        if label in emitted:
            continue
        emitted.add(label)
        lines.extend(
            [
                "",
                ".globl %s" % label,
                "%s:" % label,
                "    push rbp",
                "    mov rbp, rsp",
                "    xor eax, eax",
                "    pop rbp",
                "    ret",
            ]
        )

    return "\n".join(lines) + "\n"


def unique_defined_functions(functions: Iterable[CspFunction]) -> list[CspFunction]:
    result: list[CspFunction] = []
    seen = set()
    for function in functions:
        if not function.has_body:
            continue
        label = sanitize_label(function.name)
        if label in seen:
            continue
        seen.add(label)
        result.append(function)
    return result


def sanitize_label(name: str) -> str:
    if IDENTIFIER_RE.fullmatch(name):
        return name
    return "csp_fn_" + re.sub(r"\W+", "_", name).strip("_")


def sanitize_comment(text: str) -> str:
    return text.replace("\r", " ").replace("\n", " ")
