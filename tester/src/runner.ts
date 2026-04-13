/** Executes the SOL26 interpreter or SOL2XML parser as a subprocess. */

import { readFileSync, writeFileSync, unlinkSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";

export interface RunResult {
  exitCode: number;
  stdout: string;
  stderr: string;
}

function spawnProcess(bin: string, args: string[], stdinContent?: string): RunResult {
  /** Spawn a process and return its exit code and output. */
  const result = spawnSync(bin, args, {
    encoding: "utf8",
    input: stdinContent,
  });

  if (result.error) {
    return { exitCode: -1, stdout: "", stderr: result.error.message };
  }

  return { exitCode: result.status ?? 1, stdout: result.stdout, stderr: result.stderr };
}

export function runInterpreter(
  interpreterCmd: string,
  sourceFile: string,
  stdinFile: string | null
): RunResult {
  /** Run the interpreter on a source XML file and return exit code and output. */
  const parts = interpreterCmd.split(" ");
  const bin = parts[0] ?? "";
  const args = [...parts.slice(1), "-s", sourceFile];
  const stdin = stdinFile !== null ? readFileSync(stdinFile, "utf8") : undefined;
  return spawnProcess(bin, args, stdin);
}

export function runParser(parserCmd: string, sourceFile: string): RunResult {
  /** Run the SOL2XML parser on a SOL26 source file and return exit code and XML 
  output. */
  const parts = parserCmd.split(" ");
  const bin = parts[0] ?? "";
  return spawnProcess(bin, [...parts.slice(1), sourceFile]);
}

export function runParserThenInterpreter(
  parserCmd: string,
  interpreterCmd: string,
  sourceFile: string,
  stdinFile: string | null
): { parserResult: RunResult; interpreterResult: RunResult | null } {
  /** Run parser first, then pass its XML output to the interpreter via a temp file.
   */
  const parserResult = runParser(parserCmd, sourceFile);
  if (parserResult.exitCode !== 0) {
    return { parserResult, interpreterResult: null };
  }

  const tmpFile = join(tmpdir(), `sol26_${String(Date.now())}.xml`);
  try {
    writeFileSync(tmpFile, parserResult.stdout, "utf8");
    const interpreterResult = runInterpreter(interpreterCmd, tmpFile, stdinFile);
    return { parserResult, interpreterResult };
  } finally {
    try {
      unlinkSync(tmpFile);
    } catch {
      /* ignore */
    }
  }
}
