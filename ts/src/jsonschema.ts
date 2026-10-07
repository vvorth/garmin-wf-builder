// The project's JSON Schema validator: Draft 2020-12, the keywords this
// project's schema uses, no dependency. `validate.ts` turns its errors
// into diagnostics using their whole shape (the keyword, the failing
// subschema, each `oneOf` branch's errors as `context`, the paths, even
// the message's length to break a tie). That shape is python-jsonschema
// 4.26's, which a flat-error validator such as Ajv does not give, so the
// diagnostics stay as they are.
//
// Follows jsonschema's `validators.py` (`iter_errors`, `descend`,
// `_validate_reference`), `_keywords.py` and `_utils.py` (`equal`, `uniq`,
// `find_additional_properties`, `extras_msg`). Keywords run in each
// schema's own key order; `$ref` and `if` add nothing to the schema path.
// Instances are YAML data: a mapping is a `Map`, and an integral float a
// `PyFloat`.
import { type Data, type DataKey, PyFloat, Timestamp } from "./edit/yaml.ts";
import { quoted } from "./py.ts";

export type Schema = boolean | { [key: string]: unknown };
type Step = string | number;

export class ValidationError {
  message: string;
  validator: string | null = null;
  validatorValue: unknown = undefined;
  instance: unknown = undefined;
  schema: Schema | undefined = undefined;
  /** The path within the instance, relative to the parent error's. */
  path: Step[] = [];
  schemaPath: Step[] = [];
  context: ValidationError[];
  parent: ValidationError | null = null;
  private set = false;

  constructor(message: string, context: ValidationError[] = []) {
    this.message = message;
    this.context = context;
    for (const sub of context) sub.parent = this;
  }

  /** jsonschema's `_set`: the details, unless the keyword already set them. */
  fill(validator: string | null, validatorValue: unknown, instance: unknown, schema: Schema): void {
    if (this.set) return;
    this.set = true;
    this.validator = validator;
    this.validatorValue = validatorValue;
    this.instance = instance;
    this.schema = schema;
  }

  get absolutePath(): Step[] {
    return this.parent === null ? [...this.path] : [...this.parent.absolutePath, ...this.path];
  }

  get absoluteSchemaPath(): Step[] {
    return this.parent === null ? [...this.schemaPath] : [...this.parent.absoluteSchemaPath, ...this.schemaPath];
  }
}

// -- types and equality: jsonschema's `_types.py` and `_utils.py` ---------------

function isType(instance: unknown, type: string): boolean {
  switch (type) {
    case "object": return instance instanceof Map;
    case "array": return Array.isArray(instance);
    case "string": return typeof instance === "string";
    case "boolean": return typeof instance === "boolean";
    case "null": return instance === null;
    case "number": return typeof instance === "number" || instance instanceof PyFloat;
    // Draft 6 on: an int, or a float that is integral.
    case "integer": return instance instanceof PyFloat || (typeof instance === "number" && Number.isInteger(instance));
    default: throw new Error(`unknown type ${type}`);
  }
}

/** A plain JSON value from the schema, compared as Python's `==` would after jsonschema's `unbool`. */
function equal(one: unknown, two: unknown): boolean {
  if (one === two) return true;
  if (typeof one === "string" || typeof two === "string") return one === two;
  if (Array.isArray(one) && Array.isArray(two)) return one.length === two.length && one.every((v, i) => equal(v, two[i]));
  const asMap = (x: unknown): Map<unknown, unknown> | null =>
    x instanceof Map ? x : x !== null && typeof x === "object" && !(x instanceof PyFloat) && !(x instanceof Timestamp) && !Array.isArray(x)
      ? new Map(Object.entries(x)) : null;
  const m1 = asMap(one), m2 = asMap(two);
  if (m1 !== null && m2 !== null) {
    if (m1.size !== m2.size) return false;
    for (const [k, v] of m1) if (!m2.has(k) || !equal(v, m2.get(k))) return false;
    return true;
  }
  if (typeof one === "boolean" || typeof two === "boolean") return one === two;
  const n1 = one instanceof PyFloat ? one.value : one, n2 = two instanceof PyFloat ? two.value : two;
  return n1 === n2;
}

function uniq(container: unknown[]): boolean {
  for (let i = 0; i < container.length; i++) {
    for (let j = i + 1; j < container.length; j++) if (equal(container[i], container[j])) return false;
  }
  return true;
}

/** A Python `re` pattern as a JavaScript one: `\d` is any Unicode digit, and a final `$` also matches before a final newline. */
function pythonRegex(pattern: string): RegExp {
  let source = pattern.replace(/\\d/g, "\\p{Nd}");
  if (source.endsWith("$") && !source.endsWith("\\$")) source = `${source.slice(0, -1)}(?=\\n?$)`;
  return new RegExp(source, "u");
}

const regexes = new Map<string, RegExp>();
function search(pattern: string, text: string): boolean {
  let re = regexes.get(pattern);
  if (re === undefined) {
    re = pythonRegex(pattern);
    regexes.set(pattern, re);
  }
  return re.test(text);
}

const length = (text: string): number => Array.from(text).length;

function compareKeys(a: unknown, b: unknown): number {
  const x = String(a), y = String(b);
  return x < y ? -1 : x > y ? 1 : 0;
}

// -- the validator --------------------------------------------------------------

type Keyword = (v: Validator, value: unknown, instance: unknown, schema: Record<string, unknown>) => Iterable<ValidationError>;

const KEYWORDS: Record<string, Keyword> = {
  *$ref(v, ref, instance) {
    yield* v.descend(instance, v.resolve(ref as string));
  },
  *type(_v, types, instance) {
    const list = typeof types === "string" ? [types] : (types as string[]);
    if (!list.some((t) => isType(instance, t))) {
      yield new ValidationError(`${quoted(instance)} is not of type ${list.map((t) => quoted(t)).join(", ")}`);
    }
  },
  *properties(v, properties, instance) {
    if (!(instance instanceof Map)) return;
    for (const [property, subschema] of Object.entries(properties as Record<string, Schema>)) {
      if (instance.has(property)) yield* v.descend(instance.get(property), subschema, property, property);
    }
  },
  *additionalProperties(v, aP, instance, schema) {
    if (!(instance instanceof Map)) return;
    const properties = (schema["properties"] ?? {}) as Record<string, unknown>;
    const patterns = Object.keys((schema["patternProperties"] ?? {}) as Record<string, unknown>).join("|");
    const extras = [...instance.keys()].filter((p) => !(String(p) in properties) && !(patterns && search(patterns, String(p))));
    if (aP !== null && typeof aP === "object") {
      for (const extra of extras) yield* v.descend(instance.get(extra), aP as Schema, extra as Step);
    } else if (!aP && extras.length > 0) {
      if ("patternProperties" in schema) {
        const verb = extras.length === 1 ? "does" : "do";
        const joined = [...extras].sort(compareKeys).map(quoted).join(", ");
        const pats = Object.keys(schema["patternProperties"] as object).sort().map(quoted).join(", ");
        yield new ValidationError(`${joined} ${verb} not match any of the regexes: ${pats}`);
      } else {
        const sorted = [...extras].sort(compareKeys);
        const verb = sorted.length === 1 ? "was" : "were";
        yield new ValidationError(`Additional properties are not allowed (${sorted.map(quoted).join(", ")} ${verb} unexpected)`);
      }
    }
  },
  *required(_v, required, instance) {
    if (!(instance instanceof Map)) return;
    for (const property of required as string[]) {
      if (!instance.has(property)) yield new ValidationError(`${quoted(property)} is a required property`);
    }
  },
  *enum(_v, enums, instance) {
    if ((enums as unknown[]).every((each) => !equal(each, instance))) {
      yield new ValidationError(`${quoted(instance)} is not one of ${quoted(enums)}`);
    }
  },
  *const(_v, value, instance) {
    if (!equal(instance, value)) yield new ValidationError(`${quoted(value)} was expected`);
  },
  *allOf(v, allOf, instance) {
    let index = 0;
    for (const subschema of allOf as Schema[]) yield* v.descend(instance, subschema, undefined, index++);
  },
  *anyOf(v, anyOf, instance) {
    const all: ValidationError[] = [];
    let index = 0;
    for (const subschema of anyOf as Schema[]) {
      const errs = [...v.descend(instance, subschema, undefined, index++)];
      if (errs.length === 0) return;
      all.push(...errs);
    }
    yield new ValidationError(`${quoted(instance)} is not valid under any of the given schemas`, all);
  },
  *oneOf(v, oneOf, instance) {
    const subschemas = oneOf as Schema[];
    const all: ValidationError[] = [];
    let firstValid: Schema | undefined;
    let index = 0;
    for (; index < subschemas.length; index++) {
      const errs = [...v.descend(instance, subschemas[index]!, undefined, index)];
      if (errs.length === 0) { firstValid = subschemas[index]; index++; break; }
      all.push(...errs);
    }
    if (firstValid === undefined) {
      yield new ValidationError(`${quoted(instance)} is not valid under any of the given schemas`, all);
      return;
    }
    const moreValid = subschemas.slice(index).filter((each) => v.isValid(instance, each));
    if (moreValid.length > 0) {
      moreValid.push(firstValid);
      yield new ValidationError(`${quoted(instance)} is valid under each of ${moreValid.map(quoted).join(", ")}`);
    }
  },
  *not(v, notSchema, instance) {
    if (v.isValid(instance, notSchema as Schema)) {
      yield new ValidationError(`${quoted(instance)} should not be valid under ${quoted(notSchema)}`);
    }
  },
  *if(v, ifSchema, instance, schema) {
    if (v.isValid(instance, ifSchema as Schema)) {
      if ("then" in schema) yield* v.descend(instance, schema["then"] as Schema, undefined, "then");
    } else if ("else" in schema) {
      yield* v.descend(instance, schema["else"] as Schema, undefined, "else");
    }
  },
  *items(v, items, instance, schema) {
    if (!Array.isArray(instance)) return;
    const prefix = ((schema["prefixItems"] ?? []) as unknown[]).length;
    const extra = instance.length - prefix;
    if (extra <= 0) return;
    if (items === false) {
      const rest = extra !== 1 ? instance.slice(prefix) : instance[prefix];
      yield new ValidationError(`Expected at most ${prefix} ${prefix !== 1 ? "items" : "item"} but found ${extra} extra: ${quoted(rest)}`);
    } else {
      for (let index = prefix; index < instance.length; index++) yield* v.descend(instance[index], items as Schema, index);
    }
  },
  *minItems(_v, mI, instance) {
    if (Array.isArray(instance) && instance.length < (mI as number)) {
      yield new ValidationError(`${quoted(instance)} ${mI === 1 ? "should be non-empty" : "is too short"}`);
    }
  },
  *maxItems(_v, mI, instance) {
    if (Array.isArray(instance) && instance.length > (mI as number)) {
      yield new ValidationError(`${quoted(instance)} ${mI === 0 ? "is expected to be empty" : "is too long"}`);
    }
  },
  *uniqueItems(_v, uI, instance) {
    if (uI && Array.isArray(instance) && !uniq(instance)) yield new ValidationError(`${quoted(instance)} has non-unique elements`);
  },
  *pattern(_v, pattern, instance) {
    if (typeof instance === "string" && !search(pattern as string, instance)) {
      yield new ValidationError(`${quoted(instance)} does not match ${quoted(pattern)}`);
    }
  },
  *minLength(_v, mL, instance) {
    if (typeof instance === "string" && length(instance) < (mL as number)) {
      yield new ValidationError(`${quoted(instance)} ${mL === 1 ? "should be non-empty" : "is too short"}`);
    }
  },
  *maxLength(_v, mL, instance) {
    if (typeof instance === "string" && length(instance) > (mL as number)) {
      yield new ValidationError(`${quoted(instance)} ${mL === 0 ? "is expected to be empty" : "is too long"}`);
    }
  },
  *propertyNames(v, propertyNames, instance) {
    if (!(instance instanceof Map)) return;
    for (const property of instance.keys()) yield* v.descend(property, propertyNames as Schema);
  },
  *minProperties(_v, mP, instance) {
    if (instance instanceof Map && instance.size < (mP as number)) {
      yield new ValidationError(`${quoted(instance)} ${mP === 1 ? "should be non-empty" : "does not have enough properties"}`);
    }
  },
  *minimum(_v, minimum, instance) {
    if (isType(instance, "number") && numeric(instance) < (minimum as number)) {
      yield new ValidationError(`${quoted(instance)} is less than the minimum of ${quoted(minimum)}`);
    }
  },
  *maximum(_v, maximum, instance) {
    if (isType(instance, "number") && numeric(instance) > (maximum as number)) {
      yield new ValidationError(`${quoted(instance)} is greater than the maximum of ${quoted(maximum)}`);
    }
  },
  *exclusiveMinimum(_v, minimum, instance) {
    if (isType(instance, "number") && numeric(instance) <= (minimum as number)) {
      yield new ValidationError(`${quoted(instance)} is less than or equal to the minimum of ${quoted(minimum)}`);
    }
  },
  *dependentRequired(_v, dependentRequired, instance) {
    if (!(instance instanceof Map)) return;
    for (const [property, dependency] of Object.entries(dependentRequired as Record<string, string[]>)) {
      if (!instance.has(property)) continue;
      for (const each of dependency) {
        if (!instance.has(each)) yield new ValidationError(`${quoted(each)} is a dependency of ${quoted(property)}`);
      }
    }
  },
};

function numeric(instance: unknown): number {
  return instance instanceof PyFloat ? instance.value : (instance as number);
}

export class Validator {
  private readonly root: Record<string, unknown>;

  constructor(root: Record<string, unknown>) {
    this.root = root;
  }

  /** A local `#/...` reference. */
  resolve(ref: string): Schema {
    if (!ref.startsWith("#")) throw new Error(`unresolvable reference ${ref}`);
    let node: unknown = this.root;
    for (const raw of ref.slice(1).split("/").filter(Boolean)) {
      const part = raw.replace(/~1/g, "/").replace(/~0/g, "~");
      node = (node as Record<string, unknown>)[part];
      if (node === undefined) throw new Error(`unresolvable reference ${ref}`);
    }
    return node as Schema;
  }

  /** Every error, in jsonschema's order. */
  iterErrors(instance: unknown): ValidationError[] {
    return [...this.descend(instance, this.root)];
  }

  isValid(instance: unknown, schema: Schema): boolean {
    return this.descend(instance, schema).next().done === true;
  }

  *descend(instance: unknown, schema: Schema, path?: Step, schemaPath?: Step): Generator<ValidationError> {
    if (schema === true) return;
    if (schema === false) {
      const error = new ValidationError(`False schema does not allow ${quoted(instance)}`);
      error.fill(null, null, instance, schema);
      if (path !== undefined) error.path.unshift(path);
      if (schemaPath !== undefined) error.schemaPath.unshift(schemaPath);
      yield error;
      return;
    }
    for (const [k, value] of Object.entries(schema)) {
      const keyword = KEYWORDS[k];
      if (keyword === undefined) continue;
      for (const error of keyword(this, value, instance, schema)) {
        error.fill(k, value, instance, schema);
        if (k !== "if" && k !== "$ref") error.schemaPath.unshift(k);
        if (path !== undefined) error.path.unshift(path);
        if (schemaPath !== undefined) error.schemaPath.unshift(schemaPath);
        yield error;
      }
    }
  }
}

export type { Data, DataKey };
