import ast
import builtins
import json
import sys


MAX_SOURCE_BYTES = 64 * 1024
MAX_AST_NODES = 4096
STEP_BUDGET = 100000
_CODE_FILENAME = "<native-dag-validator>"
_MAX_ERRORS = 16
_MAX_ERROR_LENGTH = 160

_ALLOWED_BUILTINS = frozenset(
    {
        "len",
        "list",
        "dict",
        "set",
        "tuple",
        "sorted",
        "isinstance",
        "all",
        "any",
        "enumerate",
        "range",
        "str",
        "int",
        "bool",
        "type",
        "min",
        "max",
    }
)
_ALLOWED_CALL_NAMES = _ALLOWED_BUILTINS | {"ValueError"}
_ALLOWED_METHODS = frozenset(
    {"append", "add", "get", "pop", "remove", "discard", "copy"}
)
_DANGEROUS_NAMES = frozenset(
    {
        "__builtins__",
        "__import__",
        "eval",
        "exec",
        "open",
        "getattr",
        "setattr",
        "delattr",
        "globals",
        "locals",
        "vars",
        "dir",
        "compile",
        "input",
        "help",
        "breakpoint",
        "exit",
        "quit",
        "os",
        "sys",
        "subprocess",
        "socket",
        "pathlib",
        "shutil",
        "importlib",
        "builtins",
        "ctypes",
        "marshal",
        "pickle",
        "code",
        "inspect",
        "traceback",
    }
)

_ALLOWED_BUILTINS_NAMESPACE = {
    name: getattr(builtins, name)
    for name in _ALLOWED_BUILTINS
}
if "ValueError" not in _ALLOWED_BUILTINS_NAMESPACE:
    _ALLOWED_BUILTINS_NAMESPACE["ValueError"] = ValueError


class _BudgetExceeded(Exception):
    pass


class _PolicyVisitor(ast.NodeVisitor):
    _allowed_nodes = {
        ast.Add,
        ast.And,
        ast.arg,
        ast.arguments,
        ast.Assign,
        ast.AugAssign,
        ast.BinOp,
        ast.BitAnd,
        ast.BitOr,
        ast.BitXor,
        ast.BoolOp,
        ast.Break,
        ast.Call,
        ast.Compare,
        ast.comprehension,
        ast.Constant,
        ast.Continue,
        ast.Dict,
        ast.DictComp,
        ast.Div,
        ast.Eq,
        ast.Expr,
        ast.For,
        ast.FloorDiv,
        ast.GeneratorExp,
        ast.Gt,
        ast.GtE,
        ast.If,
        ast.IfExp,
        ast.In,
        ast.Index,
        ast.Is,
        ast.IsNot,
        ast.JoinedStr,
        ast.keyword,
        ast.List,
        ast.ListComp,
        ast.Load,
        ast.Lt,
        ast.LtE,
        ast.Mod,
        ast.Mult,
        ast.Name,
        ast.Not,
        ast.NotEq,
        ast.NotIn,
        ast.Or,
        ast.Pass,
        ast.Pow,
        ast.Raise,
        ast.Return,
        ast.Set,
        ast.SetComp,
        ast.Slice,
        ast.Store,
        ast.Sub,
        ast.Subscript,
        ast.Tuple,
        ast.UAdd,
        ast.UnaryOp,
        ast.USub,
        ast.While,
    }

    def __init__(self):
        self.errors = []

    def reject(self, message):
        if len(self.errors) < _MAX_ERRORS:
            self.errors.append(message)

    def generic_visit(self, node):
        if type(node) not in self._allowed_nodes:
            self.reject("unsupported syntax: " + type(node).__name__)
            return
        super().generic_visit(node)

    def visit_FunctionDef(self, node):
        self.reject("nested or unexpected function definition")

    def visit_AsyncFunctionDef(self, node):
        self.reject("async function definitions are not allowed")

    def visit_Name(self, node):
        name = node.id
        if name in _DANGEROUS_NAMES:
            self.reject("dangerous name is not allowed")
        elif name.startswith("__") and name.endswith("__"):
            self.reject("dunder name is not allowed")
        elif isinstance(node.ctx, ast.Store) and name in _ALLOWED_CALL_NAMES:
            self.reject("protected callable name is not assignable")

    def visit_Attribute(self, node):
        if node.attr not in _ALLOWED_METHODS:
            self.reject("attribute is not allowlisted")
            return
        self.visit(node.value)

    def visit_Call(self, node):
        if isinstance(node.func, ast.Name):
            if node.func.id not in _ALLOWED_CALL_NAMES:
                self.reject("call target is not allowlisted")
        elif isinstance(node.func, ast.Attribute):
            if node.func.attr not in _ALLOWED_METHODS:
                self.reject("method is not allowlisted")
        else:
            self.reject("call target is not allowlisted")
        self.visit(node.func)
        for argument in node.args:
            self.visit(argument)
        for keyword in node.keywords:
            if keyword.arg is None or (
                keyword.arg.startswith("__") and keyword.arg.endswith("__")
            ):
                self.reject("keyword form is not allowed")
            self.visit(keyword.value)

    def visit_Constant(self, node):
        if not isinstance(node.value, (str, int, float, complex, bool, type(None))):
            self.reject("constant type is not allowed")

    def visit_JoinedStr(self, node):
        for value in node.values:
            self.visit(value)

    def visit_FormattedValue(self, node):
        self.visit(node.value)
        if node.format_spec is not None:
            self.visit(node.format_spec)

    def visit_Raise(self, node):
        if node.exc is None:
            self.reject("bare raise is not allowed")
            return
        self.visit(node.exc)
        if node.cause is not None:
            self.visit(node.cause)


def _bounded_error(message):
    text = str(message).replace("\r", " ").replace("\n", " ")
    if len(text) > _MAX_ERROR_LENGTH:
        text = text[:_MAX_ERROR_LENGTH]
    return text


def _report(passed, tests=None, errors=None):
    bounded_errors = [_bounded_error(error) for error in (errors or [])][:_MAX_ERRORS]
    return {
        "schema_version": 1,
        "passed": bool(passed),
        "tests": list(tests or []),
        "errors": bounded_errors,
    }


def _policy_errors(source_text):
    if not isinstance(source_text, str):
        return ["source must be text"]
    if len(source_text.encode("utf-8")) > MAX_SOURCE_BYTES:
        return ["source exceeds 64 KiB"]
    try:
        tree = ast.parse(source_text, filename=_CODE_FILENAME, mode="exec")
    except (SyntaxError, ValueError, TypeError, MemoryError):
        return ["source could not be parsed"]
    if sum(1 for _ in ast.walk(tree)) > MAX_AST_NODES:
        return ["source exceeds AST node limit"]
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.FunctionDef):
        return ["source must contain exactly one top-level function"]
    function = tree.body[0]
    if function.name != "topological_order":
        return ["function must be named topological_order"]
    if function.decorator_list or function.returns is not None:
        return ["decorators and return annotations are not allowed"]
    if getattr(function, "type_comment", None) is not None:
        return ["type comments are not allowed"]
    arguments = function.args
    positional = list(getattr(arguments, "posonlyargs", [])) + list(arguments.args)
    if (
        [argument.arg for argument in positional] != ["nodes", "edges"]
        or arguments.defaults
        or arguments.kw_defaults
        or arguments.vararg is not None
        or arguments.kwarg is not None
        or arguments.kwonlyargs
    ):
        return ["function must have exactly nodes and edges arguments"]
    if not function.body:
        return ["function body must not be empty"]
    visitor = _PolicyVisitor()
    for statement in function.body:
        visitor.visit(statement)
    return visitor.errors


def _execution_tracer(counter):
    def trace(frame, event, argument):
        if frame.f_code.co_filename != _CODE_FILENAME:
            return trace
        if event == "call":
            frame.f_trace_opcodes = True
        elif event in {"line", "opcode"}:
            counter[0] += 1
            if counter[0] > STEP_BUDGET:
                raise _BudgetExceeded()
        return trace

    return trace


def _invoke(function, nodes, edges):
    counter = [0]
    previous_trace = sys.gettrace()
    sys.settrace(_execution_tracer(counter))
    try:
        value = function(nodes, edges)
        return "ok", value
    except _BudgetExceeded:
        return "budget", None
    except ValueError:
        return "value_error", None
    except BaseException as error:
        return type(error).__name__, None
    finally:
        sys.settrace(previous_trace)


def _test_cases():
    return [
        (
            "deterministic_ordering",
            ["b", "a", "c"],
            [("b", "c"), ("a", "c")],
            ["a", "b", "c"],
            False,
        ),
        (
            "newly_ready_nodes_are_sorted",
            ["a", "z", "b"],
            [("a", "b")],
            ["a", "b", "z"],
            False,
        ),
        (
            "duplicate_edges_deduplicated",
            ["a", "b"],
            [("a", "b"), ("a", "b")],
            ["a", "b"],
            False,
        ),
        ("empty_graph", [], [], [], False),
        ("duplicate_nodes_rejected", ["a", "a"], [], None, True),
        ("boolean_node_rejected", [True], [], None, True),
        ("nonstring_node_rejected", ["a", 7], [], None, True),
        ("empty_string_node_rejected", [""], [], None, True),
        ("invalid_endpoint_rejected", ["a"], [("a", "b")], None, True),
        ("invalid_edge_shape_rejected", ["a"], [("a",)], None, True),
        ("self_loop_rejected", ["a"], [("a", "a")], None, True),
        (
            "cycle_rejected",
            ["a", "b"],
            [("a", "b"), ("b", "a")],
            None,
            True,
        ),
    ]


def _run_tests(function):
    results = []
    errors = []
    halted = False
    for name, nodes, edges, expected, expects_error in _test_cases():
        if halted:
            results.append({"name": name, "passed": False})
            continue
        status, value = _invoke(function, list(nodes), list(edges))
        if status == "budget":
            errors.append("execution step budget exceeded")
            results.append({"name": name, "passed": False})
            halted = True
            continue
        if status == "ok":
            passed = not expects_error and type(value) is list and value == expected
        else:
            passed = expects_error and status == "value_error"
            if not expects_error and status != "value_error":
                errors.append(name + " raised " + status)
        results.append({"name": name, "passed": bool(passed)})
    return results, errors


def run_validation(source_text):
    errors = _policy_errors(source_text)
    if errors:
        return _report(False, [], errors)
    try:
        tree = ast.parse(source_text, filename=_CODE_FILENAME, mode="exec")
        globals_namespace = {"__builtins__": dict(_ALLOWED_BUILTINS_NAMESPACE)}
        locals_namespace = {}
        exec(compile(tree, _CODE_FILENAME, "exec"), globals_namespace, locals_namespace)
        function = locals_namespace.get("topological_order")
        if not callable(function):
            return _report(False, [], ["topological_order is not callable"])
    except (SyntaxError, TypeError, ValueError, MemoryError):
        return _report(False, [], ["source could not be loaded"])
    except BaseException as error:
        return _report(False, [], ["source loading failed: " + type(error).__name__])
    tests, test_errors = _run_tests(function)
    return _report(not test_errors and all(test["passed"] for test in tests), tests, test_errors)


def _cli_report(path):
    try:
        with open(path, "rb") as handle:
            data = handle.read(MAX_SOURCE_BYTES + 1)
    except (OSError, ValueError):
        return _report(False, [], ["source file could not be read"])
    if len(data) > MAX_SOURCE_BYTES:
        return _report(False, [], ["source exceeds 64 KiB"])
    try:
        source_text = data.decode("utf-8")
    except UnicodeDecodeError:
        return _report(False, [], ["source file is not UTF-8"])
    return run_validation(source_text)


def main(argv=None):
    arguments = sys.argv[1:] if argv is None else list(argv)
    if len(arguments) != 1:
        report = _report(False, [], ["expected one source path"])
    else:
        report = _cli_report(arguments[0])
    sys.stdout.write(json.dumps(report, ensure_ascii=True, separators=(",", ":")) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
