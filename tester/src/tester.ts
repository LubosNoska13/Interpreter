#!/usr/bin/env node
/**
 * An integration testing script for the SOL26 interpreter.
 *
 * IPP: You can implement the entire tool in this file if you wish, but it is recommended to split
 *      the code into multiple files and modules as you see fit.
 *
 *      Below, you have some code to get you started with the CLI argument parsing and logging setup,
 *      but you are **free to modify it** in whatever way you like.
 *
 * Author: Ondřej Ondryáš <iondryas@fit.vut.cz>
 *
 * AI usage notice: The author used OpenAI Codex to create the implementation of this
 *                  module based on its Python counterpart.
 */

import { existsSync, lstatSync, writeFileSync, unlinkSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { parseArgs } from "node:util";

import { TestReport } from "./models.js";

import { pino } from "pino";

import { readdirSync } from "node:fs";
import { join } from "node:path";
import { parseTestFile, type ParseResult } from "./test_parser.js";
import { TestCaseDefinition, UnexecutedReason, UnexecutedReasonCode } from "./models.js";

import { runInterpreter, runParser, runParserThenInterpreter, type RunResult } from "./runner.js";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { CategoryReport, TestCaseReport, TestCaseType, TestResult } from "./models.js";

import { extractTestBody } from "./test_parser.js";

const logger = pino({
  transport: {
    target: "pino-pretty",
    options: {
      colorize: true,
      destination: 2,
    },
  },
});

interface CliArguments {
  tests_dir: string;
  recursive: boolean;
  output: string | null;
  dry_run: boolean;
  include: string[] | null;
  include_category: string[] | null;
  include_test: string[] | null;
  exclude: string[] | null;
  exclude_category: string[] | null;
  exclude_test: string[] | null;
  verbose: number;
  regex_filters: boolean;
  interpreter: string;
  parser: string | null;
}

function writeResult(resultReport: TestReport, outputFile: string | null): void {
  /**
   * Writes the final report to the specified output file or standard output if no file is provided.
   */
  const resultJson = JSON.stringify(resultReport, null, 2);
  if (outputFile !== null) {
    writeFileSync(outputFile, resultJson, "utf8");
    return;
  }

  console.log(resultJson);
}

const DOUBLE_LETTER_SHORT_OPTION_NORMALIZATION = new Map<string, string>([
  ["-ic", "--include-category"],
  ["-it", "--include-test"],
  ["-ec", "--exclude-category"],
  ["-et", "--exclude-test"],
]);

const HELP_TEXT = [
  "Usage:",
  "  tester [options] tests_dir",
  "",
  "Positional arguments:",
  "  tests_dir                 Path to a directory with the test cases in the SOLtest format.",
  "",
  "Options:",
  "  -h, --help                Show this help message and exit.",
  "  -r, --recursive           Recursively search for test cases in subdirectories of the provided directory.",
  "  -o, --output <path>       The output file to write the test results to. If not provided, results will be printed to standard output.",
  "  --dry-run                 Perform a dry run: discover the test cases but don't actually execute them.",
  "  -i, --include <value>     Include only test cases with the specified name or category. Can be used multiple times to specify multiple criteria.Can be combined with -ic and -it.",
  "  -ic, --include-category <value>",
  "                            Include only test cases with the specified category. Can be used multiple times to specify multiple accepted categories. Can be combined with -it and -i.",
  "  -it, --include-test <value>",
  "                            Include only test cases with the specified name. Can be used multiple times to specify multiple accepted names. Can be combined with -ic and -i.",
  "  -e, --exclude <value>     Exclude test cases with the specified name or category. Can be used multiple times to specify multiple criteria.Can be combined with -ic and -it.",
  "  -ec, --exclude-category <value>",
  "                            Exclude test cases with the specified category. Can be used multiple times to specify multiple accepted categories. Can be combined with -it and -i.",
  "  -et, --exclude-test <value>",
  "                            Exclude test cases with the specified name. Can be used multiple times to specify multiple accepted names. Can be combined with -ic and -i.",
  "  -g                        When used, the filters specified with -i[ct]/-e[ct] will be interpreted as regular expressions instead of literal strings.",
  "  -v, --verbose             Enable verbose logging output (using once = INFO level, using twice = DEBUG level).",
  "  --interpreter <path>     Path to the interpreter entry point (e.g. python3/src/int/src/solint.py).",
  "  --parser <path>          Path to the SOL2XML parser binary (required for combined tests).",
];

const PARSE_OPTIONS = {
  help: { type: "boolean", short: "h", default: false },
  recursive: { type: "boolean", short: "r", default: false },
  output: { type: "string", short: "o" },
  "dry-run": { type: "boolean", default: false },
  include: { type: "string", short: "i", multiple: true },
  "include-category": { type: "string", multiple: true },
  "include-test": { type: "string", multiple: true },
  exclude: { type: "string", short: "e", multiple: true },
  "exclude-category": { type: "string", multiple: true },
  "exclude-test": { type: "string", multiple: true },
  "regex-filters": { type: "boolean", short: "g", default: false },
  verbose: { type: "boolean", short: "v", multiple: true },
  interpreter: { type: "string" },
  parser: { type: "string" },
} as const;

function normalizeArgv(argv: string[]): string[] {
  return argv.map((arg) => DOUBLE_LETTER_SHORT_OPTION_NORMALIZATION.get(arg) ?? arg);
}

function printHelp(): void {
  console.log(HELP_TEXT.join("\n"));
}

function listOrNull(values: string[] | undefined): string[] | null {
  if (values === undefined || values.length === 0) {
    return null;
  }

  return values;
}

function parseCliArgumentsRaw(argv: string[]) {
  return parseArgs({
    args: normalizeArgv(argv),
    options: PARSE_OPTIONS,
    allowPositionals: true,
    strict: true,
  } as const);
}

function validateOutputPath(outputPath: string): void {
  /** Validate that the output file's parent directory exists and warn if file exists.
   */
  const outputParent = dirname(outputPath);
  if (!existsSync(outputParent)) {
    console.error("The parent directory of the output file does not exist.");
    process.exit(1);
  }
  if (existsSync(outputPath)) {
    logger.warn("The output file will be overwritten: %s", outputPath);
  }
}

function parseArguments(): CliArguments {
  /**
   * Parses the command-line arguments and performs basic validation a sanitization.
   */
  let parsed: ReturnType<typeof parseCliArgumentsRaw>;

  try {
    parsed = parseCliArgumentsRaw(process.argv.slice(2));
  } catch (error: unknown) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(message);
    process.exit(2);
  }

  const parsedValues = parsed.values;

  if (parsedValues["help"]) {
    printHelp();
    process.exit(0);
  }

  if (parsed.positionals.length !== 1 || parsed.positionals[0] === undefined) {
    console.error("Exactly one positional argument (tests_dir) is required.");
    process.exit(2);
  }

  if (!parsedValues["interpreter"]) {
    console.error("--interpreter is required.");
    process.exit(1);
  }

  const args: CliArguments = {
    tests_dir: resolve(parsed.positionals[0]),
    recursive: parsedValues["recursive"],
    output: parsedValues["output"] ?? null,
    dry_run: parsedValues["dry-run"],
    include: listOrNull(parsedValues["include"]),
    include_category: listOrNull(parsedValues["include-category"]),
    include_test: listOrNull(parsedValues["include-test"]),
    exclude: listOrNull(parsedValues["exclude"]),
    exclude_category: listOrNull(parsedValues["exclude-category"]),
    exclude_test: listOrNull(parsedValues["exclude-test"]),
    verbose: parsedValues["verbose"]?.length ?? 0,
    regex_filters: parsedValues["regex-filters"],
    interpreter: parsedValues["interpreter"] ?? "",
    parser: parsedValues["parser"] ?? null,
  };

  // Check source directory
  if (!existsSync(args.tests_dir) || !lstatSync(args.tests_dir).isDirectory()) {
    console.error("The provided path is not a directory.");
    process.exit(1);
  }

  // Warn if the output file already exists
  if (args.output !== null) {
    validateOutputPath(args.output);
  }

  return args;
}

function discoverTests(
  testsDir: string,
  recursive: boolean
): { discovered: TestCaseDefinition[]; unexecuted: Record<string, UnexecutedReason> } {
  /** Find all .test files in the directory and parse them. */
  const discovered: TestCaseDefinition[] = [];
  const unexecuted: Record<string, UnexecutedReason> = {};

  const entries = readdirSync(testsDir, { withFileTypes: true });

  for (const entry of entries) {
    const fullPath = join(testsDir, entry.name);

    if (entry.isDirectory() && recursive) {
      const sub = discoverTests(fullPath, recursive);
      discovered.push(...sub.discovered);
      Object.assign(unexecuted, sub.unexecuted);
      continue;
    }

    if (!entry.isFile() || !entry.name.endsWith(".test")) continue;

    const result: ParseResult = parseTestFile(fullPath);
    if (result.ok) {
      discovered.push(result.testCase);
    } else {
      const name = entry.name.replace(/\.test$/, "");
      unexecuted[name] = result.reason;
    }
  }

  return { discovered, unexecuted };
}
function matchesFilter(test: TestCaseDefinition, filter: string, regex: boolean): boolean {
  /** Check if a test case matches a single filter value by name or category. */
  if (regex) {
    const re = new RegExp(filter);
    return re.test(test.name) || re.test(test.category);
  }
  return test.name === filter || test.category === filter;
}

function filterTests(
  tests: TestCaseDefinition[],
  args: CliArguments
): { toRun: TestCaseDefinition[]; filtered: TestCaseDefinition[] } {
  /** Split tests into those to run and those filtered out. */
  const toRun: TestCaseDefinition[] = [];
  const filtered: TestCaseDefinition[] = [];

  for (const test of tests) {
    if (isExcluded(test, args)) {
      filtered.push(test);
      continue;
    }
    if (isIncluded(test, args)) {
      toRun.push(test);
    } else {
      filtered.push(test);
    }
  }

  return { toRun, filtered };
}

function isExcluded(test: TestCaseDefinition, args: CliArguments): boolean {
  /** Return true if the test matches any exclude filter. */
  if (args.exclude?.some((f) => matchesFilter(test, f, args.regex_filters))) return true;
  if (
    args.exclude_category?.some(
      (f) => test.category === f || (args.regex_filters && new RegExp(f).test(test.category))
    )
  )
    return true;
  if (
    args.exclude_test?.some(
      (f) => test.name === f || (args.regex_filters && new RegExp(f).test(test.name))
    )
  )
    return true;
  return false;
}

function isIncluded(test: TestCaseDefinition, args: CliArguments): boolean {
  /** Return true if no include filters are set, or the test matches at least one. */
  const hasInclude = args.include || args.include_category || args.include_test;
  if (!hasInclude) return true;
  if (args.include?.some((f) => matchesFilter(test, f, args.regex_filters))) return true;
  if (
    args.include_category?.some(
      (f) => test.category === f || (args.regex_filters && new RegExp(f).test(test.category))
    )
  )
    return true;
  if (
    args.include_test?.some(
      (f) => test.name === f || (args.regex_filters && new RegExp(f).test(test.name))
    )
  )
    return true;
  return false;
}

function runDiff(actualOutput: string, expectedFile: string): string | null {
  /** Compare actual output with expected file using diff. Returns diff output or null
   if equal. */
  const tmpFile = join(tmpdir(), `sol26_actual_${String(Date.now())}.txt`);
  try {
    writeFileSync(tmpFile, actualOutput, "utf8");
    const result = spawnSync("diff", [expectedFile, tmpFile], { encoding: "utf8" });
    return result.status === 0 ? null : result.stdout || result.stderr;
  } finally {
    try {
      unlinkSync(tmpFile);
    } catch {
      /* ignore */
    }
  }
}

function withTempBody(
  test: TestCaseDefinition,
  fn: (tmpPath: string) => TestCaseReport
): TestCaseReport {
  /** Write test body to a temp file, call fn with its path, then clean up. */
  const tmpPath = join(tmpdir(), `sol26_body_${String(Date.now())}.xml`);
  try {
    writeFileSync(tmpPath, extractTestBody(test.test_source_path), "utf8");
    return fn(tmpPath);
  } finally {
    try {
      unlinkSync(tmpPath);
    } catch {
      /* ignore */
    }
  }
}

function executeTest(
  test: TestCaseDefinition,
  interpreter: string,
  parser: string | null
): TestCaseReport {
  /** Execute a single test case and return its report. */
  if (test.test_type === TestCaseType.PARSE_ONLY) {
    if (parser === null) {
      return new TestCaseReport(
        TestResult.UNEXPECTED_PARSER_EXIT_CODE,
        null,
        null,
        null,
        "No parser configured"
      );
    }
    const r = runParser(parser, test.test_source_path);
    const expected = test.expected_parser_exit_codes ?? [];
    const passed = expected.includes(r.exitCode);
    return new TestCaseReport(
      passed ? TestResult.PASSED : TestResult.UNEXPECTED_PARSER_EXIT_CODE,
      r.exitCode,
      null,
      r.stdout,
      r.stderr
    );
  }

  if (test.test_type === TestCaseType.EXECUTE_ONLY) {
    return withTempBody(test, (tmpPath) =>
      evaluateInterpreterResult(runInterpreter(interpreter, tmpPath, test.stdin_file), null, test)
    );
  }

  if (parser === null) {
    return new TestCaseReport(
      TestResult.UNEXPECTED_PARSER_EXIT_CODE,
      null,
      null,
      null,
      "No parser configured"
    );
  }

  const bodyPath = join(tmpdir(), `sol26_src_${String(Date.now())}.sol`);
  writeFileSync(bodyPath, extractTestBody(test.test_source_path), "utf8");
  let parserResult, interpreterResult;
  try {
    ({ parserResult, interpreterResult } = runParserThenInterpreter(
      parser,
      interpreter,
      bodyPath,
      test.stdin_file
    ));
  } finally {
    try {
      unlinkSync(bodyPath);
    } catch {
      /* ignore */
    }
  }

  const expectedParser = test.expected_parser_exit_codes ?? [0];
  if (!expectedParser.includes(parserResult.exitCode)) {
    return new TestCaseReport(
      TestResult.UNEXPECTED_PARSER_EXIT_CODE,
      parserResult.exitCode,
      null,
      parserResult.stdout,
      parserResult.stderr
    );
  }
  if (interpreterResult === null) {
    return new TestCaseReport(
      TestResult.UNEXPECTED_INTERPRETER_EXIT_CODE,
      parserResult.exitCode,
      null,
      parserResult.stdout,
      parserResult.stderr
    );
  }
  return evaluateInterpreterResult(interpreterResult, parserResult, test);
}

function makeReport(
  result: TestResult,
  parserResult: RunResult | null,
  intResult: RunResult | null,
  diff: string | null = null
): TestCaseReport {
  /** Build a TestCaseReport from run results. */
  return new TestCaseReport(
    result,
    parserResult?.exitCode ?? null,
    intResult?.exitCode ?? null,
    parserResult?.stdout ?? null,
    parserResult?.stderr ?? null,
    intResult?.stdout ?? null,
    intResult?.stderr ?? null,
    diff
  );
}

function evaluateInterpreterResult(
  r: RunResult,
  parserResult: RunResult | null,
  test: TestCaseDefinition
): TestCaseReport {
  /** Check interpreter exit code and optionally compare stdout with expected output.
   */
  const expected = test.expected_interpreter_exit_codes ?? [];
  if (!expected.includes(r.exitCode)) {
    return makeReport(TestResult.UNEXPECTED_INTERPRETER_EXIT_CODE, parserResult, r);
  }
  if (test.expected_stdout_file !== null && r.exitCode === 0) {
    const diff = runDiff(r.stdout, test.expected_stdout_file);
    if (diff !== null) {
      return makeReport(TestResult.INTERPRETER_RESULT_DIFFERS, parserResult, r, diff);
    }
  }
  return makeReport(TestResult.PASSED, parserResult, r);
}

function main(): void {
  /**
   * The main entry point for the SOL26 integration testing script.
   * It parses command-line arguments and executes the testing process.
   */

  // Set up logging
  // IPP: You do not have to use logging - but it is the recommended practice.
  //      See https://getpino.io/#/docs/api for more information.
  logger.level = "warn";

  // Parse the CLI arguments
  const args = parseArguments();

  // Enable debug or info logging if the verbose flag was set twice or once
  if (args.verbose >= 2) {
    logger.level = "debug";
  } else if (args.verbose === 1) {
    logger.level = "info";
  }

  const { discovered, unexecuted } = discoverTests(args.tests_dir, args.recursive);
  const { toRun, filtered } = filterTests(discovered, args);

  if (args.dry_run) {
    const report = new TestReport({ discovered_test_cases: discovered, unexecuted, results: {} });
    writeResult(report, args.output);
    return;
  }

  for (const test of filtered) {
    unexecuted[test.name] = new UnexecutedReason(UnexecutedReasonCode.FILTERED_OUT);
  }

  const results: Record<string, CategoryReport> = {};

  for (const test of toRun) {
    const report = executeTest(test, args.interpreter, args.parser);
    if (!(test.category in results)) {
      results[test.category] = new CategoryReport(0, 0, {});
    }
    const cat = results[test.category] ?? new CategoryReport(0, 0, {});
    const passed = report.result === TestResult.PASSED;
    results[test.category] = new CategoryReport(
      cat.total_points + test.points,
      cat.passed_points + (passed ? test.points : 0),
      { ...cat.test_results, [test.name]: report }
    );
  }

  const finalReport = new TestReport({ discovered_test_cases: discovered, unexecuted, results });
  writeResult(finalReport, args.output);
}

main();
