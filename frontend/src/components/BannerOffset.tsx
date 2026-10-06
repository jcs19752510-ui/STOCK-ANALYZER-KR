"use client";

import { useEffect } from "react";

/**
 * 면책 배너(상단 고정)의 실제 높이를 CSS 변수 `--banner-height`로 알린다. 전역 메뉴 줄이 배너 바로 아래에 붙어 따라오도록(sticky)
 * `top`에 이 값을 쓴다. 배너 문구가 줄바꿈되어 높이가 달라져도(폭·글자 크기) 크기 변화를 지켜보며 갱신한다.
 * 화면은 그리지 않는다. 스크립트가 실행되기 전에는 변수가 없어 `top: 0`으로 동작한다(메뉴는 배너 뒤에 가려질 뿐 깨지지 않는다).
 */
export function BannerOffset() {
  useEffect(() => {
    const banner = document.querySelector<HTMLElement>(".disclaimer-banner");
    if (!banner) return undefined;
    const root = document.documentElement;
    const apply = () => root.style.setProperty("--banner-height", `${banner.getBoundingClientRect().height}px`);
    apply();
    const observer = new ResizeObserver(apply);
    observer.observe(banner);
    return () => {
      observer.disconnect();
      root.style.removeProperty("--banner-height");
    };
  }, []);
  return null;
}
