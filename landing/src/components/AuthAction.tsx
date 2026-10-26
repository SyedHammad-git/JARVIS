"use client";

import { useClerk, useAuth } from "@clerk/nextjs";
import { useRouter } from "next/navigation";

type AuthActionProps = {
  label: "Try JARVIS" | "Sign In" | "Sign Up";
  className?: string;
};

export function AuthAction({ label, className = "button-secondary" }: AuthActionProps) {
  const { isLoaded, isSignedIn } = useAuth();
  const clerk = useClerk();
  const router = useRouter();
  const destination = label === "Sign Up" ? "sign-up" : "sign-in";

  function activate() {
    if (!isLoaded) return;
    if (isSignedIn) {
      router.push("/app");
    } else if (destination === "sign-up") {
      clerk.openSignUp({ forceRedirectUrl: "/app" });
    } else {
      clerk.openSignIn({ forceRedirectUrl: "/app" });
    }
  }

  return (
    <button className={className} type="button" onClick={activate} disabled={!isLoaded}>
      {label}
    </button>
  );
}
