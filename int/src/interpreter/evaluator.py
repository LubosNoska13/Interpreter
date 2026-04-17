"""Expression evaluator for the SOL26 interpreter."""

from typing import TextIO

from interpreter.error_codes import ErrorCode
from interpreter.exceptions import InterpreterError
from interpreter.input_model import Block, Expr, Literal, Method, Send, Var
from interpreter.sol_object import Environment, SOLClass, SOLObject


class Evaluator:
    """Evaluates SOL26 expressions within a given variable environment."""

    def __init__(self, classes: dict[str, SOLClass], input_io: TextIO) -> None:
        """Initialize the evaluator with the class registry."""
        self.classes = classes
        self.input_io = input_io

    def _eval_literal(self, literal: Literal) -> SOLObject:
        """Create a SOLObject from a literal node."""
        sol_class = self.classes.get(literal.class_id)
        if sol_class is None:
            raise InterpreterError(ErrorCode.SEM_UNDEF, f"Unknown class '{literal.class_id}'")
        obj = SOLObject(sol_class, {})
        if literal.class_id == "Integer":
            obj.native_value = int(literal.value)
        elif literal.class_id == "String":
            obj.native_value = (
                literal.value.replace("\\n", "\n").replace("\\'", "'").replace("\\\\", "\\")
            )

        if literal.value == literal.class_id:
            obj.is_class_ref = True
            obj.referred_class = sol_class

        return obj

    def _eval_var(self, var: Var, env: Environment) -> SOLObject:
        """Look up a variable by name through the environment chain."""
        current: Environment | None = env
        while current is not None:
            if var.name in current.variables:
                return current.variables[var.name]
            current = current.parent
        raise InterpreterError(ErrorCode.SEM_UNDEF, f"Undefined variable '{var.name}'")

    def _eval_block(self, block: Block, env: Environment) -> SOLObject:
        """Wrap a block literal as a SOLObject, capturing the current environment as a closure."""
        obj = SOLObject(self.classes["Block"], {})
        obj.block_node = block
        obj.block_env = env
        return obj

    def _get_current_class(self, env: Environment) -> SOLClass | None:
        """Walk up the environment chain to find the nearest current_class."""
        current: Environment | None = env
        while current is not None:
            if current.current_class is not None:
                return current.current_class
            current = current.parent
        return None

    def _eval_send(self, send: Send, env: Environment) -> SOLObject:
        """Evaluate a message send by dispatching to the receiver's method."""
        receiver = self.evaluate(send.receiver, env)
        args = [self.evaluate(arg.expr, env) for arg in send.args]

        is_super = send.receiver.var is not None and send.receiver.var.name == "super"
        current_class = self._get_current_class(env)
        if is_super and current_class is not None and current_class.parent is not None:
            start_class = current_class.parent
        else:
            start_class = receiver.sol_class

        # 1. User-defined methods first
        lookup = self._lookup_method(start_class, send.selector)
        if lookup is not None:
            method, defining_class = lookup
            return self._execute_method(method, receiver, args, defining_class)

        # 2. Built-in methods (respecting inheritance)
        builtin_result = self._dispatch_builtin(receiver, send.selector, args)
        if builtin_result is not None:
            return builtin_result

        # 3. Attribute setter / getter
        if len(args) == 1 and send.selector.endswith(":"):
            attr_name = send.selector.rstrip(":")
            if self._lookup_method(receiver.sol_class, attr_name) is not None:
                raise InterpreterError(
                    ErrorCode.INT_INST_ATTR, f"Attribute '{attr_name}' collides with method"
                )
            receiver.attributes[attr_name] = args[0]
            return args[0]

        if len(args) == 0 and send.selector in receiver.attributes:
            return receiver.attributes[send.selector]

        raise InterpreterError(
            ErrorCode.INT_DNU,
            f"'{receiver.sol_class.name}' does not understand '{send.selector}'",
        )

    def _execute_method(
        self, method: Method, receiver: SOLObject, args: list[SOLObject], current_class: SOLClass
    ) -> SOLObject:
        """Execute a method by binding parameters and evaluating its assignments."""
        variables: dict[str, SOLObject] = {"self": receiver, "super": receiver}
        for param, arg in zip(method.block.parameters, args, strict=True):
            variables[param.name] = arg
        method_env = Environment(variables, parent=None)
        method_env.current_class = current_class
        param_names = {p.name for p in method.block.parameters}
        result: SOLObject = receiver
        for assign in method.block.assigns:
            if assign.target.name in param_names:
                raise InterpreterError(
                    ErrorCode.SEM_COLLISION, f"Assignment to parameter '{assign.target.name}'"
                )
            result = self.evaluate(assign.expr, method_env)
            self._set_variable(method_env, assign.target.name, result)
        return result

    def evaluate(self, expr: Expr, env: Environment) -> SOLObject:
        """Evaluate an expression and return the resulting SOLObject."""

        if expr.literal is not None:
            return self._eval_literal(expr.literal)
        if expr.var is not None:
            return self._eval_var(expr.var, env)
        if expr.block is not None:
            return self._eval_block(expr.block, env)
        if expr.send is not None:
            return self._eval_send(expr.send, env)
        raise InterpreterError(ErrorCode.GENERAL_OTHER, "Invalid expression")

    def _execute_block(self, block_obj: SOLObject, args: list[SOLObject]) -> SOLObject:
        """Execute a Block SOLObject with the given arguments in its captured environment."""
        if block_obj.block_node is None or block_obj.block_env is None:
            raise InterpreterError(ErrorCode.INT_OTHER, "Not a valid block")

        if len(args) != len(block_obj.block_node.parameters):
            raise InterpreterError(
                ErrorCode.SEM_ARITY,
                f"Block expects {len(block_obj.block_node.parameters)} args, got {len(args)}",
            )

        variables: dict[str, SOLObject] = {}
        for param, arg in zip(block_obj.block_node.parameters, args, strict=True):
            variables[param.name] = arg

        block_env = Environment(variables, parent=block_obj.block_env)
        param_names = {p.name for p in block_obj.block_node.parameters}
        result: SOLObject = block_obj
        for assign in block_obj.block_node.assigns:
            if assign.target.name in param_names:
                raise InterpreterError(
                    ErrorCode.SEM_COLLISION, f"Assignment to parameter '{assign.target.name}'"
                )
            result = self.evaluate(assign.expr, block_env)
            self._set_variable(block_env, assign.target.name, result)

        return result

    def _int_val(self, obj: SOLObject) -> int:
        """Extract the native int value from a SOLObject, raising an error if not an Integer."""
        if not isinstance(obj.native_value, int):
            raise InterpreterError(ErrorCode.INT_OTHER, "Expected Integer")
        return obj.native_value

    def _dispatch_string(
        self, receiver: SOLObject, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Handle built-in String messages."""
        if selector == "print":
            print(receiver.native_value, end="")
            return receiver

        if selector == "asString":
            return receiver

        if selector == "length":
            obj = SOLObject(self.classes["Integer"], {})
            obj.native_value = len(str(receiver.native_value))
            return obj

        if selector == "concatenateWith:":
            if args[0].sol_class.name not in ("String",):
                return SOLObject(self.classes["Nil"], {})
            obj = SOLObject(self.classes["String"], {})
            obj.native_value = str(receiver.native_value) + str(args[0].native_value)
            return obj

        if selector == "asInteger":
            try:
                obj = SOLObject(self.classes["Integer"], {})
                obj.native_value = int(str(receiver.native_value))
                return obj
            except ValueError:
                return SOLObject(self.classes["Nil"], {})

        if selector == "read":
            obj = SOLObject(self.classes["String"], {})
            obj.native_value = self.input_io.readline().rstrip("\n")
            return obj

        if selector == "startsWith:endsBefore:":
            s = str(receiver.native_value)
            start = self._int_val(args[0]) - 1
            end = self._int_val(args[1]) - 1
            if start < 0 or end < 0 or start > len(s) or end > len(s):
                return SOLObject(self.classes["Nil"], {})
            obj = SOLObject(self.classes["String"], {})
            obj.native_value = s[start:end] if end > start else ""
            return obj

        if selector == "equalTo:":
            if args[0].sol_class.name != "String":
                return SOLObject(self.classes["False"], {})
            result = receiver.native_value == args[0].native_value
            return SOLObject(self.classes["True" if result else "False"], {})

        return None

    def _dispatch_integer(
        self, receiver: SOLObject, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Handle built-in Integer messages."""
        if selector == "asString":
            obj = SOLObject(self.classes["String"], {})
            obj.native_value = str(receiver.native_value)
            return obj

        if selector == "plus:":
            obj = SOLObject(self.classes["Integer"], {})
            obj.native_value = self._int_val(receiver) + self._int_val(args[0])
            return obj

        if selector == "minus:":
            obj = SOLObject(self.classes["Integer"], {})
            obj.native_value = self._int_val(receiver) - self._int_val(args[0])
            return obj

        if selector == "multiplyBy:":
            obj = SOLObject(self.classes["Integer"], {})
            obj.native_value = self._int_val(receiver) * self._int_val(args[0])
            return obj

        if selector == "divBy:":
            if args[0].native_value == 0:
                raise InterpreterError(ErrorCode.INT_INVALID_ARG, "Division by zero")
            obj = SOLObject(self.classes["Integer"], {})
            obj.native_value = self._int_val(receiver) // self._int_val(args[0])
            return obj

        if selector == "equalTo:":
            result = self._int_val(receiver) == self._int_val(args[0])
            return SOLObject(self.classes["True" if result else "False"], {})

        if selector == "greaterThan:":
            result = self._int_val(receiver) > self._int_val(args[0])
            return SOLObject(self.classes["True" if result else "False"], {})

        if selector == "asInteger":
            return receiver

        if selector == "timesRepeat:":
            block_obj = args[0]
            for i in range(1, self._int_val(receiver) + 1):
                iter_obj = SOLObject(self.classes["Integer"], {})
                iter_obj.native_value = i
                self._execute_block(block_obj, [iter_obj])
            return receiver

        return None

    def _dispatch_bool(
        self, receiver: SOLObject, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Handle built-in True and False messages."""
        is_true = receiver.sol_class.name == "True"

        if selector == "not":
            return SOLObject(self.classes["False" if is_true else "True"], {})

        if selector == "asString":
            obj = SOLObject(self.classes["String"], {})
            obj.native_value = "true" if is_true else "false"
            return obj

        if selector == "and:":
            if not is_true:
                return receiver
            return self._execute_block(args[0], [])

        if selector == "or:":
            if is_true:
                return receiver
            return self._execute_block(args[0], [])

        if selector == "ifTrue:ifFalse:":
            branch = args[0] if is_true else args[1]
            return self._execute_block(branch, [])

        if selector == "equalTo:":
            result = receiver.sol_class.name == args[0].sol_class.name
            return SOLObject(self.classes["True" if result else "False"], {})

        return None

    def _dispatch_nil(
        self, receiver: SOLObject, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Handle built-in Nil messages."""
        if selector == "asString":
            obj = SOLObject(self.classes["String"], {})
            obj.native_value = "nil"
            return obj
        return None

    def _dispatch_block(
        self, receiver: SOLObject, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Handle built-in Block messages."""
        if selector.startswith("value"):
            return self._execute_block(receiver, args)

        if selector == "whileTrue:":
            body = args[0]
            while True:
                condition = self._execute_block(receiver, [])
                if condition.sol_class.name != "True":
                    break
                self._execute_block(body, [])
            return SOLObject(self.classes["Nil"], {})

        return None

    def _set_variable(self, env: Environment, name: str, value: SOLObject) -> None:
        """Assign a variable, updating it in the nearest enclosing scope where it exists."""
        current: Environment | None = env
        while current is not None:
            if name in current.variables:
                current.variables[name] = value
                return
            current = current.parent
        env.variables[name] = value

    def _dispatch_object(
        self, receiver: SOLObject, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Handle built-in Object messages available to all objects."""
        if selector == "identicalTo:":
            result = receiver is args[0]
            return SOLObject(self.classes["True" if result else "False"], {})

        if selector == "equalTo:":
            result = receiver is args[0]
            return SOLObject(self.classes["True" if result else "False"], {})

        if selector == "asString":
            obj = SOLObject(self.classes["String"], {})
            obj.native_value = ""
            return obj

        if selector == "isNil":
            result = receiver.sol_class.name == "Nil"
            return SOLObject(self.classes["True" if result else "False"], {})

        if selector == "isBoolean":
            result = receiver.sol_class.name in ("True", "False")
            return SOLObject(self.classes["True" if result else "False"], {})

        if selector == "isNumber":
            result = receiver.sol_class.name == "Integer"
            return SOLObject(self.classes["True" if result else "False"], {})

        if selector == "isString":
            result = receiver.sol_class.name == "String"
            return SOLObject(self.classes["True" if result else "False"], {})

        if selector == "isBlock":
            result = receiver.sol_class.name == "Block"
            return SOLObject(self.classes["True" if result else "False"], {})

        return None

    def _builtin_base(self, sol_class: SOLClass) -> str | None:
        """Return the name of the nearest built-in ancestor class, or None."""
        builtin_names = {"String", "Integer", "True", "False", "Nil", "Block"}
        current: SOLClass | None = sol_class
        while current is not None:
            if current.name in builtin_names:
                return current.name
            current = current.parent
        return None

    def _dispatch_builtin(
        self, receiver: SOLObject, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Dispatch a built-in method call, returning None if no built-in matches."""
        if receiver.is_class_ref and receiver.referred_class is not None:
            return self._dispatch_class(receiver.referred_class, selector, args)

        base = self._builtin_base(receiver.sol_class)

        if base == "String":
            return self._dispatch_string(receiver, selector, args)
        if base == "Integer":
            return self._dispatch_integer(receiver, selector, args)
        if base in ("True", "False"):
            return self._dispatch_bool(receiver, selector, args)
        if base == "Nil":
            return self._dispatch_nil(receiver, selector, args)
        if base == "Block":
            return self._dispatch_block(receiver, selector, args)

        return self._dispatch_object(receiver, selector, args)

    def _lookup_method(self, sol_class: SOLClass, selector: str) -> tuple[Method, SOLClass] | None:
        """Search for a method by selector, returning the method and its defining class."""
        current: SOLClass | None = sol_class
        while current is not None:
            if selector in current.methods:
                return current.methods[selector], current
            current = current.parent
        return None

    def _is_instance_of(self, obj: SOLObject, sol_class: SOLClass) -> bool:
        """Check if obj is an instance of sol_class or its subclass."""
        current: SOLClass | None = obj.sol_class
        while current is not None:
            if current.name == sol_class.name:
                return True
            current = current.parent
        return False

    def _dispatch_class(
        self, sol_class: SOLClass, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Handle class-side messages: new (constructor) and from: (copy constructor)."""
        if selector == "new":
            if sol_class.singleton_instance is not None:
                return sol_class.singleton_instance
            return SOLObject(sol_class, {})

        if selector == "from:":
            if sol_class.singleton_instance is not None:
                return sol_class.singleton_instance
            original = args[0]
            if not self._is_instance_of(original, sol_class):
                raise InterpreterError(
                    ErrorCode.INT_INVALID_ARG, "from: argument is not an instance of the class"
                )
            obj = SOLObject(sol_class, dict(original.attributes))
            obj.native_value = original.native_value
            return obj

        return None
