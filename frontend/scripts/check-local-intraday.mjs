#!/usr/bin/env node
/**
 * 개인 로컬 모드(DEC-052) 프론트 순수 로직 검증. 실행:
 *   node --experimental-strip-types --test scripts/check-local-intraday.mjs
 */
import assert from "node:assert/strict";
import { test } from "node:test";
import { isPrivateHostname } from "../src/lib/privateHost.ts";

test("내 PC·사설망 주소는 true", () => {
  for (const h of ["localhost", "LOCALHOST", "127.0.0.1", "127.5.6.7", "::1", "[::1]", "10.1.2.3", "192.168.0.12", "172.16.0.1", "172.31.255.255"]) {
    assert.equal(isPrivateHostname(h), true, h);
  }
});

test("공개 도메인·공인 IP·비슷한 이름은 false", () => {
  for (const h of ["stock.example.com", "example.com", "8.8.8.8", "172.15.0.1", "172.32.0.1", "192.169.0.1", "localhost.evil.com", "evil-localhost", "127.0.0.1.evil.com", "", "10.0.0", "192.168.0.1.nip.io"]) {
    assert.equal(isPrivateHostname(h), false, h);
  }
});
