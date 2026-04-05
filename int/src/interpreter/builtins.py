"""Initialization of built-in SOL26 classes and their inheritance hierarchy."""

from interpreter.sol_object import SOLClass


def create_builtins() -> dict[str, SOLClass]:
    """Create and return all built-in SOL26 classes with their parent relationships."""

    object_class = SOLClass("Object", None, {})
    nil_class = SOLClass("Nil", object_class, {})
    integer_class = SOLClass("Integer", object_class, {})
    string_class = SOLClass("String", object_class, {})
    true_class = SOLClass("True", object_class, {})
    false_class = SOLClass("False", object_class, {})
    block_class = SOLClass("Block", object_class, {})

    return {
        "Object": object_class,
        "Nil": nil_class,
        "Integer": integer_class,
        "String": string_class,
        "True": true_class,
        "False": false_class,
        "Block": block_class
    }
