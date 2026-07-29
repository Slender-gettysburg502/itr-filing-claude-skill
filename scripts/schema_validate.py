#!/usr/bin/env python3
"""
schema_validate.py -- a small JSON Schema Draft-04 validator, standard library
only, for checking a built ITR-2 return against the department's schema when
`jsonschema` is not installed.

    python scripts/schema_validate.py filled.json
    python scripts/schema_validate.py --audit-only

Why this exists: an offline or locked-down machine has no `jsonschema`, and a
build that silently skips validation is worse than one that fails, because you
find out at the portal instead of at your desk.

## The implemented keyword set was measured, not assumed

Every keyword below was found by walking schema/ITR-2_2026_Main_V1.1.json and
counting what it actually uses. The counts are from that measurement:

    type (1194)        minimum (714)       maximum (711)      $ref (675)
    exclusiveMinimum (625)                 allOf (321)
    additionalProperties (292)             properties (292)   required (258)
    maxLength (186)    pattern (146)       minLength (142)    enum (111)
    items (87)         exclusiveMaximum (34)                  minItems (21)
    multipleOf (17)    maxItems (6)

Eighteen keywords. What the measurement also settled, each of which is a way to
get this wrong:

  * Draft-04, so `exclusiveMinimum` and `exclusiveMaximum` are booleans that
    modify `minimum` and `maximum`. They are not standalone numeric keywords.
    All 659 occurrences are booleans, which confirms it.
  * Every one of the 675 `$ref` values is local, pointing into `#/definitions/`.
    There are 201 distinct targets and no network reference.
  * `items` is always a single schema. The tuple form never appears, so an
    array's items all share one schema.
  * `additionalProperties` is always `false` in this schema. The schema form is
    implemented anyway, because a later version may use it.
  * `multipleOf` is only ever 0.01 or 0.0001. Binary floats cannot check that
    honestly, so the check goes through `decimal`.
  * `type` is never a list here, but the list form is handled.

`audit_keywords()` re-derives the keyword set from whatever schema you hand it
and reports anything this validator does not implement. The CLI prints that on
every run, so a clean pass can never quietly mean "nothing was checked" against
a future schema.

This checks shape, not arithmetic. A file can satisfy every line of the schema
and still be a wrong return. The official offline utility is the authority.
"""

import argparse
import json
import re
import sys
from decimal import Decimal, InvalidOperation
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCHEMA = ROOT / "schema" / "ITR-2_2026_Main_V1.1.json"

MAX_DEPTH = 200

#: Keywords this validator enforces.
IMPLEMENTED = {
    "$ref", "additionalProperties", "allOf", "enum", "exclusiveMaximum",
    "exclusiveMinimum", "items", "maxItems", "maxLength", "maximum",
    "minItems", "minLength", "minimum", "multipleOf", "pattern", "properties",
    "required", "type",
}

#: Keywords that carry no constraint, so not implementing them is harmless.
ANNOTATION_ONLY = {
    "$schema", "$comment", "comment", "id", "$id", "title", "description",
    "default", "definitions", "examples", "format", "readOnly", "writeOnly",
    "deprecated",
}

#: Keys under these are names chosen by the schema author, not keywords.
_NAME_CONTAINERS = {"properties", "definitions", "patternProperties",
                    "dependencies"}


class SchemaError(Exception):
    """The schema itself could not be used. Distinct from a document error."""


# --------------------------------------------------------------- keyword audit

def _walk_schema_nodes(node, is_schema=True):
    """Yield each dict that sits in a schema position."""
    if isinstance(node, dict):
        if is_schema:
            yield node
        for key, value in node.items():
            if key in _NAME_CONTAINERS:
                if isinstance(value, dict):
                    for sub in value.values():
                        yield from _walk_schema_nodes(sub, True)
            elif key in ("items", "additionalProperties", "additionalItems",
                         "not", "contains", "propertyNames"):
                if isinstance(value, list):          # tuple form
                    for sub in value:
                        yield from _walk_schema_nodes(sub, True)
                elif isinstance(value, dict):
                    yield from _walk_schema_nodes(value, True)
            elif key in ("allOf", "anyOf", "oneOf"):
                if isinstance(value, list):
                    for sub in value:
                        yield from _walk_schema_nodes(sub, True)
            elif key in ("enum", "required", "type", "$ref", "pattern",
                         "const", "format"):
                continue                              # values, never schemas
            elif isinstance(value, (dict, list)):
                yield from _walk_schema_nodes(value, False)
    elif isinstance(node, list) and not is_schema:
        for sub in node:
            yield from _walk_schema_nodes(sub, False)


def collect_keywords(schema):
    """Every keyword appearing anywhere in a schema position."""
    found = set()
    for node in _walk_schema_nodes(schema):
        found.update(node.keys())
    return found


def audit_keywords(schema):
    """
    Keywords present in `schema` that this validator does not enforce.

    An empty result means full coverage: every constraining keyword in the
    schema is actually checked. A non-empty result means a clean validation
    pass is not proof of anything, and the caller must say so.
    """
    return sorted(collect_keywords(schema) - IMPLEMENTED - ANNOTATION_ONLY)


# ------------------------------------------------------------------ path names

def _child(path, key):
    return f"{path}.{key}" if path else str(key)


def _item(path, index):
    return f"{path}[{index}]"


# ------------------------------------------------------------------ type check

def _is_type(value, name):
    if name == "object":
        return isinstance(value, dict)
    if name == "array":
        return isinstance(value, list)
    if name == "string":
        return isinstance(value, str)
    if name == "boolean":
        return isinstance(value, bool)
    if name == "null":
        return value is None
    if name == "integer":
        # bool is a subclass of int in Python. JSON says they are different.
        if isinstance(value, bool):
            return False
        if isinstance(value, int):
            return True
        # 3.0 is a valid integer under Draft-04.
        return isinstance(value, float) and value.is_integer()
    if name == "number":
        if isinstance(value, bool):
            return False
        return isinstance(value, (int, float))
    return True          # unknown type name: nothing to enforce


def _is_number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _multiple_of(value, divisor):
    """0.1 % 0.01 is 0.009999... in binary float. Decimal tells the truth."""
    try:
        dividend = Decimal(str(value))
        step = Decimal(str(divisor))
    except (InvalidOperation, ValueError):
        return True
    if step == 0:
        return True
    return dividend % step == 0


def _equal(a, b):
    """JSON equality, with bool kept distinct from 0 and 1."""
    if isinstance(a, bool) != isinstance(b, bool):
        return False
    if _is_number(a) and _is_number(b):
        return a == b
    if type(a) is not type(b):
        return False
    return a == b


# ------------------------------------------------------------------- validator

class Draft4Validator:
    """Draft-04 validator over the measured keyword subset. Collects all errors."""

    def __init__(self, schema, max_depth=MAX_DEPTH):
        if not isinstance(schema, dict):
            raise SchemaError("schema root must be an object")
        self.schema = schema
        self.max_depth = max_depth

    # -- $ref

    def _resolve(self, ref):
        if not isinstance(ref, str) or not ref.startswith("#"):
            raise SchemaError(
                f"non-local $ref {ref!r}. This validator resolves only "
                f"'#/definitions/...' pointers and never fetches anything.")
        node = self.schema
        for token in ref.lstrip("#").strip("/").split("/"):
            if not token:
                continue
            token = token.replace("~1", "/").replace("~0", "~")
            if not isinstance(node, dict) or token not in node:
                raise SchemaError(f"$ref {ref!r} does not resolve")
            node = node[token]
        if not isinstance(node, dict):
            raise SchemaError(f"$ref {ref!r} does not point at a schema")
        return node

    # -- entry point

    def iter_errors(self, instance):
        """Return every (json_path, message) found. Never raises on a defect."""
        errors = []
        self._validate(instance, self.schema, "", 0, errors)
        return errors

    def is_valid(self, instance):
        return not self.iter_errors(instance)

    # -- the walk

    def _validate(self, value, schema, path, depth, errors):
        if depth > self.max_depth:
            errors.append((path or "<root>",
                           f"validation depth {self.max_depth} exceeded, "
                           f"which usually means a cyclic $ref"))
            return
        if not isinstance(schema, dict):
            return

        # Draft-04: $ref replaces the schema it sits in. Siblings are ignored.
        if "$ref" in schema:
            try:
                target = self._resolve(schema["$ref"])
            except SchemaError as exc:
                errors.append((path or "<root>", str(exc)))
                return
            self._validate(value, target, path, depth + 1, errors)
            return

        self._check_type(value, schema, path, errors)
        self._check_enum(value, schema, path, errors)
        self._check_number(value, schema, path, errors)
        self._check_string(value, schema, path, errors)
        self._check_array(value, schema, path, depth, errors)
        self._check_object(value, schema, path, depth, errors)

        for index, sub in enumerate(schema.get("allOf", []) or []):
            self._validate(value, sub, path, depth + 1, errors)

    # -- keyword groups

    def _check_type(self, value, schema, path, errors):
        if "type" not in schema:
            return
        expected = schema["type"]
        names = expected if isinstance(expected, list) else [expected]
        if not any(_is_type(value, n) for n in names):
            errors.append((path or "<root>",
                           f"{json.dumps(value)[:60]} is not of type "
                           f"{' or '.join(str(n) for n in names)}"))

    def _check_enum(self, value, schema, path, errors):
        if "enum" not in schema:
            return
        members = schema["enum"]
        if not any(_equal(value, m) for m in members):
            shown = ", ".join(json.dumps(m) for m in members[:8])
            more = "" if len(members) <= 8 else f", and {len(members) - 8} more"
            errors.append((path or "<root>",
                           f"{json.dumps(value)[:60]} is not one of "
                           f"[{shown}{more}]"))

    def _check_number(self, value, schema, path, errors):
        if not _is_number(value):
            return
        where = path or "<root>"

        if "minimum" in schema:
            limit = schema["minimum"]
            # Draft-04: the exclusive flag modifies the bound beside it.
            if schema.get("exclusiveMinimum") is True:
                if not value > limit:
                    errors.append((where, f"{value} is not greater than {limit}"))
            elif not value >= limit:
                # Wording matches the offline utility, which reports
                # "0 is not greater or equal to 100000".
                errors.append((where,
                               f"{value} is not greater or equal to {limit}"))

        if "maximum" in schema:
            limit = schema["maximum"]
            if schema.get("exclusiveMaximum") is True:
                if not value < limit:
                    errors.append((where, f"{value} is not less than {limit}"))
            elif not value <= limit:
                errors.append((where, f"{value} is not less or equal to {limit}"))

        if "multipleOf" in schema:
            step = schema["multipleOf"]
            if not _multiple_of(value, step):
                errors.append((where, f"{value} is not a multiple of {step}"))

    def _check_string(self, value, schema, path, errors):
        if not isinstance(value, str):
            return
        where = path or "<root>"
        if "minLength" in schema and len(value) < schema["minLength"]:
            errors.append((where, f"{json.dumps(value)[:40]} is shorter than "
                                  f"{schema['minLength']} characters"))
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            errors.append((where, f"{json.dumps(value)[:40]} is longer than "
                                  f"{schema['maxLength']} characters"))
        if "pattern" in schema:
            pattern = schema["pattern"]
            try:
                # JSON Schema patterns are unanchored: search, not fullmatch.
                if re.search(pattern, value) is None:
                    errors.append((where, f"{json.dumps(value)[:40]} does not "
                                          f"match {pattern!r}"))
            except re.error as exc:
                errors.append((where, f"schema pattern {pattern!r} is not a "
                                      f"usable regex: {exc}"))

    def _check_array(self, value, schema, path, depth, errors):
        if not isinstance(value, list):
            return
        where = path or "<root>"
        if "minItems" in schema and len(value) < schema["minItems"]:
            errors.append((where, f"has {len(value)} items, fewer than the "
                                  f"required {schema['minItems']}"))
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            errors.append((where, f"has {len(value)} items, more than the "
                                  f"permitted {schema['maxItems']}"))
        if "items" in schema:
            items = schema["items"]
            if isinstance(items, list):          # tuple form, unused here
                for index, sub in enumerate(items):
                    if index < len(value):
                        self._validate(value[index], sub,
                                       _item(path, index), depth + 1, errors)
            elif isinstance(items, dict):
                for index, member in enumerate(value):
                    self._validate(member, items,
                                   _item(path, index), depth + 1, errors)

    def _check_object(self, value, schema, path, depth, errors):
        if not isinstance(value, dict):
            return
        where = path or "<root>"

        for name in schema.get("required", []) or []:
            if name not in value:
                errors.append((_child(path, name),
                               f"{name!r} is a required property and is missing"))

        properties = schema.get("properties", {}) or {}
        for name, sub in properties.items():
            if name in value:
                self._validate(value[name], sub,
                               _child(path, name), depth + 1, errors)

        if "additionalProperties" in schema:
            extra = schema["additionalProperties"]
            unknown = [k for k in value if k not in properties]
            if extra is False:
                for name in unknown:
                    errors.append((_child(path, name),
                                   f"{name!r} is not one of the permitted "
                                   f"properties here"))
            elif isinstance(extra, dict):
                for name in unknown:
                    self._validate(value[name], extra,
                                   _child(path, name), depth + 1, errors)


# ------------------------------------------------------------------- convenience

def validate(document, schema):
    """Return a list of (json_path, message). Empty means structurally valid."""
    return Draft4Validator(schema).iter_errors(document)


# -------------------------------------------------------------------------- CLI

def _print_audit(unimplemented, schema_name):
    if not unimplemented:
        print(f"keyword audit: full coverage. Every constraining keyword in "
              f"{schema_name} is enforced.")
        return True
    print(f"keyword audit: INCOMPLETE COVERAGE of {schema_name}")
    print(f"  {len(unimplemented)} keyword(s) present in the schema are NOT "
          f"checked by this validator:")
    for keyword in unimplemented:
        print(f"    {keyword}")
    print("  A pass below does not cover those. Install jsonschema, or extend")
    print("  IMPLEMENTED in this file, before relying on the result.")
    return False


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Validate a document against the ITR-2 Draft-04 schema "
                    "using only the standard library.")
    parser.add_argument("document", nargs="?",
                        help="the JSON file to validate")
    parser.add_argument("--schema", default=str(DEFAULT_SCHEMA),
                        help="schema path (default: schema/ITR-2_2026_Main_V1.1.json)")
    parser.add_argument("--audit-only", action="store_true",
                        help="report keyword coverage and exit, without validating")
    parser.add_argument("--limit", type=int, default=25,
                        help="maximum errors to print (default 25)")
    args = parser.parse_args(argv)

    schema_path = Path(args.schema)
    try:
        schema = json.loads(schema_path.read_text())
    except FileNotFoundError:
        print(f"could not run: no schema at {schema_path}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"could not run: schema is not valid JSON: {exc}", file=sys.stderr)
        return 2

    full_coverage = _print_audit(audit_keywords(schema), schema_path.name)

    if args.audit_only:
        return 0 if full_coverage else 1

    if not args.document:
        print("could not run: give a document to validate, or --audit-only",
              file=sys.stderr)
        return 2

    try:
        document = json.loads(Path(args.document).read_text())
    except FileNotFoundError:
        print(f"could not run: no such file {args.document}", file=sys.stderr)
        return 2
    except json.JSONDecodeError as exc:
        print(f"could not run: {args.document} is not valid JSON: {exc}",
              file=sys.stderr)
        return 2

    try:
        errors = validate(document, schema)
    except SchemaError as exc:
        print(f"could not run: {exc}", file=sys.stderr)
        return 2

    if errors:
        print(f"\nINVALID: {len(errors)} error(s) in {args.document}")
        for path, message in errors[:args.limit]:
            print(f"  at {path}")
            print(f"     {message}")
        if len(errors) > args.limit:
            print(f"  ... and {len(errors) - args.limit} more "
                  f"(raise --limit to see them)")
        return 1

    print(f"\nVALID: {args.document} matches {schema_path.name}")
    print("This checks shape, not arithmetic. Every field is the right type,")
    print("in range and in the right place. Whether the figures are correct is")
    print("a different question, and the official offline utility is the")
    print("authority on it. Import the file there before you file.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
