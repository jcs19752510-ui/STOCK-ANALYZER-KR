import type { MetadataRoute } from "next";

/** 회원 전용 서비스라 검색엔진 색인을 허용하지 않는다(DEC-067). 로그인을 끈 로컬에서도 해가 없다. */
export default function robots(): MetadataRoute.Robots {
  return { rules: { userAgent: "*", disallow: "/" } };
}
