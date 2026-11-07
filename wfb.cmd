@echo off
rem Windows entry point, the twin of ./wfb: `wfb build design.yaml` from any
rem directory. Runs the TypeScript CLI (ts/src/cli.ts) under the Node on PATH,
rem which must strip types and be patched (an official Node 22.23.4+, 24.22.1+
rem or 26.12.1+).
node "%~dp0ts\src\cli.ts" %*
