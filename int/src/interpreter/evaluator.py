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

    def _eval_send(self, send: Send, env: Environment) -> SOLObject:
        """Evaluate a message send by dispatching to the receiver's method."""
        receiver = self.evaluate(send.receiver, env)
        args = [self.evaluate(arg.expr, env) for arg in send.args]

        result = self._dispatch_builtin(receiver, send.selector, args)
        if result is not None:
            return result
        method = self._lookup_method(receiver.sol_class, send.selector)
        if method is None:
            raise InterpreterError(
                ErrorCode.INT_DNU,
                f"'{receiver.sol_class.name}' does not understand '{send.selector}'",
            )

        return self._execute_method(method, receiver, args)

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

        variables: dict[str, SOLObject] = {}
        for param, arg in zip(block_obj.block_node.parameters, args, strict=True):
            variables[param.name] = arg

        block_env = Environment(variables, parent=block_obj.block_env)
        result: SOLObject = block_obj
        for assign in block_obj.block_node.assigns:
            result = self.evaluate(assign.expr, block_env)
            block_env.variables[assign.target.name] = result

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
        return None

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
        if selector in ("isNumber", "isString", "isBlock", "isNil", "isBoolean"):
            return SOLObject(self.classes["False"], {})
        return None

    def _dispatch_builtin(
        self, receiver: SOLObject, selector: str, args: list[SOLObject]
    ) -> SOLObject | None:
        """Dispatch a built-in method call, returning None if no built-in matches."""
        class_name = receiver.sol_class.name

        if class_name == "String":
            return self._dispatch_string(receiver, selector, args)

        if class_name == "Integer":
            return self._dispatch_integer(receiver, selector, args)

        if class_name in ("True", "False"):
            return self._dispatch_bool(receiver, selector, args)

        if class_name == "Nil":
            return self._dispatch_nil(receiver, selector, args)

        if class_name == "Block":
            return self._dispatch_block(receiver, selector, args)

        return self._dispatch_object(receiver, selector, args)

    def _lookup_method(self, sol_class: SOLClass, selector: str) -> Method | None:
        """Search for a method by selector in the class hierarchy, returning None if not found."""
        current: SOLClass | None = sol_class
        while current is not None:
            if selector in current.methods:
                return current.methods[selector]
            current = current.parent
        return None

    def _execute_method(
        self, method: Method, receiver: SOLObject, args: list[SOLObject]
    ) -> SOLObject:
        """Execute a method by binding parameters and evaluating its assignments."""
        variables: dict[str, SOLObject] = {"self": receiver}
        for param, arg in zip(method.block.parameters, args, strict=True):
            variables[param.name] = arg

        method_env = Environment(variables, parent=None)

        result: SOLObject = receiver
        for assign in method.block.assigns:
            result = self.evaluate(assign.expr, method_env)
            method_env.variables[assign.target.name] = result

        return result
