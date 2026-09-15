import type { Metadata } from "next";
import copy from "@/content/copy.ko.json";

export const metadata: Metadata = {
  title: `${copy.about.title} | 국내주식 조건 스크리닝 정보 서비스`,
};

/** 04-ux-design.md §2-5 — 서비스 안내 및 면책 상세. 정적 콘텐츠, API 호출 없음. */
export default function AboutPage() {
  return (
    <article>
      <h1>{copy.about.title}</h1>

      <section>
        <h2>{copy.about.serviceDefinitionHeading}</h2>
        <p>{copy.about.serviceDefinitionBody}</p>
      </section>

      <section>
        <h2>{copy.about.registrationHeading}</h2>
        <p>{copy.about.registrationBody}</p>
      </section>

      <section>
        <h2>{copy.about.dataDelayHeading}</h2>
        <p>{copy.about.dataDelayBody}</p>
      </section>

      <section>
        <h2>{copy.about.dataProcessingHeading}</h2>
        <p>{copy.about.dataProcessingBody}</p>
      </section>

      <section>
        <h2>{copy.about.dataSourceHeading}</h2>
        <p>{copy.about.dataSourceBody}</p>
      </section>

      <section>
        <h2>{copy.about.contactHeading}</h2>
        <p>{copy.about.contactBody}</p>
      </section>
    </article>
  );
}
