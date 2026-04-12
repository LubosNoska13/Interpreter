"""
This module contains the main logic of the interpreter.

IPP: You must definitely modify this file. Bend it to your will.

Author: Ondřej Ondryáš <iondryas@fit.vut.cz>
Author: Ľuboš Noska <xnoskal00@stud.fit.vutbr.cz>
"""

import logging
from pathlib import Path
from typing import TextIO

from lxml import etree
from lxml.etree import ParseError
from pydantic import ValidationError

from interpreter.builtins import create_builtins
from interpreter.error_codes import ErrorCode
from interpreter.evaluator import Evaluator
from interpreter.exceptions import InterpreterError
from interpreter.input_model import Program
from interpreter.sol_object import SOLClass, SOLObject

logger = logging.getLogger(__name__)


class Interpreter:
    """
    The main interpreter class, responsible for loading the source file and executing the program.
    """

    def __init__(self) -> None:
        self.current_program: Program | None = None
        self.classes: dict[str, SOLClass] = create_builtins()

    def _load_classes(self) -> None:
        """Load all user-defined classes from the program into the class registry."""
        assert self.current_program is not None

        for class_def in self.current_program.classes:
            if class_def.name in self.classes:
                raise InterpreterError(ErrorCode.SEM_ERROR, f"Class {class_def.name} redefined")

            if class_def.parent not in self.classes:
                raise InterpreterError(
                    ErrorCode.SEM_UNDEF, f"Unknown parent class {class_def.parent}"
                )

            parent = self.classes[class_def.parent]
            methods = {method.selector: method for method in class_def.methods}
            self.classes[class_def.name] = SOLClass(class_def.name, parent, methods)

    def load_program(self, source_file_path: Path) -> None:
        """
        Reads the source SOL-XML file and stores it as the target program for this interpreter.
        If any program was previously loaded, it is replaced by the new one.

        IPP: If you wish to run static checks on the program before execution, this is a good place
             to call them from.
        """
        logger.info("Opening source file: %s", source_file_path)
        try:
            xml_tree = etree.parse(source_file_path)
        except ParseError as e:
            raise InterpreterError(
                error_code=ErrorCode.INT_XML, message="Error parsing input XML"
            ) from e
        try:
            self.current_program = Program.from_xml_tree(xml_tree.getroot())  # type: ignore
        except ValidationError as e:
            raise InterpreterError(
                error_code=ErrorCode.INT_STRUCTURE, message="Invalid SOL-XML structure"
            ) from e

        self._load_classes()

    def execute(self, input_io: TextIO) -> None:
        """
        Executes the currently loaded program, using the provided input stream as standard input.
        """

        if "Main" not in self.classes:
            raise InterpreterError(ErrorCode.SEM_MAIN, "Missing 'Main' class")
        main_class = self.classes["Main"]
        if "run" not in main_class.methods:
            raise InterpreterError(ErrorCode.SEM_MAIN, "Missing 'run' method in 'Main'")

        evaluator = Evaluator(self.classes, input_io)
        main_instance = SOLObject(main_class, {})
        run_method = main_class.methods["run"]
        evaluator._execute_method(run_method, main_instance, [], self.classes["Main"])
