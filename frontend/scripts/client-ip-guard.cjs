/**
 * Preload (AUTH-QA-3): install the client-IP sanitizer on every Node http server in this process, before Next
 * handles any request. Logic and rationale: ./client-ip.cjs.
 *   node --require ./scripts/client-ip-guard.cjs …   (package.json dev/start, Dockerfile CMD)
 */
"use strict";
require("./client-ip.cjs").install();
