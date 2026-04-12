"""Runtime representation of SOL26 objects, classes, and variable environments."""

from interpreter.input_model import Block as BlockNode
from interpreter.input_model import Method


class SOLClass:
    """Runtime representation of a SOL26 class definition."""

    def __init__(self, name: str, parent: SOLClass | None, methods: dict[str, Method]) -> None:
        self.name = name
        self.parent = parent
        self.methods = methods
        self.singleton_instance: SOLObject | None = None


class SOLObject:
    """Runtime representation of a live SOL26 object instance."""

    def __init__(self, sol_class: SOLClass, attributes: dict[str, SOLObject]) -> None:
        self.sol_class = sol_class
        self.attributes = attributes
        self.native_value: int | str | None = None
        self.block_node: BlockNode | None = None
        self.block_env: Environment | None = None
        self.is_class_ref: bool = False
        self.referred_class: SOLClass | None = None


class Environment:
    """Variable scope for a SOL26 block or method, supporting nested closures."""

    def __init__(self, variables: dict[str, SOLObject], parent: Environment | None) -> None:
        self.variables = variables
        self.parent = parent
        self.current_class: SOLClass | None = None
