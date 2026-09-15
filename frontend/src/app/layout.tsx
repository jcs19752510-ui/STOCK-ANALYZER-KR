import type { Metadata } from "next";
import type { ReactNode } from "react";
import { DisclaimerBanner } from "@/components/DisclaimerBanner";
import { Footer } from "@/components/Footer";
import { Header } from "@/components/Header";
import { SkipLink } from "@/components/SkipLink";
import copy from "@/content/copy.ko.json";
import "./globals.css";

export const metadata: Metadata = {
  title: "국내주식 조건 스크리닝 정보 서비스",
  description: copy.about.serviceDefinitionBody,
};

/**
 * 04-ux-design.md §2-0 — 공통 레이아웃(Root Layout), REQ-007 구현의 물리적
 * 위치. 모든 페이지가 이 레이아웃을 강제로 상속하므로(Next.js App Router),
 * 개별 화면이 배너를 빼먹거나 우회할 수 없다.
 */
export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="ko">
      <body>
        <SkipLink />
        <DisclaimerBanner />
        <Header />
        <main id="main-content">{children}</main>
        <Footer />
      </body>
    </html>
  );
}
