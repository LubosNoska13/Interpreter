/** Parser for SOLtest test case definition files. */

import { existsSync, readFileSync } from "node:fs";
import { basename } from "node:path";

import {
  TestCaseDefinition,
  TestCaseType,
  UnexecutedReason,
  UnexecutedReasonCode,
} from "./models.js";

export type ParseResult =
  | { ok: true; testCase: TestCaseDefinition }
  | { ok: false; reason: UnexecutedReason };

interface TestHeaders {
  description: string | null;
  category: string | null;
  parserCodes: number[];
  interpreterCodes: number[];
  points: number;
}

export function extractTestBody(filePath: string): string {
  /** Return the source code body of a .test file (everything after the first blank
  line). */
  const lines = readFileSync(filePath, "utf8").split("\n");
  const blankIndex = lines.findIndex((l) => l.trim() === "");
  if (blankIndex === -1) return "";
  return lines.slice(blankIndex + 1).join("\n");
}

function parseHeaders(lines: string[]): TestHeaders {
  /** Extract metadata from the header lines of a SOLtest file. */
  const headers: TestHeaders = {
    description: null,
    category: null,
    parserCodes: [],
    interpreterCodes: [],
    points: 1,
  };

  for (const line of lines) {
    if (line === "" || line === "\r") break;
    const t = line.trimEnd();
    if (t.startsWith("*** ")) headers.description = t.slice(4).trim();
    else if (t.startsWith("+++ ")) headers.category = t.slice(4).trim();
    else if (t.startsWith("!C! ")) headers.parserCodes.push(parseInt(t.slice(4).trim(), 10));
    else if (t.startsWith("!I! ")) headers.interpreterCodes.push(parseInt(t.slice(4).trim(), 10));
    else if (t.startsWith(">>> ")) headers.points = parseInt(t.slice(4).trim(), 10);
  }

  return headers;
}

function determineType(parserCodes: number[], interpreterCodes: number[]): TestCaseType | null {
  /** Determine test type from presence of parser and interpreter exit codes. */
  if (parserCodes.length > 0 && interpreterCodes.length > 0) return TestCaseType.COMBINED;
  if (parserCodes.length > 0) return TestCaseType.PARSE_ONLY;
  if (interpreterCodes.length > 0) return TestCaseType.EXECUTE_ONLY;
  return null;
}

export function parseTestFile(filePath: string): ParseResult {
  /** Parse a .test file and return a TestCaseDefinition or a failure reason. */
  let content: string;
  try {
    content = readFileSync(filePath, "utf8");
  } catch {
    return {
      ok: false,
      reason: new UnexecutedReason(
        UnexecutedReasonCode.MALFORMED_TEST_CASE_FILE,
        "Cannot read file"
      ),
    };
  }

  const headers = parseHeaders(content.split("\n"));

  if (headers.category === null) {
    return {
      ok: false,
      reason: new UnexecutedReason(
        UnexecutedReasonCode.MALFORMED_TEST_CASE_FILE,
        "Missing category"
      ),
    };
  }

  const testType = determineType(headers.parserCodes, headers.interpreterCodes);
  if (testType === null) {
    return {
      ok: false,
      reason: new UnexecutedReason(
        UnexecutedReasonCode.CANNOT_DETERMINE_TYPE,
        "No exit codes specified"
      ),
    };
  }

  const stem = basename(filePath, ".test");
  const stdinFile = filePath.replace(/\.test$/, ".in");
  const stdoutFile = filePath.replace(/\.test$/, ".out");

  try {
    return {
      ok: true,
      testCase: new TestCaseDefinition({
        name: stem,
        test_type: testType,
        description: headers.description,
        category: headers.category,
        points: headers.points,
        test_source_path: filePath,
        stdin_file: existsSync(stdinFile) ? stdinFile : null,
        expected_stdout_file: existsSync(stdoutFile) ? stdoutFile : null,
        expected_parser_exit_codes: headers.parserCodes.length > 0 ? headers.parserCodes : null,
        expected_interpreter_exit_codes:
          headers.interpreterCodes.length > 0 ? headers.interpreterCodes : null,
      }),
    };
  } catch (e) {
    return {
      ok: false,
      reason: new UnexecutedReason(
        UnexecutedReasonCode.MALFORMED_TEST_CASE_FILE,
        e instanceof Error ? e.message : String(e)
      ),
    };
  }
}
