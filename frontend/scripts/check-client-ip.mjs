// 실행: node --experimental-strip-types --test scripts/check-client-ip.mjs
import assert from "node:assert/strict";
import { test } from "node:test";
import { pickClientIp } from "../src/lib/clientIp.ts";

test("신뢰 프록시 1단: 오른쪽 끝 값이 실제 클라이언트", () => {
  assert.equal(pickClientIp("203.0.113.7", 1), "203.0.113.7");
});

test("왼쪽에 스푸핑한 값이 있어도 오른쪽 끝(프록시가 본 주소)을 쓴다", () => {
  assert.equal(pickClientIp("1.2.3.4, 203.0.113.7", 1), "203.0.113.7");
});

test("신뢰 프록시 2단이면 오른쪽에서 2번째", () => {
  assert.equal(pickClientIp("198.51.100.9, 203.0.113.7", 2), "198.51.100.9");
});

test("프록시 신뢰 0단·헤더 없음·값 부족이면 null(fail closed)", () => {
  assert.equal(pickClientIp("203.0.113.7", 0), null);
  assert.equal(pickClientIp(null, 1), null);
  assert.equal(pickClientIp("", 1), null);
  assert.equal(pickClientIp("203.0.113.7", 2), null);
});

test("IP 형식이 아닌 값은 거부(헤더 주입 방지)", () => {
  assert.equal(pickClientIp("evil\r\nX-Foo: 1", 1), null);
  assert.equal(pickClientIp("999.1.1.1", 1), null);
  assert.equal(pickClientIp("abc", 1), null);
});

test("IPv6 허용", () => {
  assert.equal(pickClientIp("2001:db8::1", 1), "2001:db8::1");
});
