"use client";

import { useRouter } from "next/navigation";
import { useEffect } from "react";

export function AuthRedirectHandler() {
  const router = useRouter();

  useEffect(() => {
    function redirectToSignIn() {
      const returnTo = `${window.location.pathname}${window.location.search}`;
      router.replace(`/sign-in?redirect_url=${encodeURIComponent(returnTo)}`);
    }
    window.addEventListener("jarvis:sign-in-required", redirectToSignIn);
    return () => window.removeEventListener("jarvis:sign-in-required", redirectToSignIn);
  }, [router]);

  return null;
}
